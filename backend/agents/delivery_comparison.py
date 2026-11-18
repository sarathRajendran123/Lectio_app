"""Evidence-based, topic-level comparison of prepared and transcript sources.

Matching does not establish that two documents describe the same lecture or
that a topic was (or was not) taught. A lecturer must verify the source pair.
"""

from collections import defaultdict
import re

MIN_RELEVANCE = 0.45
MAX_TOPICS = 20


def repeated_text_key(text):
    text = re.sub(r'\s+', ' ', text).strip().casefold()
    return re.sub(r'\s+\d{1,4}$', '', text)


def select_evidence(candidates, week):
    """Remove repeated cross-page snippets and diversify by source location."""
    candidates = [c for c in candidates if c.score >= MIN_RELEVANCE and
                  (c.week_number is None or c.week_number == week)]
    locations = defaultdict(set)
    for c in candidates:
        if c.page_number is not None:
            locations[(c.artifact_id, repeated_text_key(c.text))].add(c.page_number)
    selected, seen_locations = [], set()
    for c in candidates:
        key = (c.artifact_id, repeated_text_key(c.text))
        if len(locations[key]) >= 3:
            continue
        loc = (c.artifact_id, c.page_number, c.slide_number)
        if (c.page_number is not None or c.slide_number is not None) and loc in seen_locations:
            continue
        selected.append(c)
        seen_locations.add(loc)
        if len(selected) == 3:
            break
    return selected


def compare_delivery(modules, course_id, retrieve, context_loader=None):
    rows = []
    for module in modules:
        for week in module.get('weeks', []):
            for topic in week.get('topics', []):
                if len(rows) >= MAX_TOPICS:
                    return rows, True
                title = topic.get('title', '').strip()
                if not title:
                    continue
                sides = {}
                for label, kind in (('prepared', 'slides'), ('transcript', 'transcript')):
                    candidates = retrieve(title, course_id, top_k=40,
                                          where={'artifact_type': kind})
                    # Explicitly different week labels must never be presented
                    # as a pair for the planned week. Unknown labels remain
                    # candidates, but require lecturer confirmation.
                    sides[label] = select_evidence(candidates, week.get('week_number'))
                prepared, transcript = sides['prepared'], sides['transcript']
                if prepared and transcript:
                    status = 'both_have_matching_evidence'
                elif prepared:
                    status = 'transcript_evidence_not_found'
                elif transcript:
                    status = 'prepared_evidence_not_found'
                else:
                    status = 'no_matching_evidence'
                rows.append({
                    'module': module.get('title'), 'week': week.get('week_number'),
                    'topic': title, 'topic_id': topic.get('id'), 'status': status,
                    'prepared_chunk_ids': [c.chunk_id for c in prepared],
                    'transcript_chunk_ids': [c.chunk_id for c in transcript],
                    'prepared_context_ids': context_loader(course_id, prepared) if context_loader and prepared else [],
                    'notice': ('Topic-level retrieval only; confirm the sources belong '
                               'to the same lecture and check their contents. Missing '
                               'evidence does not prove a teaching divergence.'),
                })
    return rows, False
