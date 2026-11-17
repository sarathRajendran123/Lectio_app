"""Find more useful source candidates without treating them as verified claims."""
import re
from collections import defaultdict
from agents.delivery_comparison import repeated_text_key

STOP = {'the','and','for','with','that','this','from','into','your','their','you',
        'students','student','master','understand','understands','functioning',
        'various','different','detail','have','able','explain','describe'}


def phrase_queries(text):
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    result = []
    for a, b in zip(words, words[1:]):
        phrase = a + ' ' + b
        if a not in STOP and b not in STOP and phrase not in result:
            result.append(phrase)
    return result[:5]


def useful_evidence(candidates, limit=3, *, preserve_order=False, objective_text=None):
    pages = defaultdict(set)
    for c in candidates:
        page = getattr(c, 'page_number', None)
        if page is not None:
            pages[(getattr(c, 'artifact_id', ''), repeated_text_key(c.text))].add(page)
    unique = {}
    for c in candidates:
        key = (getattr(c, 'artifact_id', ''), repeated_text_key(c.text))
        if len(pages[key]) >= 3 or re.match(r'^\s*\[\d+\]\s', c.text):
            continue
        if c.chunk_id not in unique or (not preserve_order and c.score > unique[c.chunk_id].score):
            unique[c.chunk_id] = c
    # When retrieval has already reranked the complete objective, keep that
    # ordering; length or phrase-specific scores must not override relevance.
    ranked = list(unique.values()) if preserve_order else sorted(
        unique.values(), key=lambda c: (len(c.text.split()) >= 14, c.score), reverse=True)
    # Deprioritise clearly administrative passages when the objective is not
    # about administration. Keep them as a fallback: a heuristic must not
    # silently discard possible evidence, especially for teamwork objectives.
    administrative = re.compile(
        r"(?i)\b(?:pruefungsleistung|prüfungsleistung|exam(?:ination)?\s+requirements?|"
        r"grading\s+(?:policy|criteria|requirements?)|course\s+(?:organisation|organization)|"
        r"kurzvorstellung|grading\s+prerequisite)\b"
    )
    administrative_intent = re.compile(
        r"(?i)\b(?:teams?|teamwork|gruppenarbeit|gruppen|group\s+work|"
        r"assessments?|exams?|examination|prüfungen?|pruefungen?|grading|bewertung)\b"
    )
    if objective_text and not (administrative.search(objective_text) or administrative_intent.search(objective_text)):
        ranked.sort(key=lambda c: bool(administrative.search(c.text)))
    selected=[]; seen=set()
    for c in ranked:
        page = getattr(c, 'page_number', None)
        loc = (getattr(c, 'artifact_id', ''), page)
        if page is not None and loc in seen:
            continue
        selected.append(c); seen.add(loc)
        if len(selected) == limit: break
    return selected
