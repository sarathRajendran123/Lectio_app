"""
LECTIO — Parser Router
Returns the correct parser instance for a given file extension.
Single import point for all parsing logic.
"""

from rag.parsers.base_parser import BaseParser, ParsedDocument
from rag.parsers.pdf_parser import PDFParser
from rag.parsers.pptx_parser import PptxParser
from rag.parsers.docx_parser import DocxParser
from rag.parsers.transcript_parser import PlainTextParser, TranscriptParser


def get_parser(file_extension: str) -> BaseParser:
    """
    Return the appropriate parser for a file extension.

    Args:
        file_extension: lowercase extension WITHOUT dot (e.g. "pdf", "pptx")

    Raises:
        ValueError: if no parser is registered for the extension
    """
    parsers: dict[str, BaseParser] = {
        "pdf":  PDFParser(ocr_fallback=True),
        "docx": DocxParser(),
        "pptx": PptxParser(),
        "txt":  PlainTextParser(),
        "vtt":  TranscriptParser(),
    }
    parser = parsers.get(file_extension.lower().lstrip("."))
    if parser is None:
        raise ValueError(
            f"No parser available for '.{file_extension}'. "
            f"Supported: {', '.join(parsers)}"
        )
    return parser


__all__ = [
    "get_parser",
    "BaseParser", "ParsedDocument",
    "PDFParser", "PptxParser", "DocxParser",
    "PlainTextParser", "TranscriptParser",
]
