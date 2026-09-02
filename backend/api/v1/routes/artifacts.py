"""
LECTIO — Artifacts Router
POST   /api/v1/courses/{course_id}/artifacts         — Upload file
GET    /api/v1/courses/{course_id}/artifacts         — List artifacts
GET    /api/v1/courses/{course_id}/artifacts/{id}    — Get single artifact
GET    /api/v1/courses/{course_id}/artifacts/{id}/status — Processing status
DELETE /api/v1/courses/{course_id}/artifacts/{id}    — Delete artifact
"""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.rbac import CurrentUser, get_current_user
from db.repositories.artifact_repository import ArtifactRepository
from db.repositories.course_repository import CourseRepository
from db.session import get_db
from schemas.artifact import (
    ArtifactListResponse, ArtifactResponse, ArtifactStatusResponse,
    VALID_ARTIFACT_TYPES,
)
from services.upload_service import UploadError, UploadService

router = APIRouter()
logger = logging.getLogger(__name__)


async def _assert_course_access(course_id: UUID, user: CurrentUser, db: AsyncSession) -> None:
    repo = CourseRepository(db)
    course = await repo.get_by_id(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    if not await repo.user_can_access(course_id, UUID(user.id), user.roles):
        raise HTTPException(status_code=403, detail="Access denied to this course.")


# ── POST /courses/{course_id}/artifacts ───────────────────────────────────────

@router.post(
    "/{course_id}/artifacts",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_artifact(
    course_id:     UUID,
    background_tasks: BackgroundTasks,
    file:          UploadFile = File(...),
    artifact_type: str        = Form(...),
    user:          CurrentUser  = Depends(get_current_user),
    db:            AsyncSession = Depends(get_db),
):
    """
    Upload a course artefact (PDF, DOCX, PPTX, TXT, VTT).
    The file is validated, checksummed, saved to disk, and registered in the DB.
    The RAG ingestion pipeline picks it up asynchronously (Phase 2).
    """
    await _assert_course_access(course_id, user, db)

    # Validate artifact_type form field
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"artifact_type must be one of: {', '.join(VALID_ARTIFACT_TYPES)}",
        )

    file_bytes = await file.read()
    svc        = UploadService()

    try:
        safe_name, ext, storage_path, checksum, size = await svc.save(
            file_bytes=file_bytes,
            original_filename=file.filename or "upload",
            course_id=str(course_id),
        )
    except UploadError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Duplicate detection
    repo       = ArtifactRepository(db)
    duplicate  = await repo.find_duplicate(course_id, checksum)
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=f"This file was already uploaded (artifact id: {duplicate.id}).",
        )

    artifact = await repo.create(
        course_id=course_id,
        uploaded_by=UUID(user.id),
        filename=safe_name,
        original_filename=file.filename or safe_name,
        file_type=ext,
        artifact_type=artifact_type,
        file_size_bytes=size,
        storage_path=storage_path,
        checksum=checksum,
    )

    _trigger_ingestion(
        background_tasks=background_tasks,
        artifact_id=artifact.id,
        course_id=course_id,
        storage_path=storage_path,
        file_type=ext,
        artifact_type=artifact_type,
    )

    logger.info(
        f"Artifact uploaded: {artifact.id} | course={course_id} | "
        f"type={artifact_type} | size={size:,}B | user={user.email}"
    )
    

    chunk_count = await repo.count_chunks(artifact.id)
    return _to_response(artifact, chunk_count)


# ── GET /courses/{course_id}/artifacts ────────────────────────────────────────

@router.get("/{course_id}/artifacts", response_model=ArtifactListResponse)
async def list_artifacts(
    course_id: UUID,
    skip:  int = 0,
    limit: int = 50,
    user:  CurrentUser  = Depends(get_current_user),
    db:    AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo   = ArtifactRepository(db)
    total, artifacts = await repo.list_for_course(course_id, skip=skip, limit=limit)

    responses = []
    for a in artifacts:
        chunk_count = await repo.count_chunks(a.id)
        responses.append(_to_response(a, chunk_count))

    return ArtifactListResponse(total=total, artifacts=responses)


# ── GET /courses/{course_id}/artifacts/{artifact_id} ──────────────────────────

@router.get("/{course_id}/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    course_id:   UUID,
    artifact_id: UUID,
    user:  CurrentUser  = Depends(get_current_user),
    db:    AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo     = ArtifactRepository(db)
    artifact = await repo.get_by_id(artifact_id)
    if not artifact or artifact.course_id != course_id:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    chunk_count = await repo.count_chunks(artifact_id)
    return _to_response(artifact, chunk_count)


# ── GET /courses/{course_id}/artifacts/{artifact_id}/status ───────────────────

@router.get("/{course_id}/artifacts/{artifact_id}/status", response_model=ArtifactStatusResponse)
async def get_artifact_status(
    course_id:   UUID,
    artifact_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    """Poll this endpoint to track RAG processing progress."""
    await _assert_course_access(course_id, user, db)
    repo     = ArtifactRepository(db)
    artifact = await repo.get_by_id(artifact_id)
    if not artifact or artifact.course_id != course_id:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    chunk_count = await repo.count_chunks(artifact_id)
    return ArtifactStatusResponse(
        id=artifact.id,
        processing_status=artifact.processing_status,
        processing_error=artifact.processing_error,
        chunk_count=chunk_count,
    )


# ── DELETE /courses/{course_id}/artifacts/{artifact_id} ───────────────────────

@router.delete(
    "/{course_id}/artifacts/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_artifact(
    course_id:   UUID,
    artifact_id: UUID,
    user: CurrentUser  = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
):
    await _assert_course_access(course_id, user, db)
    repo     = ArtifactRepository(db)
    artifact = await repo.get_by_id(artifact_id)
    if not artifact or artifact.course_id != course_id:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    # Remove from disk
    if artifact.storage_path:
        UploadService().delete(artifact.storage_path)

    await repo.delete(artifact_id)
    logger.info(f"Artifact {artifact_id} deleted by {user.email}")


# ── Helper ────────────────────────────────────────────────────────────────────

def _to_response(artifact, chunk_count: int) -> ArtifactResponse:
    return ArtifactResponse(
        id=artifact.id,
        course_id=artifact.course_id,
        uploaded_by=artifact.uploaded_by,
        filename=artifact.filename,
        original_filename=artifact.original_filename,
        file_type=artifact.file_type,
        artifact_type=artifact.artifact_type,
        file_size_bytes=artifact.file_size_bytes,
        processing_status=artifact.processing_status,
        processing_error=artifact.processing_error,
        page_count=artifact.page_count,
        slide_count=artifact.slide_count,
        word_count=artifact.word_count,
        uploaded_at=artifact.uploaded_at,
        processed_at=artifact.processed_at,
        chunk_count=chunk_count,
    )

# ── Background ingestion import (added Phase 2) ───────────────────────────────
# Imported lazily to avoid circular imports during startup
def _trigger_ingestion(background_tasks, artifact_id, course_id, storage_path, file_type, artifact_type):
    from services.ingestion_task import run_ingestion_pipeline
    background_tasks.add_task(
        run_ingestion_pipeline,
        artifact_id=str(artifact_id),
        course_id=str(course_id),
        file_path=storage_path,
        file_type=file_type,
        artifact_type=artifact_type,
    )
