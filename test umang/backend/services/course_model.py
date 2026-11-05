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

PLAN_TYPES = ('syllabus', 'module_manual')
ASSESSMENT_TYPES = ('assignment', 'exam', 'assessment')
SCHEDULE_MODULE_TITLE = 'Course schedule (from syllabus)'

_PLAN_OUTCOME = re.compile(
    r'(?i)(students?\s+(?:will|should|can)|able to|(?:CLO|ILO|LO)\s*\d|'
    r'(?:studierende|lernende|absolvent(?:en|innen)?)n?\s+(?:können|sollen|werden|kennen)|in der lage|lernziel|'
    r'^[-*\d. )]*(?:explain|describe|implement|analyse|analyze|evaluate|design|apply|compare|identify|'
    r'erklären|beschreiben|implementieren|analysieren|bewerten|entwerfen|anwenden|vergleichen|berechnen)\b)')
_STATED_OUTCOME = re.compile(r'(?i)\b(?:students?|learners?|studierende[n]?|lernende[n]?)\s+(?:will|should|shall|are expected to|können|sollen|werden)\b')
_OUTCOME_CODE = re.compile(r'(?i)\b(?:CLO|ILO|LO)\s*\d')
_ABLE_TO = re.compile(r'(?i)\b(?:able to|in der lage|können)\b')
_WEEK_LINE = re.compile(
    r'(?im)^[ \t]*(?:[-*\u2022][ \t]*)?(?:week|wk|woche|vorlesung|sitzung|kw)[ \t]*(\d{1,2})[ \t]*[:\-\u2013\u2014.)][ \t]*(\S[^\n]{2,118}?)[ \t]*$')


def is_stated_outcome(line: str) -> bool:
    """Strict test for documents that are not course outlines (slides, papers, notes).

    Research text routinely contains 'able to' or 'students will ...' in other senses, so
    the author must either number the outcome (CLO1) or say students will *be able to*.
    """
    if _OUTCOME_CODE.search(line):
        return True
    return bool(_STATED_OUTCOME.search(line) and _ABLE_TO.search(line))


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
        if artifact.artifact_type not in ASSESSMENT_TYPES:
            plan = artifact.artifact_type in PLAN_TYPES
            for line in re.split(r'\n|(?<=[.!?])\s+',chunk.text):
                line=line.strip()
                if not 15 <= len(line) <= 1000 or line in existing: continue
                if plan:
                    if not _PLAN_OUTCOME.search(line): continue
                elif not is_stated_outcome(line): continue
                candidate_id=uuid5(NAMESPACE_URL,str(artifact.id)+':'+line)
                if await db.get(LearningObjective,candidate_id):continue
                if module is None:
                    module=Module(course_id=course_id,title='Extracted source objectives',sequence_number=len(modules)+1,
                        description='Deterministic extraction candidates. Review wording and Bloom levels before relying on audits.')
                    db.add(module);await db.flush()
                bloom,verb=classify_text(line)
                db.add(LearningObjective(id=candidate_id,module_id=module.id,text=line,code=f'EXT-{len(existing)+1}',
                    bloom_level=bloom,bloom_verb=verb,source_document_id=artifact.id,is_generated=True))
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
                db.add(AssessmentQuestion(assessment_id=assessment.id,text=question,bloom_level=qbloom,question_type='unknown'))
            db.add(AssessmentSource(assessment_id=assessment.id,artifact_id=artifact.id,chunk_id=chunk.id))
            existing_assessments.add(title);assessment_count+=1

    weeks_added = topics_added = 0
    has_weeks = await db.scalar(select(func.count(Week.id)).join(Module, Week.module_id == Module.id)
                                .where(Module.course_id == course_id))
    if not has_weeks:  # never overwrite or extend a schedule the lecturer already built
        schedule: dict[int, str] = {}
        for chunk, artifact in rows:
            if artifact.artifact_type not in PLAN_TYPES: continue
            for match in _WEEK_LINE.finditer(chunk.text):
                number, title = int(match.group(1)), match.group(2).strip(' .;:,')
                if 1 <= number <= 52 and title and number not in schedule:
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
            'method':'deterministic source extraction; Bloom levels are uncalibrated verb heuristics'}
