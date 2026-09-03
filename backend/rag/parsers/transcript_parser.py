"""
LECTIO — Plain Text & VTT Transcript Parsers

PlainTextParser: handles .txt files (syllabi exported as text, reading lists, etc.)
TranscriptParser: handles .vtt (WebVTT) lecture transcripts from Zoom/Teams/YouTube.

VTT Design:
  Transcripts are chunked by 60-second windows, not cue-by-cue.
  This produces semantically coherent segments (a sentence rarely spans >60s)
  and avoids 500 micro-chunks per lecture hour.
"""

import re
import logging
from pathlib import Path
from typing import List

from rag.parsers.base_parser import BaseParser, ParsedBlock, ParsedDocument

logger = logging.getLogger(__name__)


# ── Plain Text ─────────────────────────────────────────────────────────────────

class PlainTextParser(BaseParser):

    def parse(self, file_path: str, artifact_type: str = "other") -> ParsedDocument:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        text = self._safe_text(text)

        # Split on double newlines (paragraph boundaries)
        raw_paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        blocks: List[ParsedBlock] = []

        for i, para in enumerate(raw_paras):
            # Heuristic: short lines in all-caps or ending with ":" are headings
            first_line = para.split("\n")[0]
            is_heading = (
                len(first_line) < 80
                and (first_line.isupper() or first_line.rstrip().endswith(":"))
            )
            blocks.append(ParsedBlock(
                text=para,
                block_type="heading" if is_heading else "paragraph",
                heading_level=2 if is_heading else None,
                metadata={"para_index": i},
            ))

        return ParsedDocument(
            source_path=str(path),
            file_type="txt",
            artifact_type=artifact_type,
            blocks=blocks,
            title=path.stem,
            word_count=self._count_words(text),
        )


# ── VTT Transcript ─────────────────────────────────────────────────────────────

_VTT_TIMESTAMP = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\.\d+ --> (\d{2}):(\d{2}):(\d{2})\.\d+"
)
_VTT_TAG       = re.compile(r"<[^>]+>")          # strip VTT inline tags


def _vtt_to_seconds(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


class TranscriptParser(BaseParser):

    WINDOW_SECONDS = 60   # aggregate cues into 60-second blocks

    def parse(self, file_path: str, artifact_type: str = "transcript") -> ParsedDocument:
        path = Path(file_path)
        raw  = path.read_text(encoding="utf-8", errors="replace")

        cues    = self._parse_cues(raw)
        blocks  = self._aggregate_windows(cues)

        all_text   = " ".join(b.text for b in blocks)
        word_count = self._count_words(all_text)

        return ParsedDocument(
            source_path=str(path),
            file_type="vtt",
            artifact_type=artifact_type,
            blocks=blocks,
            title=path.stem,
            word_count=word_count,
        )

    def _parse_cues(self, raw: str) -> List[dict]:
        """Extract (start_sec, text) pairs from VTT content."""
        cues   = []
        lines  = raw.splitlines()
        i      = 0

        while i < len(lines):
            line = lines[i].strip()
            m    = _VTT_TIMESTAMP.match(line)
            if m:
                start_sec = _vtt_to_seconds(m.group(1), m.group(2), m.group(3))
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(_VTT_TAG.sub("", lines[i]).strip())
                    i += 1
                cue_text = " ".join(text_lines).strip()
                if cue_text:
                    cues.append({"start": start_sec, "text": cue_text})
            else:
                i += 1

        return cues

    def _aggregate_windows(self, cues: List[dict]) -> List[ParsedBlock]:
        """Aggregate cues into WINDOW_SECONDS buckets."""
        if not cues:
            return []

        blocks:   List[ParsedBlock] = []
        window_start = cues[0]["start"]
        bucket:  List[str] = []

        for cue in cues:
            if cue["start"] - window_start >= self.WINDOW_SECONDS:
                if bucket:
                    mins = window_start // 60
                    blocks.append(ParsedBlock(
                        text=self._safe_text(" ".join(bucket)),
                        block_type="paragraph",
                        metadata={
                            "start_sec": window_start,
                            "timestamp": f"{mins:02d}:{window_start % 60:02d}",
                        },
                    ))
                bucket       = [cue["text"]]
                window_start = cue["start"]
            else:
                bucket.append(cue["text"])

        # Final window
        if bucket:
            mins = window_start // 60
            blocks.append(ParsedBlock(
                text=self._safe_text(" ".join(bucket)),
                block_type="paragraph",
                metadata={
                    "start_sec": window_start,
                    "timestamp": f"{mins:02d}:{window_start % 60:02d}",
                },
            ))

        return blocks
