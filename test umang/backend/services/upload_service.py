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
    "md": "text/markdown",
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
        mime_type: str | None = None,
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

        if mime_type and mime_type not in (ALLOWED_EXTENSIONS[ext], "application/octet-stream"):
            if not (ext == "md" and mime_type == "text/plain"):
                raise UploadError("MIME type does not match the file extension.")
        if ext in ("docx", "pptx"):
            self._validate_office(file_bytes, ext)
        elif ext in ("txt", "md", "vtt"):
            try:
                decoded = file_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise UploadError("Text documents must be UTF-8 encoded.")
            if "\x00" in decoded or not decoded.strip():
                raise UploadError("Empty or binary text document.")
        checksum    = compute_checksum(file_bytes)
        safe_name   = self._safe_filename(original_filename, ext)
        dest_path   = self._destination(course_id, safe_name)

        await self._write(dest_path, file_bytes)
        logger.info(f"Saved artifact {safe_name} ({len(file_bytes):,} bytes) → {dest_path}")

        return safe_name, ext, str(dest_path), checksum, len(file_bytes)

    def delete(self, storage_path: str) -> None:
        """Delete a file from disk. Does not raise if not found."""
        p = Path(storage_path).resolve()
        if not p.is_relative_to(self.storage_root.resolve()):
            raise UploadError("Storage path is outside the upload directory.")
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
        course_id = str(uuid.UUID(course_id))
        folder = self.storage_root / course_id
        root=self.storage_root.resolve()
        folder=folder.resolve()
        if not folder.is_relative_to(root):raise UploadError("Unsafe upload directory.")
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
        return folder / filename

    async def _write(self, path: Path, data: bytes) -> None:
        import os,tempfile
        descriptor, temporary = tempfile.mkstemp(prefix=".upload-",dir=path.parent)
        os.close(descriptor)
        try:
            async with aiofiles.open(temporary,"wb") as f:
                await f.write(data)
            os.replace(temporary,path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _validate_office(self, data: bytes, ext: str):
        import io, zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 5000 or sum(e.file_size for e in entries) > 100 * 1024 * 1024:
                    raise UploadError("Office archive exceeds extraction limits.")
                required = "word/document.xml" if ext == "docx" else "ppt/presentation.xml"
                if required not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                    raise UploadError("Invalid Office document structure.")
                for entry in entries:
                    name = entry.filename.lower()
                    if entry.flag_bits & 1 or "vbaproject" in name or "/embeddings/" in name:
                        raise UploadError("Encrypted or active embedded content is not supported.")
                    if entry.file_size > 20 * 1024 * 1024 or entry.file_size / max(entry.compress_size, 1) > 250:
                        raise UploadError("Office archive expansion limit exceeded.")
                    if ".." in Path(name).parts or name.startswith("/"):
                        raise UploadError("Unsafe Office archive path.")
                if archive.testzip():
                    raise UploadError("Corrupt Office archive.")
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise UploadError("Invalid Office archive.") from exc
