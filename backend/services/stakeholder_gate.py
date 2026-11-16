"""The Stakeholder agent's quality gate: nothing reaches the lecturer unchecked.

Every draft is assessed before it is shown. A weak draft is regenerated with adjusted instructions
(and, where the caller allows it, another model) up to a configured limit. Each check and each retry is
a trace event. A draft that still falls short is passed on with its score and the reasons, never
presented as if it had passed.

The checks are deterministic and explainable. The score is an internal quality signal, not a measure of
educational quality, and is kept separate from any lecturer evaluation.
"""
import re
from typing import Callable, Optional

from config import settings
from knowledge.bloom_classifier import classify_text
from rag.local_service import terms
from services import trace
from services.constraints import content_fingerprint

WEIGHTS = {"structure": 0.25, "grounding": 0.30, "relevance": 0.25, "intent": 0.10, "novelty": 0.10}
PROMPT_VERSION = "stakeholder-gate/1"


def assess(text: str, citations: list, *, content_type: str, target: str, intent: Optional[dict],
           rejected_fingerprints: set = frozenset(), threshold: Optional[float] = None) -> dict:
    """Score one draft in [0, 1] with named checks and plain-language issues."""
    threshold = settings.quality_threshold if threshold is None else threshold
    text = text or ""
    issues, checks = [], {}

    # structure: complete enough to be a usable draft of its type
    structure = 1.0
    if len(text.strip()) < 80:
        structure = 0.0; issues.append("The draft is too short to be usable.")
    elif content_type in ("quiz", "assessment", "assessment_suggestion") and "?" not in text and not re.search(r"(?i)\b(question|aufgabe|frage)\b", text):
        structure = 0.4; issues.append("No question was found in an assessment draft.")
    elif content_type == "slide_outline" and len(re.findall(r"(?im)^\s*(?:#{2,4}\s+\S|(?:slide|folie)\s*\d+)", text)) < 4:
        structure = 0.4; issues.append("A slide outline needs at least three slides with their own headings.")   # 4 = title + 3 slides
    elif content_type == "clo" and classify_text(text)[0] is None:
        structure = 0.5; issues.append("The objective has no measurable action verb.")
    checks["structure"] = structure

    # grounding: every draft must rest on supplied source excerpts (quotes are validated upstream)
    grounding = 1.0 if citations else 0.0
    if not citations:
        issues.append("The draft cites no source excerpt.")
    checks["grounding"] = grounding

    # relevance: does the draft talk about what it was asked to address?
    wanted = {w[:5] for w in terms(target or "")}   # 5-letter stems so 'collision' matches 'collisions'
    found = {w[:5] for w in terms(text)}
    overlap = len(wanted & found) / len(wanted) if wanted else 1.0
    relevance = min(1.0, overlap / 0.3)
    if relevance < 0.5:
        issues.append("The draft barely mentions the topic it was asked to address.")
    checks["relevance"] = round(relevance, 3)

    # intent: stay within the cognitive levels the lecturer intends (neutral when none are stated)
    level, _ = classify_text(text)
    levels = (intent or {}).get("cognitive_levels") or []
    intent_score = 1.0
    if levels and level and level not in levels:
        intent_score = 0.3; issues.append(f"The draft reads as '{level}' level; the course intent asks for {', '.join(levels)}.")
    checks["intent"] = intent_score
    checks["intent_stated"] = bool(intent)

    # novelty: never offer again what the lecturer already rejected
    repeated = content_fingerprint(text) in rejected_fingerprints
    checks["novelty"] = 0.0 if repeated else 1.0
    if repeated:
        issues.append("This is the same draft the lecturer already rejected.")

    score = round(sum(WEIGHTS[k] * checks[k] for k in WEIGHTS), 3)
    hard_fail = repeated or grounding == 0.0 or structure == 0.0
    return {"score": score, "threshold": threshold, "passed": score >= threshold and not hard_fail,
            "issues": issues, "checks": checks, "bloom_level": level}


