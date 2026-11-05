from sqlalchemy import select
from db.models.generated_content import ApprovalRecord

async def latest_text(item,db):
    revision=await db.scalar(select(ApprovalRecord.revision_text).where(ApprovalRecord.content_id==item.id,
        ApprovalRecord.decision=='revised').order_by(ApprovalRecord.decided_at.desc(),ApprovalRecord.id.desc()).limit(1))
    return revision or item.content
