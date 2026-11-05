"""Mark all reviewed course-model mutations so previous audit views become stale."""
from datetime import datetime,timezone
from sqlalchemy import update
from db.models.course import Course

async def touch_course(course_id,db):
    await db.execute(update(Course).where(Course.id==course_id).values(updated_at=datetime.now(timezone.utc)))
