"""Keep superseded chunks accessible by ID but out of current course operations."""
from sqlalchemy import func
from db.models.artifact import Chunk


def current_chunk():
    # Legacy records have no flag and remain visible.
    return func.coalesce(Chunk.metadata_["retrieval_active"].as_boolean(), True).is_(True)
