"""Course-isolated evidence, generation, review history, export and operational status."""
import asyncio
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from fastapi.encoders import jsonable_encoder
from auth.rbac import get_current_user
from db.session import get_db
from db.models.artifact import Chunk, CourseArtifact
from db.models.course import Course, Module, LearningObjective
from db.models.generated_content import AgentRun, ApprovalRecord, GeneratedContentRecord
from db.models.report import AlignmentReport
from api.v1.routes.courses import _assert_course_access
from api.v1.routes.workflow_routes import _content_access
from config import settings

router=APIRouter()

@router.get('/system/status')
async def system_status(user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await db.execute(select(1))
    return {'database':'operational','mode':settings.runtime_mode,
        'model':settings.active_model if settings.runtime_mode == 'live' else 'deterministic test templates',
        'llm':'configured; not probed' if settings.active_api_key and settings.active_model else 'not configured',
        'retrieval':'local lexical hash vectors' if settings.runtime_mode == 'local_test' or settings.retrieval_backend=='lexical' else 'BGE / transactional SQL vectors; model not probed',
        'orchestrator':'LangGraph isolated workers','paperclip':'process adapter available; external deployment not verified',
        'confidence':'Heuristic evidence scores, not calibrated probabilities',
        'ocr':'Optional Tesseract; empty scans fail with an actionable error'}

@router.get('/dashboard')
async def dashboard(user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    courses=select(Course.id)
    if 'admin' not in user.roles: courses=courses.where(Course.coordinator_id == UUID(user.id))
    async def count(model,*conditions):
        return await db.scalar(select(func.count()).select_from(model).where(*conditions))
    return {'courses':await db.scalar(select(func.count()).select_from(courses.subquery())),
        'documents_processed':await count(CourseArtifact,CourseArtifact.course_id.in_(courses),CourseArtifact.processing_status=='done'),
        'audits_completed':await count(AgentRun,AgentRun.course_id.in_(courses),AgentRun.status.in_(['completed','waiting_for_human','needs_review'])),
        'pending':await count(GeneratedContentRecord,GeneratedContentRecord.course_id.in_(courses),GeneratedContentRecord.approval_status.in_(['pending','revised'])),
        'approved':await count(GeneratedContentRecord,GeneratedContentRecord.course_id.in_(courses),GeneratedContentRecord.approval_status=='approved'),
        'rejected':await count(GeneratedContentRecord,GeneratedContentRecord.course_id.in_(courses),GeneratedContentRecord.approval_status=='rejected')}

def chunk_dict(chunk, artifact):
    return {'id':str(chunk.id),'artifact_id':str(artifact.id),'filename':artifact.original_filename,
        'text':chunk.text,'page':chunk.page_number,'slide':chunk.slide_number,'section':chunk.section_title,
        'artifact_type':artifact.artifact_type,'week':chunk.week_number}

@router.get('/courses/{course_id}/evidence')
async def evidence(course_id:UUID,artifact_id:UUID|None=None,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    q=select(Chunk,CourseArtifact).join(CourseArtifact,Chunk.artifact_id==CourseArtifact.id).where(Chunk.course_id==course_id)
    if artifact_id: q=q.where(Chunk.artifact_id==artifact_id)
    return [chunk_dict(c,a) for c,a in (await db.execute(q.order_by(Chunk.chunk_index).limit(2000))).all()]

@router.post('/courses/{course_id}/extract-model')
async def extract_model(course_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    from services.admission import assert_idle
    await assert_idle(course_id,db)
    from services.course_model import extract_course_model
    return await extract_course_model(course_id,db)

@router.get('/courses/{course_id}/matrix')
async def matrix(course_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    reports=list((await db.scalars(select(AlignmentReport).where(AlignmentReport.course_id==course_id)
        .order_by(AlignmentReport.generated_at.desc()))).all())
    if not reports:return {'run_id':None,'rows':[],'notice':'Run an audit to calculate coverage.'}
    latest=reports[0].run_id
    results={r.report_type:(r.findings or {}).get('findings',{}) for r in reports if r.run_id==latest}
    content={r['code']:r for r in results.get('metadata_content',{}).get('clo_scores',[])}
    assessments={r['code']:r for r in results.get('metadata_assessment',{}).get('clo_assessment_map',[])}
    rows=[]
    for code in dict.fromkeys([*content,*assessments]):
        c=content.get(code,{});a=assessments.get(code,{})
        rows.append({'outcome':code,'text':c.get('text') or a.get('text'),
            'content':c.get('status','unknown'), 'assessment':'supported' if a.get('covered') else 'needs review',
            'content_score':c.get('score'),'assessment_score':a.get('score'),
            'content_sources':c.get('evidence_chunk_ids',[]),'assessment_sources':a.get('evidence_chunk_ids',[])})
    run=await db.get(AgentRun,latest)
    original=(run.workflow_state or {}).get('source_manifest',[]) if run else []
    current=list((await db.scalars(select(CourseArtifact).where(CourseArtifact.course_id==course_id))).all())
    stale={a['id']:(a.get('checksum'),a.get('processed_at')) for a in original}!={str(a.id):(a.checksum,a.processed_at.isoformat() if a.processed_at else None) for a in current}
    model=await db.get(Course,course_id)
    old_version=(run.workflow_state or {}).get('course_metadata',{}).get('model_version') if run else None
    stale=stale or old_version!=model.updated_at.isoformat()
    return {'run_id':str(latest),'rows':rows,'stale':stale,'notice':'Heuristic matches in supplied documents; lecturer review required.'}

class GenerationRequest(BaseModel):
    content_type:Literal['clo','exercise','quiz','description','assessment_suggestion']
    purpose:str=Field(min_length=8,max_length=2000)
    constraints:str=Field(default='',max_length=2000)
    objective_ids:list[UUID]=Field(default_factory=list,max_length=20)
    alternatives:int=Field(default=2,ge=1,le=3)
    models:list[str]=Field(default_factory=list,max_length=3)
    prompt_styles:list[Literal['conceptual','applied','reflective']]=Field(default_factory=lambda:['conceptual','applied','reflective'],max_length=3,min_length=1)
    gap_id:UUID|None=None
    expected_format:str=Field(default='',max_length=500)

_generation_lock=asyncio.Semaphore(2)
@router.post('/courses/{course_id}/generate',status_code=201)
async def generate(course_id:UUID,body:GenerationRequest,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    objectives=[]
    if body.objective_ids:
        objectives=list((await db.scalars(select(LearningObjective).join(Module).where(
            Module.course_id==course_id,LearningObjective.id.in_(body.objective_ids)))).all())
        if len(objectives)!=len(set(body.objective_ids)):
            raise HTTPException(422,'An objective does not belong to this course.')
    from rag.rag_service import RAGService
    from rag.generation.grounded_generator import GroundedGenerator
    from services.review import latest_text
    rag=RAGService.get_instance()
    allowed_models={settings.active_model,*settings.active_model_variants}
    if any(model not in allowed_models for model in body.models):raise HTTPException(422,'A model variant is not in the configured allow-list.')
    gap=None
    if body.gap_id:
        from db.models.report import AlignmentGapRecord
        gap=await db.scalar(select(AlignmentGapRecord).join(AlignmentReport).where(AlignmentGapRecord.id==body.gap_id,AlignmentReport.course_id==course_id))
        if not gap:raise HTTPException(404,'Related finding does not belong to this course.')
    query=body.purpose+' '+' '.join(o.text for o in objectives)+((' '+gap.description) if gap else '')
    records=[]
    async with _generation_lock:
        try:
            context=await asyncio.to_thread(rag.retrieve,query,str(course_id),8)
            for variant in range(body.alternatives):
                style=body.prompt_styles[variant%len(body.prompt_styles)]
                model=body.models[variant%len(body.models)] if body.models else settings.active_model
                prompt=f'Generate {body.content_type}. Purpose: {body.purpose}. Alternative {variant+1}. '+\
                    f'Use {style} style. Expected format: {body.expected_format or body.content_type}. Constraints: {body.constraints}. Related finding: {gap.description if gap else "none selected"}. '+\
                    'Outcomes: '+'; '.join(o.text for o in objectives)
                result=await asyncio.to_thread(GroundedGenerator(model=model).generate,prompt,context)
                record=GeneratedContentRecord(course_id=course_id,content_type=body.content_type,
                    title=f'{body.content_type.title()} · Alternative {variant+1} ({style})',content=result.content,
                    source_gap_id=str(gap.id) if gap else None,
                    citations=result.citations,model_used=result.model,approval_status='pending',confidence_score=None)
                db.add(record);records.append(record)
        except ValueError as exc: raise HTTPException(422,str(exc))
    await db.flush()
    return [{'id':str(r.id),'title':r.title,'content':r.content,'citations':r.citations,'model_used':r.model_used,'approval_status':'pending'} for r in records]

@router.get('/approvals/{content_id}/history')
async def decision_history(content_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    item=await _content_access(content_id,user,db)
    rows=list((await db.scalars(select(ApprovalRecord).where(ApprovalRecord.content_id==content_id).order_by(ApprovalRecord.decided_at,ApprovalRecord.id))).all())
    return {'original':item.content,'status':item.approval_status,'decisions':[{'id':str(r.id),'decision':r.decision,
        'comment':r.comment,'revision':r.revision_text,'reviewer_id':str(r.reviewer_id),'decided_at':r.decided_at} for r in rows]}

@router.get('/courses/{course_id}/export')
async def export_course(course_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    course=await db.get(Course,course_id)
    reports=list((await db.scalars(select(AlignmentReport).where(AlignmentReport.course_id==course_id))).all())
    items=list((await db.scalars(select(GeneratedContentRecord).where(GeneratedContentRecord.course_id==course_id))).all())
    from services.review import latest_text
    content=[]
    for i in items:
        history=await decision_history(i.id,user,db)
        content.append({'id':str(i.id),'title':i.title,'status':i.approval_status,'original':i.content,
            'current_draft':await latest_text(i,db),'accepted_content':await latest_text(i,db) if i.approval_status=='approved' else None,
            'citations':i.citations,'model':i.model_used,'history':history['decisions']})
    from db.models.review import AppliedSuggestion
    applied=list((await db.scalars(select(AppliedSuggestion).join(GeneratedContentRecord,AppliedSuggestion.content_id==GeneratedContentRecord.id).where(GeneratedContentRecord.course_id==course_id))).all())
    return jsonable_encoder({'applied_changes':[{'content_id':str(a.content_id),'target_type':a.target_type,'target_id':str(a.target_id),'accepted_snapshot':a.accepted_snapshot,'applied_by':str(a.applied_by),'created_at':a.created_at} for a in applied],'schema_version':2,'course':{'id':str(course.id),'code':course.code,'title':course.title},
        'mode':settings.runtime_mode,'reports':[{'id':str(r.id),'run_id':str(r.run_id),'dimension':r.report_type,'findings':r.findings} for r in reports],
        'suggestions':content,'finding_decisions':{str(r.id):await finding_decisions(r.id,user,db) for r in reports},'sources':await evidence(course_id,None,user,db)})

@router.post('/courses/{course_id}/artifacts/{artifact_id}/retry')
async def retry_ingestion(course_id:UUID,artifact_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    from services.admission import assert_idle
    await assert_idle(course_id,db)
    artifact=await db.get(CourseArtifact,artifact_id)
    if not artifact or artifact.course_id!=course_id:raise HTTPException(404,'Document not found.')
    if artifact.processing_status not in ('error','done'):raise HTTPException(409,'Only failed or processed documents can be rebuilt.')
    from db.models.source_link import AssessmentSource
    from db.models.course import Assessment
    from sqlalchemy import delete
    derived=select(AssessmentSource.assessment_id).where(AssessmentSource.artifact_id==artifact_id)
    await db.execute(delete(Assessment).where(Assessment.id.in_(derived)))
    from sqlalchemy import delete
    from services.document_cleanup import invalidate_artifact
    await invalidate_artifact(course_id,artifact_id)
    await db.execute(delete(Chunk).where(Chunk.artifact_id==artifact_id))
    artifact.processing_status='pending';artifact.processing_error=None
    await db.commit()
    from services.ingestion_task import run_ingestion_pipeline
    await run_ingestion_pipeline(str(artifact_id),str(course_id),artifact.storage_path,artifact.file_type,artifact.artifact_type)
    return {'status':'retry finished; refresh documents for result'}

@router.post('/courses/{course_id}/cluster-topics')
async def cluster_topics(course_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    from services.admission import assert_idle
    await assert_idle(course_id,db)
    chunks=list((await db.scalars(select(Chunk).where(Chunk.course_id==course_id).order_by(Chunk.id).limit(200))).all())
    from services.topic_clusters import cluster
    groups=await asyncio.to_thread(cluster,chunks)
    assignments={cid:g for g in groups for cid in g['chunk_ids']}
    for chunk in chunks:
        group=assignments[str(chunk.id)]
        chunk.metadata_=dict(chunk.metadata_ or {},topic_cluster={k:v for k,v in group.items() if k!='chunk_ids'})
    await db.flush()
    return {'groups':groups,'notice':'At most 200 chunks per clustering request; labels are source-term summaries requiring review.'}

class ObjectiveEdit(BaseModel):
    text:str=Field(min_length=8,max_length=3000)
    bloom_level:Literal['remember','understand','apply','analyse','evaluate','create']|None=None

@router.patch('/courses/{course_id}/objectives/{objective_id}')
async def edit_objective(course_id:UUID,objective_id:UUID,body:ObjectiveEdit,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    from services.admission import assert_idle
    await assert_idle(course_id,db)
    objective=await db.scalar(select(LearningObjective).join(Module).where(Module.course_id==course_id,LearningObjective.id==objective_id))
    if not objective:raise HTTPException(404,'Objective not found in this course.')
    from api.v1.middleware.audit_logger import AuditLog
    db.add(AuditLog(user_id=UUID(user.id),action='objective_review',resource_type='learning_objective',resource_id=objective.id,
        metadata_={'previous':objective.text,'revised':body.text,'previous_bloom':objective.bloom_level,'bloom_level':body.bloom_level}))
    from services.model_version import touch_course
    await touch_course(course_id,db)
    objective.text=body.text;objective.bloom_level=body.bloom_level
    await db.flush()
    return {'id':str(objective.id),'text':objective.text,'bloom_level':objective.bloom_level,'reviewed':True}

@router.get('/system/probe')
async def probe(user=Depends(get_current_user)):
    from services.health_service import probe_services
    return await probe_services()

class FindingReview(BaseModel):
    decision:Literal['approved','rejected','needs_review','revised']
    rationale:str=Field(default='',max_length=3000)
    revised_recommendation:str|None=Field(default=None,max_length=5000)

@router.post('/reports/{report_id}/findings/{gap_id}/review')
async def review_finding(report_id:UUID,gap_id:UUID,body:FindingReview,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    from db.models.report import AlignmentGapRecord
    from db.models.review import FindingDecision
    report=await db.get(AlignmentReport,report_id)
    if not report:raise HTTPException(404,'Report not found.')
    await _assert_course_access(report.course_id,user,db)
    gap=await db.get(AlignmentGapRecord,gap_id)
    if not gap or gap.report_id!=report_id:raise HTTPException(404,'Finding not found in report.')
    if body.decision=='revised' and not (body.revised_recommendation or '').strip():raise HTTPException(422,'A revised recommendation is required.')
    row=FindingDecision(gap_id=gap_id,reviewer_id=UUID(user.id),decision=body.decision,rationale=body.rationale,
        revised_recommendation=body.revised_recommendation,
        version_context={'run_id':str(report.run_id),'source_manifest':(report.findings or {}).get('findings',{}).get('source_manifest',[])})
    db.add(row)
    # Acceptance of a finding is separate from resolving it or accepting generated content.
    await db.flush()
    return {'decision_id':str(row.id),'status':body.decision,'content_approved':False}

@router.get('/reports/{report_id}/finding-decisions')
async def finding_decisions(report_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    from db.models.review import FindingDecision
    from db.models.report import AlignmentGapRecord
    report=await db.get(AlignmentReport,report_id)
    if not report:raise HTTPException(404,'Report not found.')
    await _assert_course_access(report.course_id,user,db)
    rows=list((await db.scalars(select(FindingDecision).join(AlignmentGapRecord,FindingDecision.gap_id==AlignmentGapRecord.id)
        .where(AlignmentGapRecord.report_id==report_id).order_by(FindingDecision.created_at))).all())
    return [{'id':str(r.id),'gap_id':str(r.gap_id),'decision':r.decision,'rationale':r.rationale,
        'revised_recommendation':r.revised_recommendation,'reviewer_id':str(r.reviewer_id),'version_context':r.version_context,'created_at':r.created_at} for r in rows]

@router.get('/courses/{course_id}/structure')
async def structured_course(course_id:UUID,user=Depends(get_current_user),db=Depends(get_db, scope="function")):
    await _assert_course_access(course_id,user,db)
    from db.repositories.course_repository import CourseRepository
    from db.models.source_link import AssessmentSource
    course=await CourseRepository(db).get_by_id_with_modules(course_id)
    links=list((await db.scalars(select(AssessmentSource).join(CourseArtifact,AssessmentSource.artifact_id==CourseArtifact.id).where(CourseArtifact.course_id==course_id))).all())
    source_map={str(l.assessment_id):{'artifact_id':str(l.artifact_id),'chunk_id':str(l.chunk_id),'method':l.extraction_method} for l in links}
    return {'course_id':str(course_id),'metadata':{'title':course.title,'code':course.code,'description':course.description},
        'modules':[{'id':str(m.id),'title':m.title,'objectives':[{'id':str(o.id),'text':o.text,'bloom_level':o.bloom_level,'source_document_id':str(o.source_document_id) if o.source_document_id else None} for o in m.learning_objectives],
            'planned_weeks':[{'week':w.week_number,'title':w.title,'topics':[{'id':str(t.id),'title':t.title} for t in w.topics]} for w in m.weeks]} for m in course.modules],
        'assessments':[{'id':str(a.id),'title':a.title,'type':a.type,'source':source_map.get(str(a.id)),
            'questions':[{'id':str(q.id),'text':q.text,'bloom_level':q.bloom_level,'marks':q.marks} for q in a.questions]} for a in course.assessments]}

class ApplySuggestion(BaseModel):
    module_id:UUID|None=None
    outcome_text:str|None=Field(default=None,min_length=8,max_length=3000)

@router.post('/approvals/{content_id}/apply')
async def apply_approved(content_id:UUID,body:ApplySuggestion,user=Depends(get_current_user),db=Depends(get_db)):
    from db.models.review import AppliedSuggestion
    from db.models.course import Assessment
    from services.review import latest_text
    from services.admission import assert_idle
    from knowledge.bloom_classifier import classify_text
    item=await _content_access(content_id,user,db)
    await assert_idle(item.course_id,db)
    if item.approval_status!='approved':raise HTTPException(409,'Only explicitly approved drafts can be applied to the course model.')
    if await db.get(AppliedSuggestion,content_id):raise HTTPException(409,'This draft has already been applied; review the course model before making another change.')
    accepted=await latest_text(item,db)
    module=None
    if body.module_id:
        module=await db.get(Module,body.module_id)
        if not module or module.course_id!=item.course_id:raise HTTPException(404,'Target module does not belong to this course.')
    if item.content_type=='clo':
        if not module:raise HTTPException(422,'Choose a target module for the approved objective.')
        text=body.outcome_text or accepted
        if text not in accepted:raise HTTPException(422,'Objective wording must be taken from the approved draft. Revise and approve it before changing wording.')
        bloom,verb=classify_text(text)
        target=LearningObjective(module_id=module.id,text=text,code='GEN-'+str(item.id)[:8],bloom_level=bloom,bloom_verb=verb,is_generated=True)
        db.add(target);await db.flush();target_type='learning_objective'
    elif item.content_type=='description':
        if not module:raise HTTPException(422,'Choose a target module for the approved description.')
        module.description=accepted;target=module;target_type='module_description'
    elif item.content_type in ('exercise','quiz','assessment_suggestion','assessment'):
        target=Assessment(course_id=item.course_id,title='Approved Lectio draft: '+(item.title or 'Assessment'),
            type='quiz' if item.content_type=='quiz' else 'assignment',description=accepted)
        db.add(target);await db.flush();target_type='assessment'
    else:raise HTTPException(422,'This draft type cannot be applied to a course model.')
    from services.model_version import touch_course
    await touch_course(item.course_id,db)
    db.add(AppliedSuggestion(content_id=item.id,target_type=target_type,target_id=target.id,applied_by=UUID(user.id),accepted_snapshot=accepted))
    await db.flush()
    return {'applied':True,'target_type':target_type,'target_id':str(target.id),'source_documents_modified':False,'rerun_audit_required':True}

@router.get('/system/agent-profiles')
async def agent_profiles(user=Depends(get_current_user)):
    return {'models':[m for m in dict.fromkeys([settings.active_model,*settings.active_model_variants]) if m],
        'prompt_styles':['conceptual','applied','reflective'],
        'contracts':[{'agent':name,'responsibility':role} for name,role in [
            ('course_director','Load source/model versions, propagate course constraints and route dependencies'),
            ('metadata_content_agent','Compare objectives and metadata with teaching evidence in both directions'),
            ('content_assessment_agent','Compare assessed tasks with teaching evidence and cognitive demands'),
            ('metadata_assessment_agent','Map objectives and assessment tasks in both directions'),
            ('content_delivery_agent','Compare planned topics, sequence and resources; do not assert actual teaching'),
            ('content_generation_agent','Generate schema-validated, source-linked draft alternatives'),
            ('stakeholder_agent','Rank and consolidate findings, flag conflicts and retain lecturer decisions')]],
        'mode':settings.runtime_mode,'notice':'Model availability must be checked against the configured provider account.'}
