"""
LECTIO — Bloom's Taxonomy Classifier

Classifies CLO text and assessment questions to one of the six
cognitive levels in Bloom's Revised Taxonomy (Anderson & Krathwohl, 2001).

Method:
  1. Keyword matching against curated verb lists (fast, deterministic)
  2. If no verb match → LLM-based classification (accurate, costs tokens)
  3. Returns level name + the matched/inferred verb

Why keyword-first?
  - 80%+ of CLOs use standard Bloom's verbs ("implement", "analyse", "evaluate")
  - Keyword matching is instant and free
  - LLM fallback handles novel phrasing ("work out", "make sense of", etc.)
"""

import re
from typing import Optional, Tuple

# ── Verb lexicon (Bloom's Revised Taxonomy) ───────────────────────────────────
# Source: Anderson & Krathwohl (2001) + Forehand (2010) additions

BLOOM_VERBS: dict[str, list[str]] = {
    "remember": [
        "define", "list", "recall", "recognise", "recognize", "identify",
        "name", "state", "label", "match", "reproduce", "memorise",
        "memorize", "repeat", "duplicate", "quote", "outline",
    ],
    "understand": [
        "explain", "describe", "summarise", "summarize", "paraphrase",
        "classify", "compare", "contrast", "interpret", "translate",
        "discuss", "distinguish", "estimate", "give examples", "illustrate",
        "infer", "predict", "report", "restate", "review", "select",
    ],
    "apply": [
        "implement", "use", "demonstrate", "apply", "calculate", "compute",
        "construct", "execute", "modify", "operate", "produce", "show",
        "solve", "write", "develop", "perform", "practice", "employ",
        "utilise", "utilize", "carry out", "build", "complete",
    ],
    "analyse": [
        "analyse", "analyze", "differentiate", "examine", "breakdown",
        "break down", "categorise", "categorize", "compare", "deconstruct",
        "detect", "diagram", "dissect", "distinguish", "divide", "focus",
        "inspect", "investigate", "outline", "question", "separate", "test",
    ],
    "evaluate": [
        "evaluate", "assess", "judge", "critique", "justify", "defend",
        "argue", "appraise", "choose", "conclude", "criticise", "criticize",
        "decide", "determine", "dispute", "estimate", "prioritise",
        "prioritize", "rank", "recommend", "select", "support", "value",
    ],
    "create": [
        "create", "design", "develop", "formulate", "generate", "plan",
        "produce", "propose", "construct", "compose", "devise", "imagine",
        "invent", "make", "organise", "organize", "compile", "assemble",
        "combine", "integrate", "modify", "reconstruct", "revise",
        "write", "hypothesise", "hypothesize",
    ],
}

# Pre-build a flat lookup: verb → level (longest match wins for multi-word verbs)
_VERB_TO_LEVEL: dict[str, str] = {}
for _level, _verbs in BLOOM_VERBS.items():
    for _v in _verbs:
        _VERB_TO_LEVEL[_v] = _level

LEVEL_ORDER = ["remember", "understand", "apply", "analyse", "evaluate", "create"]


def classify_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Classify a CLO or question to a Bloom's level.

    Returns:
        (level, matched_verb)  or  (None, None) if no match found
    """
    text_lower = text.lower()

    # Try multi-word verbs first (e.g. "break down" before "break")
    multi_word = {v: l for v, l in _VERB_TO_LEVEL.items() if " " in v}
    for verb in sorted(multi_word, key=len, reverse=True):
        if verb in text_lower:
            return _VERB_TO_LEVEL[verb], verb

    # Single-word verbs: match whole words only
    for verb, level in sorted(_VERB_TO_LEVEL.items(), key=lambda x: len(x[0]), reverse=True):
        if " " in verb:
            continue
        pattern = rf"\b{re.escape(verb)}\b"
        if re.search(pattern, text_lower):
            return level, verb

    return None, None


def classify_with_llm(text: str, llm) -> Tuple[str, Optional[str]]:
    """
    LLM fallback classifier for text that contains no standard Bloom's verbs.
    Uses the LLM to identify the intended cognitive level.

    Returns:
        (level, inferred_verb)
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = f"""You are a Bloom's Taxonomy expert.
Classify the following learning objective or assessment question to ONE of these six levels:
remember | understand | apply | analyse | evaluate | create

Text: "{text}"

Respond with ONLY a JSON object:
{{"level": "<level>", "verb": "<key_action_verb_in_text>"}}

No explanation, no markdown, just the JSON."""

    try:
        response = llm.invoke([
            SystemMessage(content="You classify educational text to Bloom's Taxonomy levels."),
            HumanMessage(content=prompt),
        ])
        import json
        data  = json.loads(response.content.strip())
        level = data.get("level", "").lower()
        verb  = data.get("verb", "")
        if level in LEVEL_ORDER:
            return level, verb
    except Exception:
        pass

    return "understand", None   # Safe default


def compare_levels(level_a: str, level_b: str) -> int:
    """
    Compare two Bloom's levels.
    Returns: -1 if a < b, 0 if equal, +1 if a > b
    """
    try:
        ia = LEVEL_ORDER.index(level_a.lower())
        ib = LEVEL_ORDER.index(level_b.lower())
        return 0 if ia == ib else (1 if ia > ib else -1)
    except ValueError:
        return 0


def level_to_int(level: str) -> int:
    """Convert level name to integer (remember=1 … create=6)."""
    try:
        return LEVEL_ORDER.index(level.lower()) + 1
    except ValueError:
        return 0
