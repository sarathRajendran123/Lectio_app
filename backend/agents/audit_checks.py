"""Additional bidirectional checks using actual structured data and filtered retrieval.

These are explainable heuristics. Absence of a match is an evidence gap and
never proof that a topic is academically invalid or was not taught.
"""
import re
import uuid
from knowledge.bloom_classifier import classify_text,level_to_int
from agents.graph.state import AlignmentGap

TEACHING=['slides','transcript','reading','other']
ASSESSMENT=['assignment','exam','assessment']
METADATA=['syllabus','module_manual']

def _gap(kind,text,entity_type,entity_id,recommendation,chunks=(),score=0.,severity='warning'):
    return AlignmentGap(str(uuid.uuid4()),kind,severity,text,entity_type,entity_id,round(score,4),recommendation,[c.chunk_id for c in chunks[:3]])

def enrich(agent,state,dimension):
    result=state['alignment_results'][dimension]
    objectives=[o for m in state.get('modules',[]) for o in m.get('clos',[])]
    topics=[t for m in state.get('modules',[]) for w in m.get('weeks',[]) for t in w.get('topics',[])]
    assessments=state.get('assessments',[])
    result.findings['limitations']=['Only uploaded, processed artefacts were inspected. Missing materials and independent study can explain weak matches.',
        'Scores and Bloom classifications are heuristics requiring lecturer review.']
    if dimension=='metadata_content':
        for objective in objectives[:40]:
            if re.search(r'\b(understand|know|learn|be aware|familiar)\b',objective['text'],re.I) and not re.search(r'\b(explain|apply|design|compare|evaluate|implement|analyse|identify)\b',objective['text'],re.I):
                result.gaps.append(_gap('objective_not_measurable',f"Objective {objective.get('code') or objective['id']} uses a vague verb; the stated outcome may be difficult to verify.",
                    'clo',objective['id'],'Replace the vague verb with an observable action while preserving the intended scope.'))
        reverse=[]
        for topic in topics[:20]:
            evidence=agent._retrieve(topic['title'],state['course_id'],3,{'artifact_type':{'$in':TEACHING}})
            if not evidence or max(c.score for c in evidence)<.5:continue
            mapped=agent._retrieve(topic['title'],state['course_id'],3,{'artifact_type':{'$in':METADATA}})
            if not mapped or max(c.score for c in mapped)<.4:
                reverse.append(topic['title'])
                result.gaps.append(_gap('taught_topic_outside_metadata',f"Teaching evidence for '{topic['title']}' has no strong match in the supplied module metadata. This may be enrichment or incomplete metadata.",
                    'topic',topic.get('id'),'Confirm the intended scope; update objectives only if the topic is essential.',evidence,max(c.score for c in evidence), 'info'))
        result.findings['topics_without_metadata_match']=reverse
    if dimension=='metadata_assessment':
        mapping=[]
        cached={o['id']:agent._retrieve(o['text'],state['course_id'],6,{'artifact_type':{'$in':ASSESSMENT}}) for o in objectives[:30]}
        for assessment in assessments[:20]:
            for question in assessment.get('questions',[])[:15]:
                matches=[]
                for objective in objectives[:30]:
                    hits=cached[objective['id']]
                    question_source=[c for c in hits if question['text'] in c.text or c.text in question['text']]
                    if question_source and max(c.score for c in question_source)>=.45:matches.append(objective.get('code') or objective['id'])
                if not matches:
                    evidence=agent._retrieve(question['text'],state['course_id'],3,{'artifact_type':{'$in':ASSESSMENT}})
                    result.gaps.append(_gap('assessment_unclear_outcome',f"Assessment excerpt '{assessment['title']}' has no clear stated-outcome mapping in the available corpus.",
                        'assessment',assessment['id'],'Map this question to an outcome or document the legitimate independent-study expectation.',evidence))
                mapping.append({'assessment_id':assessment['id'],'question_id':question['id'],'outcome_codes':matches,'status':'supported' if matches else 'needs_review'})
        result.findings['question_outcome_map']=mapping
    if dimension=='content_delivery':
        sequence=[]
        for module in state.get('modules',[]):
            for week in module.get('weeks',[]):
                for topic in week.get('topics',[])[:10]:
                    chunks=agent._retrieve(topic['title'],state['course_id'],3,{'artifact_type':{'$in':TEACHING}})
                    for c in chunks:
                        if c.week_number and c.week_number != week['week_number'] and c.score>.6:
                            sequence.append({'topic':topic['title'],'planned_week':week['week_number'],'material_week':c.week_number,'chunk_id':c.chunk_id})
        result.findings['planned_sequence_differences']=sequence
        if sequence:
            result.gaps.append(_gap('planned_sequence_difference','Strong topic matches carry a different week number from the teaching plan. Preview and revision sessions are possible explanations.',
                'course',state['course_id'],'Review the source week labels and planned schedule; do not infer actual delivery from either.',score=.5,severity='info'))
        _delivery_verification(agent,state,result)
        methods=' '.join(str(w.get('title') or '') for m in state.get('modules',[]) for w in m.get('weeks',[]))
        if objectives and not methods.strip():
            result.gaps.append(_gap('delivery_information_missing','No planned activities or delivery descriptions are stored for this course.',
                'course',state['course_id'],'Enter planned teaching activities and resources before assessing delivery suitability.',severity='info'))
    _intent_checks(state,dimension,result,objectives,assessments)
    if result.gaps and result.status=='pass':result.status='warning'
    return state

