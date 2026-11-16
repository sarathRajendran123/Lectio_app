"""Planned vs delivered: compare what the lecture transcript says with the prepared slides and notes.

Method, kept explainable on purpose:
  1. Each planned section (a slide or a paragraph of notes) is split into its points (sentences).
  2. The transcript is split into teaching segments (a new segment starts at a transition such as
     "next" / "finally" / "als Nächstes", or when a sentence shares no content word with the running segment).
  3. A planned point counts as addressed when some transcript segment contains enough of its content
     words, or (with the neural backend) is semantically close to it. Wording may differ: a point is
     never required to appear literally.
  4. A section is covered when enough of its points are addressed, partial when only some are, and not
     covered when none is.
  5. A substantive transcript segment that matches no planned section is reported as taught but not
     planned. Segments that read as an example or aside next to planned content are listed, not flagged.

What this is not: it measures whether planned content is traceable in the transcript, never how well it
was taught. A missing match can mean an incomplete or badly transcribed recording. With the lexical test
backend only shared words count, so true synonyms need the neural backend.
"""
import re
from typing import Callable, Optional

from config import settings
from rag.local_service import terms

PLANNED_TYPES = ("slides", "reading", "other")
TRANSCRIPT_TYPES = ("transcript",)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9\"'(])")
_TRANSITION = re.compile(r"^\W*(next|now|finally|then|moving on|let us turn|let's turn|let's move|secondly|thirdly|lastly|"
                         r"als nächstes|nun|jetzt|anschließend|schließlich|zum schluss|kommen wir|weiter geht)\b", re.I)
_EXAMPLE = re.compile(r"\b(for example|for instance|as an example|imagine|think of|let me give|anecdote|by the way|"
                      r"zum beispiel|beispielsweise|stellen sie sich|stell dir|übrigens|nebenbei)\b", re.I)


def stems(text: str) -> set:
    """Content words cut to six letters, so 'collision', 'collisions' and 'collide'-like forms mostly meet."""
    return {w[:6] if len(w) > 6 else w[:5] if len(w) > 5 else w for w in terms(text)}


def sentences(text: str) -> list:
    return [s.strip() for s in _SENTENCE.split(" ".join((text or "").split())) if s.strip()]


def _ref(chunk, **extra) -> dict:
    meta = getattr(chunk, "metadata", None) or {}
    return {"chunk_id": chunk.chunk_id, "document": meta.get("filename"), "slide": chunk.slide_number, "page": chunk.page_number,
            "timestamp": meta.get("timestamp"), **extra}


def planned_sections(chunks: list) -> list:
    """One section per slide chunk or paragraph: a title and the points it makes."""
    sections = []
    for chunk in chunks:
        for part in [p for p in re.split(r"\n\s*\n", chunk.text or "") if p.strip()]:
            parts = sentences(part)
            if not parts:
                continue
            heading = len(parts) > 1 and len(parts[0].split()) <= 6
            title = (parts[0].rstrip(".:") if heading else (chunk.section_title or " ".join(parts[0].split()[:8])))
            points = [p for p in (parts[1:] if heading else parts) if len(stems(p)) >= 2]
            if points:
                sections.append({"title": title, "points": points, "text": " ".join(parts), "chunk": chunk})
    return sections


def transcript_segments(chunks: list, max_sentences: int = 6) -> list:
    """Teaching segments: consecutive sentences that stay on one subject."""
    segments = []
    for chunk in chunks:
        current, seen = [], set()
        for sentence in sentences(chunk.text or ""):
            words = stems(sentence)
            shift = bool(current) and (bool(_TRANSITION.match(sentence)) or len(current) >= max_sentences
                                       or (len(current) >= 2 and words and not (words & seen)))
            if shift:
                segments.append({"text": " ".join(current), "chunk": chunk, "index": len(segments)})
                current, seen = [], set()
            current.append(sentence)
            seen |= words
        if current:
            segments.append({"text": " ".join(current), "chunk": chunk, "index": len(segments)})
    for segment in segments:
        segment["stems"] = stems(segment["text"])
    return segments


