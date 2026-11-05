"""Database-backed admission lock; shared by all worker processes."""
from sqlalchemy import text,select,func
from fastapi import HTTPException
from db.models.generated_content import AgentRun
from db.models.artifact import CourseArtifact
from config import settings

async def lock_admission(db):
    if db.bind.dialect.name=='postgresql':
        await db.execute(text('SELECT pg_advisory_xact_lock(128947823)'))
    elif db.bind.dialect.name=='sqlite':
        await db.commit()
        await db.execute(text('BEGIN IMMEDIATE'))

async def assert_idle(course_id,db):
    active=await db.scalar(select(AgentRun.id).where(AgentRun.course_id==course_id,AgentRun.status.in_(['running','pending'])).limit(1))
    if active:raise HTTPException(409,'An audit is active. Wait or cancel it before changing the course sources or model.')

async def admit_audit(course_id,db):
    await lock_admission(db)
    await assert_idle(course_id,db)
    count=await db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.status.in_(['running','pending'])))
    if count>=settings.max_concurrent_runs:raise HTTPException(429,'Audit capacity reached; try again after a run completes.')
    processing=await db.scalar(select(CourseArtifact.id).where(CourseArtifact.course_id==course_id,
        CourseArtifact.processing_status.in_(['pending','parsing','chunking','embedding','storing'])).limit(1))
    if processing:raise HTTPException(409,'Wait for document processing to finish before starting the audit.')