def _delivery_verification(agent,state,result):
    """Planned vs delivered: compare the lecture transcript with the slides and notes (services/delivery_check.py).
    When both exist the dimension is scored on what the transcript shows; the earlier number, which only says
    that planned material is available, is kept beside it."""
    from rag.local_service import LocalRAGService
    from services import delivery_check, projection, trace
    try:
        chunks=agent._run_async(LocalRAGService().load(state['course_id'])) or []
    except Exception as exc:   # the planned-material checks above stand; say plainly that delivery was not verified
        result.findings['delivery_verification']={'ran':False,'reason':'The course materials could not be loaded for the delivery comparison: '+str(exc)[:200]}
        return
    planned=[c for c in chunks if c.artifact_type in delivery_check.PLANNED_TYPES]
    spoken=[c for c in chunks if c.artifact_type in delivery_check.TRANSCRIPT_TYPES]
    check=delivery_check.verify(planned,spoken,projection._vectors if projection._neural() else None)
    result.findings['delivery_verification']=check
    trace.emit('tool_call',{'tool':'delivery_verification','planned_chunks':len(planned),'transcript_chunks':len(spoken),'ran':check['ran'],
        'counts':check.get('counts'),'unplanned':len(check.get('unplanned',[])),'method':check.get('method')})
    if not check['ran']:return
    for section in check['sections']:
        if section['status']=='covered':continue
        missing=[p['point'] for p in section['points'] if not p['addressed']]
        said=[p['transcript']['chunk_id'] for p in section['points'] if p['addressed']]
        where=section['planned']
        source=f"{where.get('document') or 'planned material'}"+(f", slide {where['slide']}" if where.get('slide') else f", page {where['page']}" if where.get('page') else '')
        if section['status']=='not_covered':
            text=(f"Planned section '{section['title']}' ({source}) was not found in the transcript: none of its {section['points_total']} point(s) has a match. "
                "The recording or transcript may be incomplete.")
            kind,severity,action='delivery_not_covered','warning','Check whether this section was taught in a session without a transcript; otherwise update the slides or the plan.'
        else:
            text=(f"Planned section '{section['title']}' ({source}) appears only partly in the transcript: {section['points_addressed']} of {section['points_total']} point(s) matched. "
                f"Not found: {' | '.join(m[:140] for m in missing[:3])}")
            kind,severity,action='delivery_partial','info','Check whether the unmatched points were covered elsewhere or dropped on purpose.'
        gap=_gap(kind,text,'course',None,action,score=section['points_addressed']/section['points_total'],severity=severity)
        gap.evidence_chunk_ids=list(dict.fromkeys([where['chunk_id']]+said))[:4]
        result.gaps.append(gap)
    for item in check['unplanned']:
        said=item['transcript']
        gap=_gap('delivery_unplanned',f"The transcript{(' at '+said['timestamp']) if said.get('timestamp') else ''} covers content with no match in the slides or notes: \"{said['excerpt'][:200]}\". "
            "This may be an example, an aside, or new content.",'course',None,'Add it to the planned material if it is part of the course; otherwise no action is needed.',score=item['term_overlap'],severity='info')
        gap.evidence_chunk_ids=[said['chunk_id']]
        result.gaps.append(gap)
    result.findings['planned_material_score']=result.overall_score if result.status not in ('needs_review','failed') else None
    result.findings.pop('reason',None)
    result.findings['note']='Scored on whether planned content can be found in the lecture transcript. Not a judgement of teaching quality.'
    result.overall_score=check['delivered_share']
    result.status='pass' if result.overall_score>=.75 else 'warning' if result.overall_score>=.55 else 'fail'
    result.recommendations=[f"{check['counts']['not_covered']} planned section(s) not found in the transcript, {check['counts']['partial']} found only partly, "
        f"{len(check['unplanned'])} transcript segment(s) outside the planned material."]+[r for r in result.recommendations]

def _level(item):
    return item.get('bloom_level') or classify_text(item.get('text') or '')[0]

def _intent_checks(state,dimension,result,objectives,assessments):
    """Goal propagation into the analysis itself: compare the lecturer's intended cognitive levels with the
    stated objectives (described) and with the assessment questions (assessed). Scores are not changed; an
    intended level that nothing reaches is reported as its own finding."""
    intent=state.get('course_intent')
    result.findings['course_intent']={'id':intent['id'],'version':intent['version']} if intent else None
    wanted=(intent or {}).get('cognitive_levels') or []
    if not wanted or result.status in ('needs_review','failed'):
        if not intent:result.findings['intent_notice']='No course intent was stated, so the findings were not checked against the lecturer\'s goals.'
        return
    if dimension=='metadata_content':items,kind,noun,action=objectives,'intent_level_without_objective','stated learning objective','Add or revise an objective at this level, or change the course intent if the level is not wanted.'
    elif dimension=='metadata_assessment':
        items=[q for a in assessments for q in a.get('questions',[])]
        kind,noun,action='intent_level_not_assessed','assessment question','Add an assessment task at this level, or change the course intent if the level is not meant to be assessed.'
    else:return
    if not items:return
    reached=sorted({l for l in map(_level,items) if l},key=level_to_int)
    missing=[l for l in wanted if l not in reached]
    result.findings['intent_check']={'intended_levels':wanted,'levels_found':reached,'not_reflected':missing,'items_checked':len(items),'intent_version':intent['version']}
    for level in missing:
        result.gaps.append(_gap(kind,f"The course intent (version {intent['version']}) asks for the '{level}' level, but no {noun} was classified at that level. "
            f"Levels found: {', '.join(reached) or 'none could be classified'}.",'course',None,action,score=0.,severity='warning'))
