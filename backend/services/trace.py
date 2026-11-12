"""Append-only, hash-chained trace of what the system did and why.

Every audit creation, agent start/finish/failure, agent-to-agent message, tool call, model call,
quality check, retry and lecturer decision is one `trace_events` row.

Integrity, stated exactly:
  * The application only ever INSERTs. The ORM refuses UPDATE and DELETE on TraceEvent, and database
    triggers (SQLite and PostgreSQL) abort UPDATE and DELETE on the table, so normal application
    operations and ordinary SQL cannot alter history.
  * Each event stores `hash = sha256(prev_hash + canonical event)`, one chain per run (or per course for
    events outside a run). `verify_chain` recomputes it, so an edit, a removal or a reordering made by
    someone who bypassed the triggers is detected.
  * When a run ends (and on request) the chain head is written to an anchor file outside the database.
    `verify_chain` compares the database with every anchor, so events cut off the end, or a whole chain
    rewritten consistently by a database owner, are detected up to the last anchor.
  * It is NOT tamper-proof against someone who can rewrite both the database and the anchor file; copy the
    anchors to another system for that.

Privacy: prompts and documents are never stored here, only fingerprints, sizes, ids and outcomes.
"""
import asyncio
import concurrent.futures
import contextvars
import hashlib
import json
import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from config import settings
from db.models.governance import TraceEvent

logger = logging.getLogger(__name__)
GENESIS = "0" * 64
_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("lectio_trace", default={})
_lock = threading.Lock()


class AppendOnlyViolation(RuntimeError):
    pass


@event.listens_for(TraceEvent, "before_update")
def _no_update(mapper, connection, target):
    raise AppendOnlyViolation("trace_events is append-only: an event cannot be changed.")


@event.listens_for(TraceEvent, "before_delete")
def _no_delete(mapper, connection, target):
    raise AppendOnlyViolation("trace_events is append-only: an event cannot be deleted.")


def install_guards(sync_conn) -> None:
    """Database-level triggers that abort UPDATE and DELETE on trace_events."""
    if sync_conn.dialect.name == "sqlite":
        for op in ("UPDATE", "DELETE"):
            sync_conn.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS trace_events_no_{op.lower()} BEFORE {op} ON trace_events "
                f"BEGIN SELECT RAISE(ABORT, 'trace_events is append-only'); END"))
    elif sync_conn.dialect.name == "postgresql":
        sync_conn.execute(text(
            "CREATE OR REPLACE FUNCTION trace_events_append_only() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'trace_events is append-only'; END; $$ LANGUAGE plpgsql"))
        sync_conn.execute(text("DROP TRIGGER IF EXISTS trace_events_guard ON trace_events"))
        sync_conn.execute(text(
            "CREATE TRIGGER trace_events_guard BEFORE UPDATE OR DELETE ON trace_events "
            "FOR EACH ROW EXECUTE FUNCTION trace_events_append_only()"))
        sync_conn.execute(text("DROP TRIGGER IF EXISTS trace_events_no_truncate ON trace_events"))
        sync_conn.execute(text(
            "CREATE TRIGGER trace_events_no_truncate BEFORE TRUNCATE ON trace_events "
            "FOR EACH STATEMENT EXECUTE FUNCTION trace_events_append_only()"))


# ── context: who is acting, for which run and task ───────────────────────────

def current() -> dict:
    return dict(_ctx.get())


@contextmanager
def context(**values):
    """Bind run_id / course_id / agent / task_id / dimension / intent / constraint_ids for nested emits and model calls."""
    token = _ctx.set({**_ctx.get(), **{k: v for k, v in values.items() if v is not None}})
    try:
        yield
    finally:
        _ctx.reset(token)


def bind(fn):
    """Carry the current trace context into a worker thread (thread pools do not inherit it)."""
    ctx = contextvars.copy_context()
    return lambda *a, **k: ctx.run(fn, *a, **k)


