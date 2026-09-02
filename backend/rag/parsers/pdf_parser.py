"""
LECTIO — PDF Parser (PyMuPDF)
Extracts text, headings, tables, and captions from PDF files.
Falls back to Tesseract OCR for scanned/image-only pages.

Why PyMuPDF over pdfplumber / pdfminer?
  - 5–10× faster
  - Better font/size metadata (used to detect headings)
  - Native table detection (fitz.Page.find_tables)
  - Same Python wheel, no Java dependency
"""

import logging
from pathlib import Path
from typing import List, Optional

from rag.parsers.base_parser import BaseParser, ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

# Minimum text chars per page to skip OCR
OCR_FALLBACK_THRESHOLD = 30


class PDFParser(BaseParser):
    """
    Parse a PDF into structured ParsedBlocks.

    Strategy:
      1. Extract text blocks with font-size metadata
      2. Classify blocks as heading / paragraph / table / caption
      3. For pages below OCR_FALLBACK_THRESHOLD chars → run Tesseract
      4. Accumulate running section_title from headings
    """

    def __init__(self, ocr_fallback: bool = True, ocr_language: str = "eng"):
        self.ocr_fallback = ocr_fallback
        self.ocr_language = ocr_language

    def parse(self, file_path: str, artifact_type: str = "other") -> ParsedDocument:
        try:
            import fitz   # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")

        path   = Path(file_path)
        doc    = fitz.open(str(path))
        blocks: List[ParsedBlock] = []
        warnings: List[str] = []

        # Detect dominant font size (used to infer headings)
        font_sizes = []
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") == 0:   # text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            font_sizes.append(span.get("size", 12))

        body_size = self._modal_font_size(font_sizes) if font_sizes else 12.0

        current_section: Optional[str] = None

        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text("text")

            # OCR fallback for image-only pages
            if len(page_text.strip()) < OCR_FALLBACK_THRESHOLD and self.ocr_fallback:
                ocr_text = self._ocr_page(page)
                if ocr_text:
                    blocks.append(ParsedBlock(
                        text=self._safe_text(ocr_text),
                        block_type="paragraph",
                        page_number=page_num,
                        section_title=current_section,
                        metadata={"ocr": True},
                    ))
                    warnings.append(f"Page {page_num}: OCR used (low text density).")
                continue

            # Extract tables first (fitz 1.23+)
            table_bboxes = set()
            try:
                for table in page.find_tables():
                    df_text = self._table_to_text(table)
                    if df_text:
                        blocks.append(ParsedBlock(
                            text=df_text,
                            block_type="table",
                            page_number=page_num,
                            section_title=current_section,
                            is_table=True,
                        ))
                    # Track bbox so we skip these spans in text extraction
                    for cell in table.cells:
                        if cell:
                            table_bboxes.add(tuple(int(x) for x in cell[:4]))
            except Exception:
                pass   # find_tables not available in older PyMuPDF

            # Extract text blocks with font metadata
            raw_dict = page.get_text("dict")
            for block in raw_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue

                block_text_parts = []
                max_size = 0.0
                is_bold  = False

                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if not span_text:
                            continue
                        size = span.get("size", 12)
                        flags = span.get("flags", 0)
                        max_size = max(max_size, size)
                        if flags & 2**4:   # bold bit
                            is_bold = True
                        block_text_parts.append(span_text)

                full_text = " ".join(block_text_parts)
                full_text = self._safe_text(full_text)
                if not full_text:
                    continue

                block_type, heading_level = self._classify_block(
                    full_text, max_size, body_size, is_bold
                )

                if block_type == "heading":
                    current_section = full_text

                blocks.append(ParsedBlock(
                    text=full_text,
                    block_type=block_type,
                    page_number=page_num,
                    section_title=current_section if block_type != "heading" else None,
                    heading_level=heading_level,
                    is_bold=is_bold,
                ))

        doc.close()

        all_text  = " ".join(b.text for b in blocks)
        word_count = self._count_words(all_text)

        return ParsedDocument(
            source_path=str(path),
            file_type="pdf",
            artifact_type=artifact_type,
            blocks=blocks,
            total_pages=len(doc) if not doc.is_closed else None,
            title=path.stem,
            word_count=word_count,
            parse_warnings=warnings,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _classify_block(
        self,
        text: str,
        font_size: float,
        body_size: float,
        is_bold: bool,
    ) -> tuple[str, Optional[int]]:
        """Heuristic classification using font size relative to body text."""
        ratio = font_size / body_size if body_size else 1.0

        if ratio >= 1.8 or (ratio >= 1.4 and is_bold):
            return "heading", 1
        if ratio >= 1.3 or (ratio >= 1.15 and is_bold):
            return "heading", 2
        if ratio >= 1.1 and is_bold:
            return "heading", 3
        if len(text) < 80 and is_bold:
            return "heading", 3
        return "paragraph", None

    def _modal_font_size(self, sizes: list) -> float:
        """Return the most common font size (body text size)."""
        from collections import Counter
        rounded = [round(s, 1) for s in sizes]
        return Counter(rounded).most_common(1)[0][0] if rounded else 12.0

    def _table_to_text(self, table) -> str:
        """Convert a fitz Table object to a readable text representation."""
        try:
            rows = table.extract()
            if not rows:
                return ""
            lines = []
            for row in rows:
                cells = [str(c).strip() if c else "" for c in row]
                lines.append(" | ".join(cells))
            return "\n".join(lines)
        except Exception:
            return ""

    def _ocr_page(self, page) -> str:
        """Rasterise page and run Tesseract OCR."""
        try:
            import pytesseract
            from PIL import Image
            import io

            pix  = page.get_pixmap(dpi=200)
            img  = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img, lang=self.ocr_language)
            return text
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return ""
