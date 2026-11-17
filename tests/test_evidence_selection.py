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


def test_full_objective_order_is_preserved_and_admin_passages_deprioritised():
    items = [item('admin', 'Prüfungsleistung – Teams Die Studierenden bilden feste Teams.', 6, .99),
             item('relevant', 'Deep learning is a key technology for applications across several industries.', 5, .65),
             item('second', 'Industrial machine learning improves quality and logistics in manufacturing.', 8, .60)]
    selected = useful_evidence(items, limit=3, preserve_order=True,
                               objective_text='Explain the importance of deep learning across industries')
    assert [c.chunk_id for c in selected] == ['relevant', 'second', 'admin']
    assert useful_evidence(items, limit=3, preserve_order=True,
                           objective_text='Prüfungsleistung teams')[0].chunk_id == 'admin'
    assert useful_evidence(items, limit=3, preserve_order=True,
                           objective_text='Die Studierenden arbeiten im Team')[0].chunk_id == 'admin'


def test_query_scores_do_not_reorder_results_from_different_searches():
    items = [item('best_full_objective', 'Deep learning transforms applications across fields.', 1, .5),
             item('next', 'A related discussion about data and models.', 2, .99)]
    assert [c.chunk_id for c in useful_evidence(items, preserve_order=True)] == [
        'best_full_objective', 'next']
