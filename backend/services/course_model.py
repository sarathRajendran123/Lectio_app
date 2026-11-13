"""Conservative, source-linked extraction; candidates remain marked for lecturer review.

Independence rule: *plan* documents (syllabus, module manual) state what the course
intends to teach, so they are a legitimate reference for audits and the weekly schedule
may be read from them. *Delivery* documents (slides, transcripts, papers) are the
evidence being audited; outcomes are only taken from them when the author states them
explicitly ("Students will be able to ..."). Anything that would have to be inferred
from delivery content is proposed for approval instead (see services/auto_build.py).
"""
import re
from uuid import UUID, uuid5, NAMESPACE_URL
from sqlalchemy import func, select
from db.models.artifact import CourseArtifact, Chunk
from db.models.course import Module, Week, Topic, LearningObjective, Assessment, AssessmentQuestion
from db.models.source_link import AssessmentSource
from knowledge.bloom_classifier import classify_text

async def _classify_rest(course_id, items) -> int:
    """Model fallback for objectives and questions the verb rules could not classify: one bounded call,
    live mode only. Items the model does not classify validly stay without a level."""
    from config import settings
    if not items or not settings.bloom_llm_fallback or settings.runtime_mode != 'live' or not settings.llm_ready:
        return 0
    import asyncio
    from knowledge.bloom_classifier import classify_many_with_llm
    from services import trace
    batch = items[:settings.bloom_llm_max_items]
    def ask():
        with trace.context(course_id=str(course_id), agent='bloom_classifier', task_id=f'course:{course_id}:bloom_levels'):
            return classify_many_with_llm([i.text for i in batch])
    answers = await asyncio.to_thread(ask)
    for index, (level, verb) in answers.items():
        batch[index].bloom_level = level
        if hasattr(batch[index], 'bloom_verb'):
            batch[index].bloom_verb = verb
    return len(answers)


PLAN_TYPES = ('syllabus', 'module_manual')
ASSESSMENT_TYPES = ('assignment', 'exam', 'assessment')
SCHEDULE_MODULE_TITLE = 'Course schedule (from syllabus)'

# The line rules live in knowledge/outline_rules.py (no database needed, measured in datasets/extraction).
from knowledge.outline_rules import _WEEK_LINE, is_stated_outcome, outcome_lines, schedule_entries  # noqa: E402,F401


async def extract_course_model(course_id, db):
    rows = (await db.execute(select(Chunk, CourseArtifact).join(CourseArtifact,Chunk.artifact_id == CourseArtifact.id)
        .where(Chunk.course_id == course_id, CourseArtifact.processing_status == 'done')
        .order_by(Chunk.chunk_index))).all()
    modules = list((await db.scalars(select(Module).where(Module.course_id == course_id))).all())
    module = next((m for m in modules if m.title == 'Extracted source objectives'),None)
    existing = set((await db.scalars(select(LearningObjective.text).join(Module).where(Module.course_id == course_id))).all())
    existing_assessments = set((await db.scalars(select(Assessment.title).where(Assessment.course_id == course_id))).all())
    count = 0; assessment_count=0; unclassified=[]
    for chunk, artifact in rows:
        if artifact.artifact_type not in ASSESSMENT_TYPES:
            plan = artifact.artifact_type in PLAN_TYPES
            for line in outcome_lines(chunk.text, plan):
                if line in existing: continue
                candidate_id=uuid5(NAMESPACE_URL,str(artifact.id)+':'+line)
                if await db.get(LearningObjective,candidate_id):continue
                if module is None:
                    module=Module(course_id=course_id,title='Extracted source objectives',sequence_number=len(modules)+1,
                        description='Deterministic extraction candidates. Review wording and Bloom levels before relying on audits.')
                    db.add(module);await db.flush()
                bloom,verb=classify_text(line)
                objective=LearningObjective(id=candidate_id,module_id=module.id,text=line,code=f'EXT-{len(existing)+1}',
                    bloom_level=bloom,bloom_verb=verb,source_document_id=artifact.id,is_generated=True)
                db.add(objective)
                if bloom is None:unclassified.append(objective)
                existing.add(line);count+=1
        else:
            title=f'{artifact.original_filename or artifact.filename} · source {str(chunk.id)[:8]}'
            if title in existing_assessments: continue
            assessment=Assessment(course_id=course_id,title=title,type='assignment',description=chunk.text)
            db.add(assessment);await db.flush()
            bloom,_=classify_text(chunk.text)
            questions=[t.strip() for t in re.split(r'(?m)(?:^|\n)(?:Question\s+\d+[:.)]?|Q\d+[:.)]|\d+[.)])\s+',chunk.text) if t.strip()]
            for question in questions[:50]:
                qbloom,_=classify_text(question)
                item=AssessmentQuestion(assessment_id=assessment.id,text=question,bloom_level=qbloom,question_type='unknown')
                db.add(item)
                if qbloom is None:unclassified.append(item)
            db.add(AssessmentSource(assessment_id=assessment.id,artifact_id=artifact.id,chunk_id=chunk.id))
            existing_assessments.add(title);assessment_count+=1

    model_classified=await _classify_rest(course_id,unclassified)

    weeks_added = topics_added = 0
    has_weeks = await db.scalar(select(func.count(Week.id)).join(Module, Week.module_id == Module.id)
                                .where(Module.course_id == course_id))
    if not has_weeks:  # never overwrite or extend a schedule the lecturer already built
        schedule: dict[int, str] = {}
        for chunk, artifact in rows:
            if artifact.artifact_type not in PLAN_TYPES: continue
            for number, title in schedule_entries(chunk.text):
                if number not in schedule:
                    schedule[number] = title
        if len(schedule) >= 2:  # one stray "Week 3: ..." mention is not a schedule
            top = await db.scalar(select(func.max(Module.sequence_number)).where(Module.course_id == course_id)) or 0
            sched = Module(course_id=course_id, title=SCHEDULE_MODULE_TITLE, sequence_number=top + 1,
                description='Weekly schedule read from the syllabus. Review before relying on delivery checks.')
            db.add(sched); await db.flush()
            for number in sorted(schedule):
                week = Week(module_id=sched.id, week_number=number, title=schedule[number])
                db.add(week); await db.flush()
                db.add(Topic(week_id=week.id, title=schedule[number], sequence_order=1))
                weeks_added += 1; topics_added += 1

    if count or assessment_count or weeks_added:
        from services.model_version import touch_course
        await touch_course(course_id,db)
    await db.flush()
    return {'objectives_added':count,'assessments_added':assessment_count,
            'weeks_added':weeks_added,'topics_added':topics_added,'review_required':True,
            'bloom_unclassified_by_rules':len(unclassified),'bloom_classified_by_model':model_classified,
            'method':'deterministic source extraction; Bloom levels come from verb rules'+(' and, where those found none, a model' if model_classified else '')+'; review them'}
