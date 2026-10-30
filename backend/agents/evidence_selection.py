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


def useful_evidence(candidates, limit=3):
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
        if c.chunk_id not in unique or c.score > unique[c.chunk_id].score:
            unique[c.chunk_id] = c
    ranked = sorted(unique.values(), key=lambda c: (len(c.text.split()) >= 14, c.score), reverse=True)
    selected=[]; seen=set()
    for c in ranked:
        page = getattr(c, 'page_number', None)
        loc = (getattr(c, 'artifact_id', ''), page)
        if page is not None and loc in seen:
            continue
        selected.append(c); seen.add(loc)
        if len(selected) == limit: break
    return selected
