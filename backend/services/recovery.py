"""Close work that a stopped server left half-done, so nothing stays "running" forever."""
from sqlalchemy import select, update

from db.models.artifact import CourseArtifact
from db.models.generated_content import AgentRun
from db.session import AsyncSessionLocal

RUN_MESSAGE = "Server restarted during audit; please rerun."
ARTIFACT_MESSAGE = "Server restarted during processing; retry ingestion."
INTERRUPTED = ["running", "paused"]
IN_PROGRESS = ["pending", "parsing", "chunking", "embedding", "storing"]


async def recover_interrupted_work() -> dict:
    # Assumes one backend process: a second live worker's runs would be closed too.
    async with AsyncSessionLocal() as db:
        runs = list((await db.execute(select(AgentRun.id, AgentRun.course_id).where(AgentRun.status.in_(INTERRUPTED)))).all())
        await db.execute(update(AgentRun).where(AgentRun.status.in_(INTERRUPTED)).values(status="failed", error_message=RUN_MESSAGE))
        documents = await db.execute(update(CourseArtifact).where(CourseArtifact.processing_status.in_(IN_PROGRESS))
                                     .values(processing_status="error", processing_error=ARTIFACT_MESSAGE))
        await db.commit()
    from services import trace
    for run_id, course_id in runs:
        await trace.aemit("run_finished", {"status": "failed", "tokens": 0, "error": RUN_MESSAGE},
                          subject=("run", str(run_id)), run_id=str(run_id), course_id=str(course_id), agent="recovery")
    return {"runs": len(runs), "documents": documents.rowcount or 0}
