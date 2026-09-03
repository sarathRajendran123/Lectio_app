"""
LECTIO — Upload Service
Handles file validation, sanitisation, disk storage, and checksum.
Keeps all file-system logic out of route handlers.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Tuple

import aiofiles

from config import settings
from db.repositories.artifact_repository import compute_checksum

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt":  "text/plain",
    "vtt":  "text/vtt",
}

# Magic-byte signatures for server-side type verification
MAGIC_BYTES: dict[str, bytes] = {
    "pdf":  b"%PDF",
    "docx": b"PK\x03\x04",   # ZIP-based (Office Open XML)
    "pptx": b"PK\x03\x04",
}


class UploadError(Exception):
    """Raised when a file fails validation."""


class UploadService:
    def __init__(self):
        self.storage_root = Path(settings.artifact_storage_path)
        self.max_bytes    = settings.max_upload_size_bytes

    # ── Public API ────────────────────────────────────────────────────────────

    async def save(
        self,
        file_bytes: bytes,
        original_filename: str,
        course_id: str,
    ) -> Tuple[str, str, str, str, int]:
        """
        Validate, sanitise, and persist a file.

        Returns:
            (safe_filename, extension, storage_path, checksum, size_bytes)

        Raises:
            UploadError on any validation failure.
        """
        self._validate_size(file_bytes)
        ext = self._extract_extension(original_filename)
        self._validate_extension(ext)
        self._validate_magic_bytes(file_bytes, ext)

        checksum    = compute_checksum(file_bytes)
        safe_name   = self._safe_filename(original_filename, ext)
        dest_path   = self._destination(course_id, safe_name)

        await self._write(dest_path, file_bytes)
        logger.info(f"Saved artifact {safe_name} ({len(file_bytes):,} bytes) → {dest_path}")

        return safe_name, ext, str(dest_path), checksum, len(file_bytes)

    def delete(self, storage_path: str) -> None:
        """Delete a file from disk. Does not raise if not found."""
        p = Path(storage_path)
        if p.exists():
            p.unlink()
            logger.info(f"Deleted artifact file: {storage_path}")

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_size(self, data: bytes) -> None:
        if len(data) > self.max_bytes:
            raise UploadError(
                f"File exceeds maximum size of {settings.max_upload_size_mb} MB."
            )
        if len(data) == 0:
            raise UploadError("File is empty.")

    def _extract_extension(self, filename: str) -> str:
        ext = Path(filename).suffix.lstrip(".").lower()
        if not ext:
            raise UploadError("File has no extension.")
        return ext

    def _validate_extension(self, ext: str) -> None:
        if ext not in ALLOWED_EXTENSIONS:
            raise UploadError(
                f"File type '.{ext}' is not allowed. "
                f"Accepted: {', '.join(ALLOWED_EXTENSIONS)}"
            )

    def _validate_magic_bytes(self, data: bytes, ext: str) -> None:
        """Server-side MIME check — prevents disguised executables."""
        expected = MAGIC_BYTES.get(ext)
        if expected and not data.startswith(expected):
            raise UploadError(
                f"File content does not match declared type '.{ext}'. "
                "Upload was rejected for security reasons."
            )

    # ── Storage ───────────────────────────────────────────────────────────────

    def _safe_filename(self, original: str, ext: str) -> str:
        """
        Produce a safe filename: strip path traversal, whitespace, special chars.
        Format: <uuid>_<sanitised_stem>.<ext>
        """
        stem = Path(original).stem
        stem = re.sub(r"[^\w\-]", "_", stem)   # keep word chars, hyphens
        stem = stem[:80]                          # max stem length
        return f"{uuid.uuid4().hex}_{stem}.{ext}"

    def _destination(self, course_id: str, filename: str) -> Path:
        folder = self.storage_root / course_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder / filename

    async def _write(self, path: Path, data: bytes) -> None:
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
