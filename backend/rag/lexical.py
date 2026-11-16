"""Lexical scoring of the offline test backend. Hash vectors are lexical, NOT semantic AI embeddings.
No database import, so evaluation scripts can use it on their own."""
import hashlib
import math
import re

STOP = {'the','and','for','with','that','this','from','will','able','students','learning','outcome','explain','describe','apply','understand','analyse','analyze','evaluate','create','lecture','slides','covering'}
STOP |= {'der','die','das','und','ist','nicht','mit','von','den','für','auf','ein','eine','wird','sich','als','sie','werden','können','studierenden','studierende','wie','auch','oder','dem','des','zur','zum','bei','nach','über'}
def terms(text):
    return [w for w in re.findall(r'\b\w{3,}\b',text.lower()) if w not in STOP]
def vector(text):
    values = [0.] * 256
    for word in terms(text):
        index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], 'big') % 256
        values[index] += 1
    length = math.sqrt(sum(v*v for v in values)) or 1
    return [v/length for v in values]

def lexical_score(query, text, text_vector=None):
    """Offline test score: share of query words found in the text plus hash-vector cosine. 0 when no word is shared."""
    qterms = set(terms(query))
    overlap = qterms & set(terms(text))
    if not overlap:
        return 0.
    cosine = sum(a*b for a, b in zip(text_vector or vector(text), vector(query)))
    return round(0.65*len(overlap)/max(1, len(qterms)) + 0.35*max(0, cosine), 4)