def fingerprint(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean(payload: dict) -> dict:
    """Drop anything that looks like a credential; keep the payload JSON-safe."""
    out = {k: v for k, v in (payload or {}).items()
           if not any(marker in str(k).lower() for marker in ("password", "secret", "authorization", "api_key", "apikey"))}
    return json.loads(json.dumps(out, default=str, ensure_ascii=False))


def _event_hash(prev_hash: str, body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _body(row) -> dict:
    return {"chain_key": row.chain_key, "seq": row.seq, "ts": row.ts, "run_id": row.run_id, "course_id": row.course_id,
            "event_type": row.event_type, "agent": row.agent, "task_id": row.task_id, "parent_id": row.parent_id,
            "subject_type": row.subject_type, "subject_id": row.subject_id, "payload": row.payload}


async def _insert(db, fields: dict) -> TraceEvent:
    last = (await db.execute(select(TraceEvent.seq, TraceEvent.hash).where(TraceEvent.chain_key == fields["chain_key"])
                             .order_by(TraceEvent.seq.desc()).limit(1))).first()
    seq, prev = (last[0] + 1, last[1]) if last else (1, GENESIS)
    row = TraceEvent(id=uuid.uuid4(), seq=seq, prev_hash=prev, hash="", **fields)
    row.hash = _event_hash(prev, _body(row))
    db.add(row)
    await db.flush()
    return row


async def aemit(event_type: str, payload: Optional[dict] = None, *, db=None, subject: Optional[tuple] = None,
                parent_id: Optional[str] = None, **override) -> Optional[str]:
    """Append one event. Pass `db` when already inside a request transaction (same connection, no lock wait)."""
    if not settings.trace_enabled:
        return None
    ctx = {**_ctx.get(), **{k: v for k, v in override.items() if v is not None}}
    run_id, course_id = ctx.get("run_id"), ctx.get("course_id")
    chain_key = str(run_id) if run_id else f"course:{course_id}" if course_id else "system"
    extra = {k: ctx[k] for k in ("dimension", "intent", "constraint_ids") if ctx.get(k) is not None}
    fields = dict(chain_key=chain_key, ts=datetime.now(timezone.utc).isoformat(), run_id=str(run_id) if run_id else None,
                  course_id=str(course_id) if course_id else None, event_type=event_type, agent=ctx.get("agent"),
                  task_id=ctx.get("task_id"), parent_id=parent_id or ctx.get("parent_id"),
                  subject_type=subject[0] if subject else None, subject_id=str(subject[1]) if subject else None,
                  payload=_clean({**extra, **(payload or {})}))
    try:
        if db is not None:
            for _ in range(5):
                try:
                    async with db.begin_nested():
                        return str((await _insert(db, fields)).id)
                except IntegrityError:
                    continue
            raise RuntimeError("could not append to the trace chain")
        from db.session import AsyncSessionLocal
        for _ in range(8):
            try:
                async with AsyncSessionLocal() as session:
                    row = await _insert(session, fields)
                    await session.commit()
                    return str(row.id)
            except IntegrityError:      # another writer took this seq: read the new tail and try again
                await asyncio.sleep(0.01)
        raise RuntimeError("could not append to the trace chain")
    except Exception as exc:            # tracing must never break the work it describes, but must not fail silently
        logger.error("trace event %s was not recorded: %s", event_type, exc)
        return None


def emit(event_type: str, payload: Optional[dict] = None, **kw) -> Optional[str]:
    """Synchronous append for agent code and worker threads."""
    if not settings.trace_enabled:
        return None
    coro_factory = bind(lambda: asyncio.run(aemit(event_type, payload, **kw)))
    with _lock:                         # one writer per process keeps a chain's order stable
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return coro_factory()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(coro_factory).result()


# ── anchors: chain heads recorded outside the database ───────────────────────
# The hash chain alone cannot show that events were cut off the end, or that someone with full database
# rights rewrote a whole chain consistently. An anchor is the (seq, hash) of a chain's last event written
# to an append-only file beside the uploads. `verify_chain` checks every anchor against the database.
# Limit, stated exactly: someone who can rewrite both the database and this file is still not detected;
# copy the file (or the head hash shown by the verify endpoints) to another system to close that.

_anchor_lock = threading.Lock()


def anchor_path() -> Path:
    return Path(settings.trace_anchor_path or Path(settings.artifact_storage_path) / "trace_anchors.jsonl")


def anchors(chain_key: str) -> list:
    path = anchor_path()
    if not path.exists():
        return []
    found = []
    with _anchor_lock, path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if chain_key not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("chain_key") == chain_key:
                found.append(entry)
    return found


async def anchor(db, chain_key: str) -> Optional[dict]:
    """Record the committed head of a chain outside the database. Call only after the events are committed."""
    if not settings.trace_enabled:
        return None
    last = (await db.execute(select(TraceEvent.seq, TraceEvent.hash).where(TraceEvent.chain_key == chain_key)
                             .order_by(TraceEvent.seq.desc()).limit(1))).first()
    if not last:
        return None
    entry = {"chain_key": chain_key, "seq": last[0], "hash": last[1], "ts": datetime.now(timezone.utc).isoformat()}
    known = anchors(chain_key)
    if known and known[-1]["seq"] == entry["seq"] and known[-1]["hash"] == entry["hash"]:
        return known[-1]
    try:
        path = anchor_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _anchor_lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as exc:
        logger.error("trace anchor for %s was not written: %s", chain_key, exc)
        return None
    return entry


async def verify_chain(db, chain_key: str) -> dict:
    """Recompute a chain and compare it with its anchors.

    Reports the first event whose hash, link or sequence does not hold, or the first anchor the database
    no longer matches (events removed from the end, or the chain rewritten)."""
    rows = (await db.scalars(select(TraceEvent).where(TraceEvent.chain_key == chain_key).order_by(TraceEvent.seq))).all()
    prev, expected = GENESIS, 1
    for row in rows:
        if row.seq != expected:
            return {"chain_key": chain_key, "valid": False, "events": len(rows), "broken_at_seq": row.seq, "reason": "missing or reordered event"}
        if row.prev_hash != prev or row.hash != _event_hash(prev, _body(row)):
            return {"chain_key": chain_key, "valid": False, "events": len(rows), "broken_at_seq": row.seq, "reason": "event content or link was altered"}
        prev, expected = row.hash, expected + 1
    known = anchors(chain_key)
    by_seq = {row.seq: row.hash for row in rows}
    for entry in known:
        if by_seq.get(entry["seq"]) != entry["hash"]:
            reason = ("events were removed from the end of the log" if entry["seq"] not in by_seq
                      else "the log no longer matches the head recorded outside the database (rewritten)")
            return {"chain_key": chain_key, "valid": False, "events": len(rows), "broken_at_seq": entry["seq"], "reason": reason,
                    "anchored_seq": entry["seq"]}
    return {"chain_key": chain_key, "valid": True, "events": len(rows), "head": prev,
            "anchored_seq": known[-1]["seq"] if known else None}


async def count(db, **filters) -> int:
    q = select(func.count()).select_from(TraceEvent)
    for k, v in filters.items():
        q = q.where(getattr(TraceEvent, k) == v)
    return await db.scalar(q)


def to_dict(row: TraceEvent) -> dict:
    return {"id": str(row.id), "seq": row.seq, "ts": row.ts, "event_type": row.event_type, "agent": row.agent,
            "task_id": row.task_id, "parent_id": row.parent_id, "subject_type": row.subject_type,
            "subject_id": row.subject_id, "payload": row.payload, "hash": row.hash[:12]}
