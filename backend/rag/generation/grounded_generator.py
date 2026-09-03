"""
LECTIO — Grounded Generator
Takes retrieved, reranked chunks + a task prompt and calls the LLM.
Every generated item MUST include [SOURCE_N] citation markers,
which are then resolved to human-readable citations by CitationBuilder.

Why citations are non-negotiable:
  Without grounding, a generated CLO like "Students will be able to implement
  a red-black tree" might have no basis in the actual course content.
  Citations let the lecturer verify the source in one click.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from rag.chunking.chunk_models import RetrievedChunk

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 12_000   # ~3000 tokens — leaves room for system + response


@dataclass
class GeneratedItem:
    """Output from the generator, with resolved citations."""
    content:      str              # Final text (citation markers replaced)
    raw_content:  str              # As returned by LLM (marker form)
    citations:    List[dict]       # [{"marker": "[SOURCE_1]", "citation": "..."}]
    model:        str
    tokens_used:  int
    context_used: int              # Number of context chunks consumed


class GroundedGenerator:
    """
    Calls Groq (Llama 3.3 70B) with retrieved context.
    System prompt enforces citation discipline.
    """

    SYSTEM_PROMPT = """You are an expert educational content designer working with a university lecturer.

Your task is to generate high-quality educational content that is STRICTLY grounded in the provided course materials.

RULES:
1. Every factual claim or generated item MUST include a citation marker: [SOURCE_1], [SOURCE_2], etc.
2. Only use information present in the provided CONTEXT sections.
3. Do NOT invent topics, objectives, or content not present in the context.
4. If the context is insufficient to generate a high-quality item, say so explicitly.
5. Match the academic level and terminology of the source materials.
6. Format your response cleanly — no preamble, no meta-commentary."""

    def __init__(self, model: Optional[str] = None):
        from config import settings
        self.model = model or settings.groq_model
        self._llm  = None

    def _get_llm(self):
        if self._llm is None:
            from langchain_groq import ChatGroq
            from config import settings
            self._llm = ChatGroq(
                model=self.model,
                groq_api_key=settings.groq_api_key,
                temperature=0.3,      # Low temperature for factual grounding
                max_tokens=2000,
            )
        return self._llm

    def generate(
        self,
        task_prompt: str,
        context_chunks: List[RetrievedChunk],
        extra_instructions: Optional[str] = None,
    ) -> GeneratedItem:
        """
        Generate content grounded in context_chunks.

        Args:
            task_prompt:        What to generate (e.g. "Generate 3 CLOs for Module 2")
            context_chunks:     Reranked retrieved chunks to ground the generation
            extra_instructions: Optional reviewer preference additions

        Returns:
            GeneratedItem with content, citations, and metadata
        """
        context_text  = self._build_context(context_chunks)
        full_prompt   = self._build_prompt(task_prompt, context_text, extra_instructions)

        llm          = self._get_llm()
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=full_prompt),
        ]

        response    = llm.invoke(messages)
        raw_content = response.content
        tokens_used = response.response_metadata.get("token_usage", {}).get("total_tokens", 0)

        # Resolve [SOURCE_N] markers to human-readable citations
        resolved, citations = CitationBuilder.resolve(raw_content, context_chunks)

        return GeneratedItem(
            content=resolved,
            raw_content=raw_content,
            citations=citations,
            model=self.model,
            tokens_used=tokens_used,
            context_used=len(context_chunks),
        )

    def _build_context(self, chunks: List[RetrievedChunk]) -> str:
        """Format chunks as numbered context sections."""
        parts   = []
        total   = 0
        for i, chunk in enumerate(chunks, start=1):
            citation = chunk.to_citation()
            entry    = f"[SOURCE_{i}] {citation}\n{chunk.text}"
            entry_len = len(entry)
            if total + entry_len > MAX_CONTEXT_CHARS:
                logger.debug(f"Context budget reached at chunk {i}/{len(chunks)}")
                break
            parts.append(entry)
            total += entry_len
        return "\n\n---\n\n".join(parts)

    def _build_prompt(
        self,
        task: str,
        context: str,
        extra: Optional[str],
    ) -> str:
        lines = [
            "=== COURSE MATERIAL CONTEXT ===",
            context,
            "",
            "=== TASK ===",
            task,
        ]
        if extra:
            lines += ["", "=== ADDITIONAL INSTRUCTIONS ===", extra]
        lines += [
            "",
            "Remember: cite every claim with [SOURCE_N] markers matching the context above.",
        ]
        return "\n".join(lines)


class CitationBuilder:
    """
    Resolves [SOURCE_N] markers in LLM output to human-readable citations.
    """

    _MARKER_RE = re.compile(r"\[SOURCE_(\d+)\]")

    @classmethod
    def resolve(
        cls,
        text: str,
        chunks: List[RetrievedChunk],
    ) -> tuple[str, List[dict]]:
        """
        Replace [SOURCE_N] with readable citations.

        Returns:
            (resolved_text, citations_list)
            citations_list: [{"marker": "[SOURCE_1]", "citation": "...", "chunk_id": "..."}]
        """
        citations: List[dict] = []
        seen: dict = {}

        def replacer(match):
            idx = int(match.group(1)) - 1   # 1-indexed → 0-indexed
            if idx < 0 or idx >= len(chunks):
                return match.group(0)       # keep original if out of range
            chunk    = chunks[idx]
            citation = chunk.to_citation()
            marker   = match.group(0)

            if marker not in seen:
                seen[marker] = citation
                citations.append({
                    "marker":   marker,
                    "citation": citation,
                    "chunk_id": chunk.chunk_id,
                    "artifact_type": chunk.artifact_type,
                    "page_number":   chunk.page_number,
                    "slide_number":  chunk.slide_number,
                    "week_number":   chunk.week_number,
                    "section_title": chunk.section_title,
                })

            return f"{marker}"   # keep marker in text; UI renders it as a link

        resolved = cls._MARKER_RE.sub(replacer, text)
        return resolved, citations
