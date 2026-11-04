"""Projected alignment after the lecturer adopts approved drafts, without re-running the audit.

Each open gap that a draft can address is re-checked against the lecturer's approved (or edited
and approved) draft with the same similarity measure the audit uses. A gap counts as addressed only
if that check passes; nothing is assumed. The dimension score then moves towards 100% in proportion
to the severity-weighted share of gaps addressed, so one finding never explains the whole shortfall
(shares are over at least three warning-weights) and a projection never exceeds 95%. Projected numbers are labelled as such: only a
full audit, after the real course files change, produces a verified score.
"""
import asyncio
import math
import re
from sqlalchemy import select
from config import settings
from db.models.generated_content import GeneratedContentRecord
from db.models.report import AlignmentGapRecord, AlignmentReport
from knowledge.bloom_classifier import classify_text, level_to_int
from services.review import latest_text

WEIGHT = {'critical': 2.0, 'warning': 1.0, 'info': 0.5}
ASSESSMENT_DRAFTS = ('quiz', 'exercise', 'assessment_suggestion', 'assessment')
MIN_TOTAL_WEIGHT = 3.0   # a score reflects many evidence items: one finding never explains the whole shortfall
MAX_PROJECTED = 0.95    # only a full audit can show near-perfect alignment
STATUS_THRESHOLDS = {'metadata_assessment': (0.80, 0.60)}   # same cut-offs as the audit agents
_TOPIC = re.compile(r"Topic '(.+?)' has")
_CLO = re.compile(r"CLO: '(.+?)'", re.S)
_LEVELS = re.compile(r"targets '(\w+)' level but content only reaches '(\w+)'")


_vec_cache: dict = {}


def _neural() -> bool:
    return settings.runtime_mode == 'live' and settings.retrieval_backend == 'neural'


def _vectors(texts: list[str]) -> list[list[float]]:
    """Embed each distinct text once (one batch for the misses); small bounded memo across requests."""
    missing = list(dict.fromkeys(t for t in texts if t not in _vec_cache))
    if missing:
        from rag.embedding.bge_embedder import BGEEmbedder
        if len(_vec_cache) + len(missing) > 1000:
            _vec_cache.clear()
        # first 1200 characters carry the question/objective; keeps long drafts cheap on CPU
        _vec_cache.update(zip(missing, BGEEmbedder.get_instance().embed_texts([t[:1200] for t in missing])))
    return [_vec_cache[t] for t in texts]


LIVE_TYPES = ('live_missing_objective', 'live_missing_assessment')
CHECKED_TYPES = ('topic_not_assessed', 'clo_not_assessed') + LIVE_TYPES


def target_of(gap) -> str:
    """The topic / objective text a gap is about."""
    if gap.gap_type in LIVE_TYPES:
        return (gap.description or '').split(' Rationale:')[0]
    if gap.gap_type == 'topic_not_assessed':
        m = _TOPIC.search(gap.description or '')
    elif gap.gap_type == 'clo_not_assessed':
        m = _CLO.search(gap.description or '')
    else:
        m = None
    return m.group(1) if m else (gap.description or '')


def similarity(a: str, b: str) -> tuple[float, float]:
    """(cosine, threshold). Neural live mode uses the embedding model (audit threshold 0.55);
    test/lexical mode uses hash vectors, whose cosines are lower, so a lower bar applies."""
    if _neural():
        va, vb = _vectors([a, b])
        return sum(x * y for x, y in zip(va, vb)), 0.55
    from rag.local_service import vector
    va, vb = vector(a), vector(b)
    return sum(x * y for x, y in zip(va, vb)), 0.3


