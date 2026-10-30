"""A continuous course review journey backed by authenticated API data."""
import json
import streamlit as st
from utils.session_utils import get_client, safe_api_call
from components.ui_components import render_citations

def show_workbench():
    st.title('Course workbench')
    st.caption('Inspect the sources. Audit alignment. Keep the final decision yours.')
    client=get_client()
    data,err=safe_api_call(client.list_courses)
    if err:st.error(err);return
    courses=(data or {}).get('courses',[])
    if not courses:
        st.info('Create your first course in Documents & upload, then return here.');return
    course=st.selectbox('Course',courses,format_func=lambda c:f"{c['code']} · {c['title']}")
    cid=course['id'];base=f'courses/{cid}'
    status,err=safe_api_call(client.workbench,'system/status')
    if status and status['mode']=='local_test':
        st.warning('LOCAL TEST MODE · deterministic retrieval and draft templates. No LLM inference has taken place.')
    tabs=st.tabs(['Sources & model','Alignment & evidence','Create drafts','Review & export'])
    with tabs[0]:
        st.subheader('Source collection')
        documents,err=safe_api_call(client.list_artifacts,cid)
        if err:st.error(err)
        for doc in (documents or {}).get('artifacts',[]):
            with st.expander(f"{doc.get('original_filename')} · {doc['processing_status']}"):
                st.caption(f"{doc.get('artifact_type')} · {doc.get('chunk_count',0)} chunks")
                if doc.get('processing_error'):st.error(doc['processing_error'])
                if doc['processing_status'] in ('error','done') and st.button('Retry / rebuild source index',key='retry'+doc['id']):
                    _,err=safe_api_call(client.workbench,base+f"/artifacts/{doc['id']}/retry",'POST')
                    if err:st.error(err)
                    else:st.rerun()
                if st.checkbox('Inspect extracted text',key='preview'+doc['id']):
                    chunks,err=safe_api_call(client.workbench,base+'/evidence?artifact_id='+doc['id'])
                    if err:st.error(err)
                    for c in chunks or []:
                        st.caption(f"{c['filename']} · page {c['page'] or '—'} · slide {c['slide'] or '—'} · {c['section'] or 'unlabelled section'}")
                        st.text(c['text'])
        if st.button('Extract source objectives & assessment text'):
            result,err=safe_api_call(client.workbench,base+'/extract-model','POST')
            if err:st.error(err)
            else:st.success(f"{result['objectives_added']} objectives and {result['assessments_added']} assessment excerpts added. Review them in Course Structure.")
        st.caption('Extraction uses explicit phrases in your files. Inferred Bloom levels require review; missing metadata stays unknown.')
        modules,_=safe_api_call(client.list_modules,cid)
        objectives=[]
        for module in modules or []:
            clos,_=safe_api_call(client.list_clos,cid,module['id']);objectives.extend(clos or [])
        if objectives:
            st.subheader('Review learning objectives')
            objective=st.selectbox('Extracted or entered objective',objectives,format_func=lambda o:o['text'])
            with st.form('review-objective'+objective['id']):
                text=st.text_area('Objective wording',value=objective['text'])
                levels=[None,'remember','understand','apply','analyse','evaluate','create']
                bloom=st.selectbox('Reviewed Bloom level',levels,index=levels.index(objective.get('bloom_level')) if objective.get('bloom_level') in levels else 0,format_func=lambda v:v or 'Unknown')
                save=st.form_submit_button('Save reviewed objective')
            if save:
                _,err=safe_api_call(client.workbench,base+'/objectives/'+objective['id'],'PATCH',{'text':text,'bloom_level':bloom})
                if err:st.error(err)
                else:st.success('Objective updated and review logged. Rerun the audit to update alignment.')
        if st.button('Group source topics'):
            result,err=safe_api_call(client.workbench,base+'/cluster-topics','POST')
            if err:st.error(err)
            else:
                st.caption(result['notice']);st.dataframe(result['groups'],width="stretch",hide_index=True)

    with tabs[1]:
        a,b=st.columns([3,1])
        a.subheader('Four dimensions, one review')
        if b.button('Run alignment audit',type='primary'):
            result,err=safe_api_call(client.run_audit,cid)
            if err:st.error(err)
            else:st.session_state['workbench_run_'+cid]=result['run_id'];st.rerun()
        run=st.session_state.get('workbench_run_'+cid)
        if run:
            info,err=safe_api_call(client.get_run_status,run)
            if err:st.error(err)
            else:
                st.info('Audit status: '+info['status'].replace('_',' '))
                if info.get('error_message'):st.warning(info['error_message'])
                x,y=st.columns(2)
                if x.button('Refresh audit progress'):st.rerun()
                if info['status']=='running' and y.button('Cancel audit'):
                    _,err=safe_api_call(client.workbench,'runs/'+run+'/cancel','POST')
                    if err:st.error(err)
                    else:st.rerun()
                steps,_=safe_api_call(client.get_run_steps,run)
                if steps:st.dataframe(steps,width="stretch",hide_index=True)
        matrix,err=safe_api_call(client.workbench,base+'/matrix')
        if err:st.error(err)
        elif matrix:
            st.caption(matrix['notice'])
            if matrix.get('stale'):st.warning('Course sources changed since this audit. Run a fresh audit before relying on this matrix.')
            if matrix['rows']:st.dataframe(matrix['rows'],width="stretch",hide_index=True)
        reports,err=safe_api_call(client.list_reports,cid)
        sources,_=safe_api_call(client.workbench,base+'/evidence')
        source_map={c['id']:c for c in sources or []}
        if reports:
            runs=list(dict.fromkeys(r['run_id'] for r in reports))
            selected=st.selectbox('Audit history',runs,format_func=lambda r:next(x['generated_at'][:19] for x in reports if x['run_id']==r)+' · '+r[:8])
            severity=st.multiselect('Finding priority',['critical','warning','info'],default=['critical','warning','info'])
            for meta in [r for r in reports if r['run_id']==selected]:
                with st.expander(meta['report_type'].replace('_',' ↔ ').title()+' · '+meta['status']):
                    report,err=safe_api_call(client.get_report,meta['id'])
                    if err:st.error(err);continue
                    findings=report.get('findings') or {}
                    details=findings.get('findings') or {}
                    if details.get('note') or details.get('error'):st.info(details.get('note') or details['error'])
                    if meta['report_type'] == 'content_delivery':
                        comparison = details.get('prepared_transcript_comparison', [])
                        if comparison:
                            st.markdown('**Prepared materials and transcript evidence**')
                            st.caption(details.get('comparison_notice', 'Lecturer review required.'))
                            if details.get('comparison_truncated'):
                                st.warning('Only the first 20 planned topics were compared.')
                            for row in comparison:
                                st.write(f"Week {row['week']} · {row['topic']} · {row['status'].replace('_', ' ')}")
                                for label, key in [('Prepared slides', 'prepared_chunk_ids'), ('Transcript', 'transcript_chunk_ids')]:
                                    st.caption(label)
                                    if not row.get(key):
                                        st.caption('No matching source excerpt found.')
                                    for ref in row.get(key, []):
                                        source = source_map.get(ref)
                                        if source:
                                            st.caption(f"{source['filename']} · page {source['page'] or '—'} · slide {source['slide'] or '—'}")
                                            st.text(source['text'])
                                        else:
                                            st.warning('Source no longer available. Rerun the audit.')
                                if row.get('prepared_context_ids'):
                                    st.caption('Additional text from the same pages (context, not necessarily a topic match):')
                                    for ref in row['prepared_context_ids']:
                                        source = source_map.get(ref)
                                        if source:
                                            st.caption(f"{source['filename']} · page {source['page'] or '—'}")
                                            st.text(source['text'])
                                        else:
                                            st.caption('Page context is unavailable in this view.')
                    st.caption('Scores are heuristic evidence indicators, not probabilities. Planned delivery does not verify attendance or teaching.')
                    broker=details.get('broker_review',{})
                    if broker.get('possible_conflicts'):st.warning('Potentially conflicting recommendations require lecturer review.');st.json(broker['possible_conflicts'])
                    if broker.get('ranked_findings'):st.dataframe(broker['ranked_findings'],width="stretch",hide_index=True)
                    decisions,_=safe_api_call(client.workbench,'reports/'+meta['id']+'/finding-decisions')
                    if decisions:st.dataframe(decisions,width="stretch",hide_index=True)
                    stored={g['id']:g for g in report.get('gaps',[])}
                    for gap in findings.get('gaps',[]):
                        if gap['severity'] not in severity:continue
                        st.markdown('**'+gap['gap_type'].replace('_',' ').title()+'**')
                        st.write(gap['description']);st.write('Suggested action: '+gap['recommendation'])
                        for ref in gap.get('evidence_chunk_ids',[]):
                            source=source_map.get(ref)
                            if source:
                                st.caption(f"{source['filename']} · page {source['page'] or '—'} · slide {source['slide'] or '—'}")
                                st.text(source['text'])
                            else:st.warning('Source no longer available. Rerun the audit after document changes.')
                        if not gap.get('evidence_chunk_ids'):st.caption('No direct supporting excerpt. This is an evidence gap requiring lecturer review.')
                        saved=stored.get(gap['gap_id'])
                        if saved:
                            with st.form('finding-review'+saved['id']):
                                decision=st.selectbox('Finding decision',['needs_review','approved','rejected','revised'])
                                rationale=st.text_input('Decision rationale')
                                revised=st.text_area('Revised recommendation (for revised decision)')
                                submit_review=st.form_submit_button('Record finding decision')
                            if submit_review:
                                _,review_error=safe_api_call(client.workbench,'reports/'+meta['id']+'/findings/'+saved['id']+'/review','POST',{'decision':decision,'rationale':rationale,'revised_recommendation':revised or None})
                                if review_error:st.error(review_error)
                                else:st.success('Finding decision recorded; generated content still requires separate approval.')
                        if saved and not saved['is_resolved'] and st.button('Mark reviewed / resolved',key='resolve'+saved['id']):
                            _,err=safe_api_call(client.resolve_gap,meta['id'],saved['id'])
                            if err:st.error(err)
                            else:st.rerun()
    with tabs[2]:
        st.subheader('Grounded alternatives')
        st.caption('Every result is a draft. Sources remain unchanged until you explicitly approve a proposal.')
        with st.form('generate'+cid):
            kind=st.selectbox('Content type',['clo','exercise','quiz','description','assessment_suggestion'])
            purpose=st.text_area('Purpose and relevant course topic',placeholder='Create an exercise on binary search complexity')
            constraints=st.text_area('Constraints',placeholder='Academic level, format, target Bloom level, duration…')
            modules,_=safe_api_call(client.list_modules,cid)
            objectives=[]
            for m in modules or []:
                clos,_=safe_api_call(client.list_clos,cid,m['id']);objectives.extend(clos or [])
            selected_objectives=st.multiselect('Relevant learning objectives',objectives,format_func=lambda o:o['text'])
            profiles,_=safe_api_call(client.workbench,'system/agent-profiles')
            styles=st.multiselect('Prompt styles',(profiles or {}).get('prompt_styles',['conceptual','applied','reflective']),default=['conceptual','applied'])
            models=st.multiselect('Configured model variants',(profiles or {}).get('models',[]))
            expected_format=st.text_input('Expected output format',placeholder='Two questions with marking criteria, or a short module description')
            alternatives=st.slider('Alternatives',1,3,2)
            submit=st.form_submit_button('Generate draft alternatives',type='primary')
        if submit:
            with st.spinner('Retrieving course evidence and preparing drafts…'):
                result,err=safe_api_call(client.workbench,base+'/generate','POST',{'content_type':kind,'purpose':purpose,
                    'constraints':constraints,'objective_ids':[o['id'] for o in selected_objectives],'alternatives':alternatives,'models':models,'prompt_styles':styles or ['conceptual'],'expected_format':expected_format})
            if err:st.error(err)
            else:st.session_state['variants'+cid]=result
        variants=st.session_state.get('variants'+cid,[])
        if variants:
            for col,item in zip(st.columns(len(variants)),variants):
                with col:
                    st.markdown('**'+item['title']+'**');st.caption(item['model_used']);st.write(item['content']);render_citations(item['citations'])
            st.info('Drafts are saved. Review, edit or approve them in Approval Center.')
    with tabs[3]:
        st.subheader('Review and preserve decisions')
        st.write('Approval Center retains original drafts, edited revisions, reviewer decisions and rationales. Revised drafts still require explicit approval.')
        if st.button('Open Approval Center'):
            st.session_state['nav_redirect']='Approval Center';st.rerun()
        approved,err=safe_api_call(client.list_approvals,'approved',cid)
        if approved:
            item=st.selectbox('Approved draft to apply',approved,format_func=lambda i:i.get('title') or i['id'])
            modules,_=safe_api_call(client.list_modules,cid)
            module=st.selectbox('Target module',modules or [None],format_func=lambda m:m['title'] if m else 'Create a module in Course Structure')
            outcome_text=st.text_area('Objective wording from approved draft (for CLO only)',value=item.get('content','') if item.get('content_type')=='clo' else '')
            if st.button('Apply approved draft to course model'):
                result,apply_error=safe_api_call(client.workbench,'approvals/'+item['id']+'/apply','POST',{'module_id':module['id'] if module else None,'outcome_text':outcome_text or None})
                if apply_error:st.error(apply_error)
                else:st.success('Approved change applied to the course model. Source documents remain preserved. Rerun alignment to inspect the result.')
        if st.button('Prepare course export'):
            export,err=safe_api_call(client.workbench,base+'/export')
            if err:st.error(err)
            else:st.session_state['export'+cid]=json.dumps(export,indent=2,ensure_ascii=False)
        if 'export'+cid in st.session_state:
            st.download_button('Download evidence & decision history',st.session_state['export'+cid],file_name='lectio-course-export.json',mime='application/json')

def show_system():
    st.title('System status')
    data,err=safe_api_call(get_client().workbench,'system/status')
    if err:st.error(err);return
    if st.button('Check service connectivity'):
        result,probe_error=safe_api_call(get_client().workbench,'system/probe')
        if probe_error:st.error(probe_error)
        else:st.json(result)
    for key,value in data.items():
        with st.container(border=True):
            st.markdown('**'+key.replace('_',' ').title()+'**');st.write(value)
