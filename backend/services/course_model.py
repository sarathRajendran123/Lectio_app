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

async def _model_levels(course_id, texts) -> dict:
    """Model fallback for objectives and questions the verb rules could not classify: one bounded call,
    live mode only, made BEFORE anything is written. A model call inside an open write transaction held the
    SQLite write lock for its whole duration: an audit started meanwhile failed with "database is locked",
    and the call's own trace event could not be written. Returns {text: (level, verb)} for valid answers."""
    from config import settings
    if not texts or not settings.bloom_llm_fallback or settings.runtime_mode != 'live' or not settings.llm_ready:
        return {}
    import asyncio
    from knowledge.bloom_classifier import classify_many_with_llm
    from services import trace
    batch = list(texts)[:settings.bloom_llm_max_items]
    def ask():
        with trace.context(course_id=str(course_id), agent='bloom_classifier', task_id=f'course:{course_id}:bloom_levels'):
            return classify_many_with_llm(batch)
    answers = await asyncio.to_thread(ask)
    return {batch[index]: answer for index, answer in answers.items()}


PLAN_TYPES = ('syllabus', 'module_manual')
ASSESSMENT_TYPES = ('assignment', 'exam', 'assessment')
SCHEDULE_MODULE_TITLE = 'Course schedule (from syllabus)'

# The line rules live in knowledge/outline_rules.py (no database needed, measured in datasets/extraction).
from knowledge.outline_rules import _WEEK_LINE, is_fragment_of, is_stated_outcome, outcome_lines, prose_outcomes, schedule_entries, table_schedule  # noqa: E402,F401


async def extract_course_model(course_id, db):
    from db.chunk_visibility import current_chunk
    rows = (await db.execute(select(Chunk, CourseArtifact).join(CourseArtifact,Chunk.artifact_id == CourseArtifact.id)
        .where(Chunk.course_id == course_id, CourseArtifact.processing_status == 'done', current_chunk())
        .order_by(Chunk.chunk_index))).all()
    modules = list((await db.scalars(select(Module).where(Module.course_id == course_id))).all())
    module = next((m for m in modules if m.title == 'Extracted source objectives'),None)
    existing = set((await db.scalars(select(LearningObjective.text).join(Module).where(Module.course_id == course_id))).all())
    existing_assessments = set((await db.scalars(select(Assessment.title).where(Assessment.course_id == course_id))).all())
    count = 0; assessment_count=0
    # A plan document is also read as a whole: outcome paragraphs and schedule tables are often split across passages.
    documents={}
    for chunk, artifact in rows:
        if artifact.artifact_type in PLAN_TYPES:documents.setdefault(artifact.id,(artifact,[]))[1].append(chunk.text or '')
    prose={aid:prose_outcomes('\n'.join(texts)) for aid,(artifact,texts) in documents.items()}
    first_chunk={}
    for chunk, artifact in rows:first_chunk.setdefault(artifact.id,chunk.id)
    # Plan everything first (reads only), ask the model once, then write.
    planned=[];pending={};seen=set(existing);seen_titles=set(existing_assessments)
    for chunk, artifact in rows:
        if artifact.artifact_type not in ASSESSMENT_TYPES:
            plan = artifact.artifact_type in PLAN_TYPES
            lines=[l for l in outcome_lines(chunk.text, plan) if not is_fragment_of(l,prose.get(artifact.id,[]))]
            if chunk.id==first_chunk.get(artifact.id):lines+=prose.get(artifact.id,[])
            for line in dict.fromkeys(lines):
                if line in seen: continue
                candidate_id=uuid5(NAMESPACE_URL,str(artifact.id)+':'+line)
                if await db.get(LearningObjective,candidate_id):continue
                seen.add(line);planned.append(('objective',chunk,artifact,line))
                if classify_text(line)[0] is None:pending[line]=None
        else:
            title=f'{artifact.original_filename or artifact.filename} · source {str(chunk.id)[:8]}'
            if title in seen_titles: continue
            seen_titles.add(title)
            questions=[t.strip() for t in re.split(r'(?m)(?:^|\n)(?:(?:Question|Task|Exercise|Aufgabe|Frage|Übung)\s+\d+[:.)]?|Q\d+[:.)]|\d+[.)])\s+',chunk.text) if t.strip()][:50]
            planned.append(('assessment',chunk,artifact,(title,questions)))
            for question in questions:
                if classify_text(question)[0] is None:pending[question]=None
    model_levels=await _model_levels(course_id,list(pending))

    def level_of(text):
        level,verb=classify_text(text)
        return model_levels.get(text,(level,verb)) if level is None else (level,verb)

    for kind, chunk, artifact, payload in planned:
        if kind=='objective':
            line=payload
            if module is None:
                module=Module(course_id=course_id,title='Extracted source objectives',sequence_number=len(modules)+1,
                    description='Deterministic extraction candidates. Review wording and Bloom levels before relying on audits.')
                db.add(module);await db.flush()
            bloom,verb=level_of(line)
            db.add(LearningObjective(id=uuid5(NAMESPACE_URL,str(artifact.id)+':'+line),module_id=module.id,text=line,code=f'EXT-{len(existing)+1}',
                bloom_level=bloom,bloom_verb=verb,source_document_id=artifact.id,is_generated=True))
            existing.add(line);count+=1
        else:
            title,questions=payload
            assessment=Assessment(course_id=course_id,title=title,type='assignment',description=chunk.text)
            db.add(assessment);await db.flush()
            for question in questions:
                db.add(AssessmentQuestion(assessment_id=assessment.id,text=question,bloom_level=level_of(question)[0],question_type='unknown'))
            db.add(AssessmentSource(assessment_id=assessment.id,artifact_id=artifact.id,chunk_id=chunk.id))
            existing_assessments.add(title);assessment_count+=1

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
        for artifact, texts in documents.values():
            for number, title in table_schedule('\n'.join(texts)):
                schedule.setdefault(number, title)
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
            'bloom_unclassified_by_rules':len(pending),'bloom_classified_by_model':len(model_levels),
            'method':'deterministic source extraction; Bloom levels come from verb rules'+(' and, where those found none, a model' if model_levels else '')+'; review them'}
