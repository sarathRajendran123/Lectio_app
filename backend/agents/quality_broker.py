"""Evidence-aware consolidation; contradictory actions remain visible for humans."""
import re
from collections import defaultdict

SEVERITY={'critical':3,'warning':2,'info':1,'pass':0}
def normalized(text):return ' '.join(re.findall(r'\w+',text.lower()))
def broker(results):
    groups={}; sources=defaultdict(list)
    for dimension,result in results.items():
        for gap in result.gaps:
            key=(gap.gap_type,gap.affected_entity_id or normalized(gap.description))
            sources[key].append({'dimension':dimension,'gap_id':gap.gap_id})
            if key not in groups or SEVERITY.get(gap.severity,0)>SEVERITY.get(groups[key].severity,0):groups[key]=gap
    ranked=[]
    entities=defaultdict(list)
    for key,gap in groups.items():
        evidence=len(set(gap.evidence_chunk_ids))
        strength='moderate' if evidence else 'insufficient'
        priority=SEVERITY.get(gap.severity,0)*10+min(evidence,5)
        ranked.append({'gap_id':gap.gap_id,'title':gap.gap_type.replace('_',' ').title(),'priority':priority,
            'evidence_strength':strength,'review_required':True,'source_findings':sources[key],
            'uncertainty':'Retrieved sources exist; inference still requires lecturer validation.' if evidence else 'No direct source supports this finding; confirm corpus completeness.',
            'alternatives':[gap.recommendation,'Check missing documents, planned independent study and lecturer intent before changing course content.']})
        if gap.affected_entity_id:entities[gap.affected_entity_id].append(gap)
    conflicts=[]
    for entity,gaps in entities.items():
        add=[g for g in gaps if re.search(r'\b(add|expand|raise|include)\b',g.recommendation,re.I)]
        remove=[g for g in gaps if re.search(r'\b(remove|reduce|exclude|lower)\b',g.recommendation,re.I)]
        if add and remove:
            conflicts.append({'entity_id':entity,'finding_ids':[g.gap_id for g in add+remove],
                'reason':'Recommendations suggest opposing actions for the same entity; lecturer adjudication required.'})
    return {'ranked_findings':sorted(ranked,key=lambda r:r['priority'],reverse=True),
        'possible_conflicts':conflicts,'duplicate_count':sum(len(v)-1 for v in sources.values()),
        'policy':'No recommendation is accepted without an explicit lecturer decision.'}