def rationale(*, content_type: str, style: str, model: str, target: str, citations: list, review: dict) -> str:
    """One or two plain sentences on why this variant exists and how far to trust it."""
    sources = sorted({(c.get("citation") or "").split(",")[0].strip() for c in citations if c.get("citation")})
    grounded = f"It rests on {len(citations)} excerpt(s)" + (f" from {', '.join(sources[:3])}" if sources else "") if citations else "It cites no source"
    lead = f"A {style} {content_type.replace('_', ' ')} draft" if style else f"A {content_type.replace('_', ' ')} draft"
    verdict = (f"It passed the internal check ({review['score']:.0%})." if review["passed"]
               else f"It did NOT pass the internal check ({review['score']:.0%}, needs {review['threshold']:.0%}): " + " ".join(review["issues"]))
    tries = f" Produced after {review['attempts']} attempts." if review.get("attempts", 1) > 1 else ""
    return f"{lead} written by {model or 'the configured model'} to address: {(target or '').strip()[:160]}. {grounded}. {verdict}{tries}"


def produce(generate: Callable, *, content_type: str, target: str, intent: Optional[dict], constraint_ids: list,
            rejected_fingerprints: set, guidance: str = "", style: str = "", models: Optional[list] = None,
            subject: Optional[tuple] = None) -> tuple:
    """Run `generate(extra_instructions, model)` until a draft passes or the retry limit is reached.

    `generate` returns an object with `.content`, `.citations`, `.model` and `.tokens_used`.
    Returns (item, review). Raises the last generation error only if no attempt produced a draft.
    """
    models = [m for m in (models or [None])]
    limit = max(0, settings.quality_max_retries)
    best, best_review, last_error, extra = None, None, None, guidance
    for attempt in range(limit + 1):
        model = models[min(attempt, len(models) - 1)]
        try:
            item = generate(extra, model)
        except Exception as exc:                  # a failed generation is a failed attempt, recorded like any other
            last_error = exc
            trace.emit("quality_check", {"attempt": attempt + 1, "passed": False, "score": 0.0, "issues": [f"generation failed: {str(exc)[:200]}"],
                                         "gate_version": PROMPT_VERSION, "model": model}, subject=subject)
            reason = f"generation failed: {str(exc)[:120]}"
        else:
            review = assess(item.content, item.citations, content_type=content_type, target=target, intent=intent,
                            rejected_fingerprints=rejected_fingerprints)
            review["attempts"] = attempt + 1
            trace.emit("quality_check", {"attempt": attempt + 1, "passed": review["passed"], "score": review["score"],
                                         "threshold": review["threshold"], "issues": review["issues"], "checks": review["checks"],
                                         "gate_version": PROMPT_VERSION, "model": getattr(item, "model", model),
                                         "constraint_ids": constraint_ids}, subject=subject)
            if best_review is None or review["score"] > best_review["score"]:
                best, best_review = item, review
            if review["passed"]:
                break
            reason = "; ".join(review["issues"]) or "score below threshold"
        if attempt < limit:
            next_model = models[min(attempt + 1, len(models) - 1)]
            trace.emit("retry", {"attempt": attempt + 2, "reason": reason, "adjusted_instructions": True,
                                 "switched_model": next_model != model, "next_model": next_model}, subject=subject)
            extra = (guidance + "\n\n" if guidance else "") + (
                "QUALITY REVIEW of your previous attempt found these problems. Fix every one and do not repeat the earlier wording: " + reason)
            if "quotation does not occur verbatim" in reason:
                extra += ("\nFor each support quote, select a short continuous excerpt directly from its numbered source. "
                          "Copy it exactly, including punctuation, capitalization, and spacing; do not translate or paraphrase the quote.")
    if best is None:
        raise last_error if last_error else RuntimeError("No draft was produced.")
    best_review["attempts"] = max(best_review.get("attempts", 1), attempt + 1)
    best_review["rationale"] = rationale(content_type=content_type, style=style, model=getattr(best, "model", ""), target=target,
                                         citations=best.citations, review=best_review)
    return best, best_review
