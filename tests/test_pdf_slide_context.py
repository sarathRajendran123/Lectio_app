from rag.chunking.semantic_chunker import SemanticChunker
from rag.parsers.base_parser import ParsedBlock, ParsedDocument


def test_pdf_slides_keep_question_and_explanation_together_on_same_page():
    blocks = [
        ParsedBlock('Local minima?', 'heading', page_number=1),
        ParsedBlock('Saddle points are common in high dimensions.', 'paragraph', page_number=1),
        ParsedBlock('Optimization', 'heading', page_number=2),
        ParsedBlock('The learning rate controls update size.', 'paragraph', page_number=2),
    ]
    doc = ParsedDocument('slides.pdf', 'pdf', 'slides', blocks)
    chunks = SemanticChunker(use_semantic_split=True).chunk(doc, 'artifact', 'course')
    assert len(chunks) == 2
    assert chunks[0].page_number == 1 and 'Local minima?' in chunks[0].text
    assert 'Saddle points are common' in chunks[0].text
    assert 'learning rate' not in chunks[0].text
    assert chunks[1].page_number == 2 and 'learning rate' in chunks[1].text
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_slide_without_page_number_never_merges_with_another_unknown_page():
    blocks = [ParsedBlock('A first separate block.', 'paragraph'), ParsedBlock('A second separate block.', 'paragraph')]
    chunks = SemanticChunker().chunk(ParsedDocument('x.pdf', 'pdf', 'slides', blocks), 'a', 'c')
    assert len(chunks) == 2


def test_large_pdf_slide_remains_bounded():
    body = 'Many important slide words. ' * 140
    chunks = SemanticChunker(max_tokens=100).chunk(
        ParsedDocument('slides.pdf', 'pdf', 'slides', [ParsedBlock(body, 'paragraph', page_number=1)]), 'a', 'c')
    assert len(chunks) > 1
    assert all(len(c.text) <= 400 and c.page_number == 1 for c in chunks)
    assert ''.join(c.text for c in chunks) == body


def test_non_slide_pdf_keeps_original_block_boundaries():
    blocks = [ParsedBlock('First paragraph.', 'paragraph', page_number=1), ParsedBlock('Second paragraph.', 'paragraph', page_number=1)]
    chunks = SemanticChunker().chunk(ParsedDocument('manual.pdf', 'pdf', 'syllabus', blocks), 'a', 'c')
    assert [c.text for c in chunks] == ['First paragraph.', 'Second paragraph.']
