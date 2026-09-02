"""
LECTIO — DOCX Parser (python-docx)
Extracts paragraphs, headings, and tables from Word documents.
Heading hierarchy is preserved — critical for syllabus/module manual parsing
where Heading 1 = Module, Heading 2 = Topic, Heading 3 = Subtopic.
"""

import logging
from pathlib import Path
from typing import List, Optional

from rag.parsers.base_parser import BaseParser, ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)

HEADING_STYLES = {
    "heading 1": 1, "heading 2": 2, "heading 3": 3,
    "heading 4": 4, "heading 5": 5, "heading 6": 6,
    "title": 1,
}


class DocxParser(BaseParser):

    def parse(self, file_path: str, artifact_type: str = "other") -> ParsedDocument:
        try:
            from docx import Document
        except ImportError:
            raise ImportError("python-docx not installed. Run: pip install python-docx")

        path = Path(file_path)
        doc  = Document(str(path))

        blocks: List[ParsedBlock] = []
        warnings: List[str] = []
        current_section: Optional[str] = None
        para_index = 0

        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            # ── Paragraph ─────────────────────────────────────────────────────
            if tag == "p":
                from docx.text.paragraph import Paragraph
                para      = Paragraph(element, doc)
                text      = para.text.strip()
                if not text:
                    continue

                style_name  = para.style.name.lower() if para.style else ""
                heading_lvl = HEADING_STYLES.get(style_name)
                is_bold     = any(run.bold for run in para.runs if run.text.strip())

                if heading_lvl is not None:
                    current_section = text
                    blocks.append(ParsedBlock(
                        text=self._safe_text(text),
                        block_type="heading",
                        section_title=None,
                        heading_level=heading_lvl,
                        is_bold=True,
                        metadata={"style": style_name, "para_index": para_index},
                    ))
                else:
                    blocks.append(ParsedBlock(
                        text=self._safe_text(text),
                        block_type="paragraph",
                        section_title=current_section,
                        is_bold=is_bold,
                        metadata={"style": style_name, "para_index": para_index},
                    ))
                para_index += 1

            # ── Table ─────────────────────────────────────────────────────────
            elif tag == "tbl":
                try:
                    from docx.table import Table
                    table = Table(element, doc)
                    rows  = []
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        rows.append(" | ".join(cells))
                    table_text = "\n".join(rows)
                    if table_text.strip():
                        blocks.append(ParsedBlock(
                            text=self._safe_text(table_text),
                            block_type="table",
                            section_title=current_section,
                            is_table=True,
                        ))
                except Exception as e:
                    warnings.append(f"Table parse error: {e}")

        all_text   = " ".join(b.text for b in blocks)
        word_count = self._count_words(all_text)

        return ParsedDocument(
            source_path=str(path),
            file_type="docx",
            artifact_type=artifact_type,
            blocks=blocks,
            title=path.stem,
            word_count=word_count,
            parse_warnings=warnings,
        )