def check_gap(gap, drafts: list[dict], used: set | None = None):
    """Return (draft, detail) if an approved draft addresses this gap, else (None, reason)."""
    if gap.gap_type in CHECKED_TYPES:
        target = target_of(gap)
        best = None
        wanted = ('clo',) if gap.gap_type == 'live_missing_objective' else ASSESSMENT_DRAFTS
        for d in (x for x in drafts if x['type'] in wanted):
            sim, bar = similarity(target, d['text'])
            if sim >= bar and (best is None or sim > best[1]):
                best = (d, sim)
        if best:
            return best[0], f'draft matches "{target[:60]}" (similarity {best[1]:.2f}, needs {bar:.2f})'
        return None, ('no approved objective draft covers this yet' if gap.gap_type == 'live_missing_objective'
                      else 'no approved assessment draft covers this yet')
    if gap.gap_type == 'bloom_level_mismatch':
        m = _LEVELS.search(gap.description or '')
        if not m:
            return None, 'cognitive levels could not be read from this finding'
        asked, reached = m.groups()
        for d in (x for x in drafts if x['id'] not in (used or set())):   # one draft closes at most one level gap
            level, _ = classify_text(d['text'])
            if level and level_to_int(level) < level_to_int(asked) and abs(level_to_int(level) - level_to_int(reached)) <= 1:
                return d, f'approved draft is at "{level}" level, within one step of the taught "{reached}" level'
        return None, 'no approved draft aligns the cognitive level with the taught content'
    if gap.gap_type == 'live_alignment_review':
        return None, 'model-review finding: adopt its suggested correction, then re-audit to verify'
    return None, 'needs new teaching material or lecturer action; a generated draft cannot close it'


def projected_score(verified: float, resolved: float, total: float) -> float:
    share = resolved / max(total, MIN_TOTAL_WEIGHT)
    return max(verified, min(MAX_PROJECTED, verified + (1.0 - verified) * share))


def status_for(report_type: str, score: float) -> str:
    ok, warn = STATUS_THRESHOLDS.get(report_type, (0.75, 0.55))
    return 'pass' if score >= ok else 'warning' if score >= warn else 'fail'


async def project_course(course_id, db) -> dict:
    reports = (await db.scalars(select(AlignmentReport).where(AlignmentReport.course_id == course_id)
                                .order_by(AlignmentReport.generated_at.desc()))).all()
    latest = {}
    for r in reports:
        latest.setdefault(r.report_type, r)
    rows = (await db.scalars(select(GeneratedContentRecord).where(
        GeneratedContentRecord.course_id == course_id, GeneratedContentRecord.approval_status == 'approved'))).all()
    drafts = [{'id': str(r.id), 'title': r.title, 'type': r.content_type, 'text': await latest_text(r, db)} for r in rows]
    dimensions = []
    if _neural() and drafts:   # one batch for every text we will compare
        texts = [d['text'] for d in drafts]
        for report in latest.values():
            texts += [target_of(g) for g in (await db.scalars(select(AlignmentGapRecord).where(
                AlignmentGapRecord.report_id == report.id, AlignmentGapRecord.gap_type.in_(CHECKED_TYPES)))).all()]
        await asyncio.to_thread(_vectors, texts)
    for report_type, report in sorted(latest.items()):
        verified = float(report.overall_score or 0)
        gaps = (await db.scalars(select(AlignmentGapRecord).where(AlignmentGapRecord.report_id == report.id))).all()
        entry = {'report_type': report_type, 'verified_score': verified, 'verified_status': report.status,
                 'run_id': str(report.run_id), 'gaps_total': len(gaps), 'addressed': [], 'open': []}
        if report.status in ('needs_review', 'failed'):
            entry.update(projected_score=None, projected_status=report.status, delta=0.0,
                         note='This check could not be scored, so no projection is made.')
            dimensions.append(entry); continue
        total = resolved = 0.0
        used: set = set()
        for gap in gaps:
            w = WEIGHT.get(gap.severity, 1.0); total += w
            draft, detail = await asyncio.to_thread(check_gap, gap, drafts, used) if drafts else (None, 'no approved drafts yet')
            if draft and gap.gap_type == 'bloom_level_mismatch':
                used.add(draft['id'])
            item = {'gap_id': str(gap.id), 'gap_type': gap.gap_type, 'severity': gap.severity, 'description': gap.description[:220]}
            if draft:
                resolved += w
                entry['addressed'].append({**item, 'draft_id': draft['id'], 'draft_title': draft['title'], 'check': detail})
            else:
                entry['open'].append({**item, 'reason': detail})
        projected = projected_score(verified, resolved, total)
        entry.update(projected_score=round(projected, 4), projected_status=status_for(report_type, projected),
                     delta=round(projected - verified, 4))
        dimensions.append(entry)
    return {'dimensions': dimensions, 'approved_drafts': len(drafts), 'basis': 'latest audit per check',
            'method': 'Each addressed gap is re-checked against an approved draft with the audit similarity measure; the score moves '
                      'towards 100% by the severity-weighted share of gaps addressed. Projected, not verified: adopt the drafts in the '
                      'real course files and re-run the audit to verify.'}
