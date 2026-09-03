"""
LECTIO — Base Agent
All specialised agents inherit from this class.
Provides: LLM access, RAG retrieval, structured JSON parsing, error handling.
"""

import asyncio
import concurrent.futures
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from agents.graph.state import LectioWorkflowState, WorkflowError

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Abstract base for all LECTIO agents.

    Subclasses implement `run(state) → LectioWorkflowState`.
    """

    name: str = "base_agent"

    def __init__(self):
        self._llm = None
        self._rag = None

    # ── Sync/Async Bridge ───────────────────────────────────────────────────────
    # LangGraph nodes run synchronously, but our DB/RAG calls are async. We're
    # always invoked from inside FastAPI's already-running event loop, so plain
    # asyncio.run(...) fails with "cannot be called from a running event loop".
    # This runs the coroutine on its own dedicated thread/loop instead, which
    # works whether or not a loop is already running on the calling thread.
    @staticmethod
    def _run_async(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop running on this thread — safe to use asyncio.run() directly.
            return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    # ── LLM ───────────────────────────────────────────────────────────────────

    def _get_llm(self):
        if self._llm is None:
            from langchain_groq import ChatGroq
            from config import settings
            self._llm = ChatGroq(
                model=settings.groq_model,
                groq_api_key=settings.groq_api_key,
                temperature=0.1,      # Low temperature for factual analysis
                max_tokens=4000,
            )
        return self._llm

    # ── RAG ───────────────────────────────────────────────────────────────────

    def _get_rag(self):
        if self._rag is None:
            from rag.rag_service import RAGService
            self._rag = RAGService.get_instance()
        return self._rag

    def _retrieve(self, query: str, course_id: str, top_k: int = 8, where: Optional[dict] = None):
        """Retrieve grounded context chunks."""
        return self._get_rag().retrieve(
            query=query,
            course_id=course_id,
            top_k=top_k,
            where=where,
            rerank=True,
        )

    # ── LLM Utilities ─────────────────────────────────────────────────────────

    def _invoke(self, system: str, human: str) -> tuple[str, int]:
        """
        Call the LLM and return (content, tokens_used).
        Handles token tracking for cost monitoring.
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = self._get_llm()
        response = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=human),
        ])
        tokens = response.response_metadata.get("token_usage", {}).get("total_tokens", 0)
        return response.content, tokens

    def _parse_json(self, text: str) -> Any:
        """
        Extract and parse JSON from LLM output.
        Handles markdown code fences and stray text around JSON.
        """
        # Strip markdown fences
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```", "", text)
        text = text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find first JSON object or array
        for pattern in [r"\{.*\}", r"\[.*\]"]:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"Could not extract valid JSON from LLM output: {text[:200]}")

    # ── State Helpers ─────────────────────────────────────────────────────────

    def _log_error(self, state: LectioWorkflowState, message: str) -> LectioWorkflowState:
        err = WorkflowError(
            agent=self.name,
            message=message,
            ts=datetime.now(timezone.utc).isoformat(),
        )
        errors = list(state.get("error_log", []))
        errors.append(err)
        return {**state, "error_log": errors}

    def _add_tokens(self, state: LectioWorkflowState, n: int) -> dict:
        return {"total_tokens": state.get("total_tokens", 0) + n}

    def _gap_id(self) -> str:
        return str(uuid.uuid4())

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Abstract ──────────────────────────────────────────────────────────────

    def run(self, state: LectioWorkflowState) -> LectioWorkflowState:
        raise NotImplementedError(f"{self.name}.run() must be implemented")