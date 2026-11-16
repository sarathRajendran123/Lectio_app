"""Collect source references for bounded, course-scoped lookup."""
from uuid import UUID

def cited_chunk_ids(value):
    """Find only chunk-reference fields in a report, not arbitrary IDs."""
    keys = {'evidence_chunk_ids', 'prepared_chunk_ids', 'transcript_chunk_ids', 'prepared_context_ids'}
    refs = set()
    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in keys and isinstance(child, list):
                    for ref in child:
                        try:
                            refs.add(str(UUID(str(ref))))
                        except (ValueError, TypeError, AttributeError):
                            continue
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return refs

