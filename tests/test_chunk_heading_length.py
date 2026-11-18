from rag.chunking.semantic_chunker import SemanticChunker
from rag.parsers.base_parser import ParsedBlock, ParsedDocument


def test_long_section_metadata_is_bounded_without_truncating_content():
    heading = "A" * 648
    body = "This paragraph contains the actual teaching content."
    document = ParsedDocument(
        source_path="slides.pdf", file_type="pdf", artifact_type="slides",
        blocks=[ParsedBlock(text=body, block_type="paragraph", section_title=heading)],
    )
    chunks = SemanticChunker().chunk(document, "artifact", "course")
    assert chunks
    assert all(len(chunk.section_title) == 500 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == body
