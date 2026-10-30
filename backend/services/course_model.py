"""Conservative, source-linked extraction; candidates remain marked for lecturer review."""
import re
from uuid import UUID, uuid5, NAMESPACE_URL
from sqlalchemy import select
from db.models.artifact import CourseArtifact, Chunk
from db.models.course import Module, LearningObjective, Assessment, AssessmentQuestion
from db.models.source_link import AssessmentSource
from knowledge.bloom_classifier import classify_text

async def extract_course_model(course_id, db):
    rows = (await db.execute(select(Chunk, CourseArtifact).join(CourseArtifact,Chunk.artifact_id == CourseArtifact.id)
        .where(Chunk.course_id == course_id, CourseArtifact.processing_status == 'done')
        .order_by(Chunk.chunk_index))).all()
    modules = list((await db.scalars(select(Module).where(Module.course_id == course_id))).all())
    module = next((m for m in modules if m.title == 'Extracted source objectives'),None)
    existing = set((await db.scalars(select(LearningObjective.text).join(Module).where(Module.course_id == course_id))).all())
    existing_assessments = set((await db.scalars(select(Assessment.title).where(Assessment.course_id == course_id))).all())
    count = 0; assessment_count=0
    for chunk, artifact in rows:
        if artifact.artifact_type in ('syllabus','module_manual'):
            for line in re.split(r'\n|(?<=[.!?])\s+',chunk.text):
                line=line.strip()
                if not 15 <= len(line) <= 1000 or line in existing: continue
                if not re.search(r'(?i)(students?\s+(?:will|should|can)|able to|(?:CLO|ILO|LO)\s*\d|^[-*\d. )]*(?:explain|describe|implement|analyse|analyze|evaluate|design|apply|compare|identify)\b)',line): continue
                candidate_id=uuid5(NAMESPACE_URL,str(artifact.id)+':'+line)
                if await db.get(LearningObjective,candidate_id):continue
                if module is None:
                    module=Module(course_id=course_id,title='Extracted source objectives',sequence_number=len(modules)+1,
                        description='Deterministic extraction candidates. Review wording and Bloom levels before relying on audits.')
                    db.add(module);await db.flush()
                bloom,verb=classify_text(line)
                db.add(LearningObjective(id=candidate_id,module_id=module.id,text=line,code=f'EXT-{len(existing)+1}',
                    bloom_level=bloom,bloom_verb=verb,source_document_id=artifact.id,is_generated=False))
                existing.add(line);count+=1
        if artifact.artifact_type in ('assignment','exam','assessment'):
            title=f'{artifact.original_filename or artifact.filename} · source {str(chunk.id)[:8]}'
            if title in existing_assessments: continue
            assessment=Assessment(course_id=course_id,title=title,type='assignment',description=chunk.text)
            db.add(assessment);await db.flush()
            bloom,_=classify_text(chunk.text)
            questions=[t.strip() for t in re.split(r'(?m)(?:^|\n)(?:Question\s+\d+[:.)]?|Q\d+[:.)]|\d+[.)])\s+',chunk.text) if t.strip()]
            for question in questions[:50]:
                qbloom,_=classify_text(question)
                db.add(AssessmentQuestion(assessment_id=assessment.id,text=question,bloom_level=qbloom,question_type='unknown'))
            db.add(AssessmentSource(assessment_id=assessment.id,artifact_id=artifact.id,chunk_id=chunk.id))
            existing_assessments.add(title);assessment_count+=1
    if count or assessment_count:
        from services.model_version import touch_course
        await touch_course(course_id,db)
    await db.flush()
    return {'objectives_added':count,'assessments_added':assessment_count,'review_required':True,
            'method':'deterministic source extraction; Bloom levels are uncalibrated verb heuristics'}
