from sqlalchemy import String, cast, create_engine, select, text

from db.chunk_visibility import current_chunk
from db.models.artifact import Chunk


def test_visibility_expression_compiles_for_postgresql():
    from sqlalchemy.dialects import postgresql
    sql = str(select(Chunk.id).where(current_chunk()).compile(
        dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'retrieval_active' in sql and 'coalesce' in sql.lower()


def test_current_chunk_includes_legacy_and_active_but_excludes_archived():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE chunks (id TEXT PRIMARY KEY, metadata JSON NOT NULL)'))
        db.execute(text("INSERT INTO chunks VALUES ('legacy', '{}'), ('active', '{\"retrieval_active\": true}'), ('old', '{\"retrieval_active\": false}')"))
        id_text = cast(Chunk.__table__.c.id, String)
        visible = set(db.scalars(select(id_text).where(current_chunk())).all())
        assert visible == {'legacy', 'active'}
        # Direct ID lookups still find historical citations.
        assert db.scalar(select(id_text).where(id_text == 'old')) == 'old'
