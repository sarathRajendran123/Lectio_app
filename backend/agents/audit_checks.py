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
        methods=' '.join(str(w.get('title') or '') for m in state.get('modules',[]) for w in m.get('weeks',[]))
        if objectives and not methods.strip():
            result.gaps.append(_gap('delivery_information_missing','No planned activities or delivery descriptions are stored for this course.',
                'course',state['course_id'],'Enter planned teaching activities and resources before assessing delivery suitability.',severity='info'))
    if result.gaps and result.status=='pass':result.status='warning'
    return state
