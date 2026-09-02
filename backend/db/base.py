"""
LECTIO — SQLAlchemy async engine & declarative base.
All ORM models import Base from here.
"""

from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from config import settings


# ── Async Engine ─────────────────────────────────────────────────────────────
# NullPool: never cache/reuse a raw asyncpg connection across calls. Required
# because the AI agent workflow bridges sync LangGraph nodes to async DB
# calls by running them on a separate thread/event loop (see
# agents/base_agent.py::_run_async) — asyncpg connections are permanently
# bound to the event loop that opened them, so a pooled connection created
# under one loop cannot be reused under another (raises "the handler is
# closed"). NullPool sidesteps this entirely: every checkout opens a fresh
# connection and closes it right after, so it's always safe regardless of
# which thread/loop is asking.
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=NullPool,
)


# ── Declarative Base ──────────────────────────────────────────────────────────
class Base(AsyncAttrs, DeclarativeBase):
    """
    All ORM models inherit from this class.
    Provides async attribute-loading support (AsyncAttrs); each model
    defines its own created_at/updated_at columns individually.
    """
    pass