def _cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def verify(planned_chunks: list, transcript_chunks: list, embed: Optional[Callable] = None) -> dict:
    """Compare transcript with planned material. `embed(texts) -> unit vectors` enables semantic matching."""
    sections = planned_sections(planned_chunks)[:settings.delivery_max_sections]
    segments = transcript_segments(transcript_chunks)[:settings.delivery_max_segments]
    if not sections or not segments:
        missing = "transcript" if sections else "slides or notes" if segments else "transcript and slides"
        return {"ran": False, "reason": f"No {missing} uploaded, so what was said could not be compared with what was planned. "
                                        "Actual delivery is unverified."}
    semantic = embed is not None
    if semantic:
        texts = [p for s in sections for p in s["points"]] + [s["text"] for s in sections] + [g["text"] for g in segments]
        vectors = dict(zip(texts, embed(texts)))
    need_terms, need_sim = settings.delivery_point_term_coverage, settings.delivery_point_similarity

    results, matched_segments = [], set()
    for section in sections:
        points = []
        for point in section["points"]:
            wanted = stems(point)
            best, best_cover, best_sim, best_rank = None, 0.0, 0.0, 0.0
            for segment in segments:
                cover = len(wanted & segment["stems"]) / len(wanted)
                sim = _cosine(vectors[point], vectors[segment["text"]]) if semantic else 0.0
                rank = max(cover / need_terms, sim / need_sim) if semantic else cover   # how close this segment comes to a match
                if rank > best_rank:
                    best, best_cover, best_sim, best_rank = segment, cover, sim, rank
            addressed = best is not None and (best_cover >= need_terms or (semantic and best_sim >= need_sim))
            if addressed:
                matched_segments.add(best["index"])
            points.append({"point": point, "addressed": addressed, "term_coverage": round(best_cover, 2),
                           "similarity": round(best_sim, 2) if semantic else None,
                           "transcript": _ref(best["chunk"], segment=best["index"], excerpt=best["text"][:400]) if addressed else None})
        share = sum(p["addressed"] for p in points) / len(points)
        status = "covered" if share >= settings.delivery_covered_share else "partial" if share > 0 else "not_covered"
        results.append({"title": section["title"], "status": status, "points_addressed": sum(p["addressed"] for p in points),
                        "points_total": len(points), "points": points, "planned": _ref(section["chunk"], excerpt=section["text"][:400])})

    section_stems = [stems(s["text"]) for s in sections]
    unplanned, asides = [], []
    for position, segment in enumerate(segments):
        if segment["index"] in matched_segments or len(segment["stems"]) < settings.delivery_min_segment_terms:
            continue
        overlap = max(len(segment["stems"] & known) / len(segment["stems"]) for known in section_stems)
        sim = max(_cosine(vectors[segment["text"]], vectors[s["text"]]) for s in sections) if semantic else 0.0
        if overlap >= settings.delivery_unplanned_term_overlap or (semantic and sim >= settings.delivery_unplanned_similarity):
            continue                                    # same subject as a planned section, said differently
        entry = {"transcript": _ref(segment["chunk"], segment=segment["index"], excerpt=segment["text"][:400]),
                 "term_overlap": round(overlap, 2), "similarity": round(sim, 2) if semantic else None}
        neighbours = {segments[i]["index"] for i in (position - 1, position + 1) if 0 <= i < len(segments)
                      and segments[i]["chunk"] is segment["chunk"]}
        if _EXAMPLE.search(segment["text"]) and neighbours & matched_segments:
            asides.append(entry)                        # an example or aside beside planned content: listed, not flagged
        else:
            unplanned.append(entry)

    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("covered", "partial", "not_covered")}
    return {"ran": True, "method": "semantic and shared content words" if semantic else "shared content words (lexical test backend)",
            "sections": results, "unplanned": unplanned, "examples_or_asides": asides, "counts": counts,
            "transcript_segments": len(segments),
            "delivered_share": round((counts["covered"] + 0.5 * counts["partial"]) / len(results), 4),
            "thresholds": {"point_term_coverage": need_terms, "point_similarity": need_sim if semantic else None,
                           "covered_share": settings.delivery_covered_share},
            "notice": "Shows whether planned content can be found in the transcript. It is not a judgement of teaching quality, "
                      "and an incomplete transcript can explain a missing match."}
