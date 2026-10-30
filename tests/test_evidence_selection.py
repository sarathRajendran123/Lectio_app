from types import SimpleNamespace
from agents.evidence_selection import useful_evidence, phrase_queries


def item(ident, text, page, score):
    return SimpleNamespace(chunk_id=ident, text=text, page_number=page, artifact_id='doc', score=score)


def test_retrieval_suppresses_repeated_footer_and_bibliography():
    items = [item(f'f{i}', f'Deep Learning course footer {i}', i, .99) for i in range(1, 5)]
    items += [item('ref', '[15] Smith, J. Neural Networks (2001). Journal reference.', 40, .95),
              item('heading', 'Neural Networks', 3, .9),
              item('body', 'Neural networks use layers of connected neurons to transform data and learn parameters during training.', 5, .5)]
    selected = useful_evidence(items)
    assert selected[0].chunk_id == 'body'
    assert not any(c.chunk_id.startswith('f') or c.chunk_id == 'ref' for c in selected)


def test_translation_generates_bounded_search_phrases():
    queries=phrase_queries('You master the mathematical and algorithmic foundations of neural networks and understand various architectures in detail.')
    assert 'neural networks' in queries
    assert len(queries) <= 5
