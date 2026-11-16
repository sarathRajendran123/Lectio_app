from agents.graph.state import AlignmentResult,AlignmentGap,Node
from agents.course_director import CourseDirectorAgent
from agents.live_review import augment
from rag.chunking.chunk_models import RetrievedChunk
from scripts.evaluate import evaluate
import pytest

def test_director_merges_before_generation_route(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings,'generation_auto_enabled',True)
    gap=AlignmentGap('g','clo_not_covered','warning','Missing topic','clo',None,0.,'Review sources')
    state={'course_id':'x','course_metadata':{'title':'x'},'alignment_results':{
        dimension:AlignmentResult('a',dimension,.5,'warning',[gap] if dimension=='metadata_content' else [])
        for dimension in ('metadata_content','content_assessment','metadata_assessment','content_delivery')},'all_gaps':[]}
    result=CourseDirectorAgent().run(state)
    assert result['current_node']==Node.CONTENT_GENERATION
    assert len(result['all_gaps'])==1

def test_live_review_rejects_unretrieved_evidence():
    import json
    class Agent:
        def _retrieve(self,*a,**k):return [RetrievedChunk('real','Real source excerpt',.8,'a','slides','c',1,None,None,None)]
        def _invoke(self,*a,**k):return json.dumps({'findings':[{'title':'Finding','description':'An unsupported conclusion','severity':'warning','rationale':'Rationale here','correction':'Review this issue','evidence_ids':['invented'],'evidence_strength':'strong'}],'limitations':'Unverified'}),10
        def _parse_json(self,text):return json.loads(text)
    state={'course_id':'c','modules':[],'course_metadata':{'title':'Topic'},'alignment_results':{'metadata_content':AlignmentResult('a','metadata_content',.5,'warning')}}
    augment(Agent(),state,'metadata_content')
    result=state['alignment_results']['metadata_content']
    assert result.gaps==[] and result.findings['live_review']['discarded_unverifiable']==1   # invented evidence never surfaces

def test_evaluation_is_ground_truth_based():
    result=evaluate([{'predicted':'1','actual':'1','accepted':'1','quality':'4'}, {'predicted':'1','actual':'0','accepted':'0'}, {'predicted':'0','actual':'1'}])
    assert result['precision']==.5 and result['recall']==.5 and result['acceptance_rate']==.5

def test_generation_marks_empty_action_list_attempted():
    from agents.content_generation_agent import ContentGenerationAgent
    state={'course_id':'x','all_gaps':[AlignmentGap('g','objective_not_measurable','warning','Vague verb','clo',None,.2,'Review verb')]}
    result=ContentGenerationAgent().run(state)
    assert result['generation_attempted'] is True


def test_live_reviews_are_prefetched_concurrently_and_called_once_each():
    import json, threading
    from agents.live_review import DIMENSIONS, augment, prefetch
    calls = []
    class Agent:
        def _retrieve(self, *a, **k): return [RetrievedChunk('real', 'Real source excerpt', .8, 'a', 'slides', 'c', 1, None, None, None)]
        def _invoke(self, *a, **k):
            calls.append(threading.current_thread().name)
            return json.dumps({'findings': [], 'limitations': 'None found'}), 5
        def _parse_json(self, text): return json.loads(text)
    state = {'run_id': 'r1', 'course_id': 'c', 'modules': [], 'course_metadata': {'title': 'T'},
             'alignment_results': {d: AlignmentResult('a', d, .9, 'pass') for d in DIMENSIONS}}
    prefetch(Agent(), state); prefetch(Agent(), state)   # second call must not resubmit
    for d in DIMENSIONS: out = augment(Agent(), state, d)
    assert len(calls) == len(DIMENSIONS) and all(n.startswith('live-review') for n in calls)
    assert out['total_tokens'] == 5


def test_confirmations_are_not_gaps_and_fixable_findings_get_draftable_gap_types():
    import json
    from agents.live_review import DIMENSIONS, augment
    finding = lambda title, fixable: {'title': title, 'description': 'Described in detail here', 'severity': 'warning', 'rationale': 'Because',
        'correction': 'Add one', 'evidence_ids': ['real'], 'evidence_strength': 'moderate', 'fixable_by': fixable}
    class Agent:
        def _retrieve(self, *a, **k): return [RetrievedChunk('real', 'Real source excerpt', .8, 'a', 'slides', 'c', 1, None, None, None)]
        def _invoke(self, *a, **k):
            return json.dumps({'findings': [finding('No objective covers graphs', 'objective'), finding('Exam items unmapped', 'assessment'),
                finding('Schedule unclear', 'none')], 'confirmed': ['Binary search objective is supported by the slides'],
                'limitations': 'x'}), 7
        def _parse_json(self, text): return json.loads(text)
    state = {'course_id': 'c', 'modules': [], 'course_metadata': {'title': 'T'},
             'alignment_results': {d: AlignmentResult('a', d, .9, 'pass') for d in DIMENSIONS}}
    augment(Agent(), state, 'metadata_content')
    result = state['alignment_results']['metadata_content']
    assert [g.gap_type for g in result.gaps] == ['live_missing_objective', 'live_missing_assessment', 'live_alignment_review']
    assert result.findings['live_review']['confirmed'] == ['Binary search objective is supported by the slides']
    assert not any('supported' in g.description for g in result.gaps)


def test_an_audit_still_completes_when_debug_turns_on_sql_echo(client, headers, monkeypatch):
    """DEBUG=true turns on SQL echo, which writes every statement to stdout. The audit worker's stdout must still hold
    only its JSON result; before the fix every audit in that configuration failed with 'Extra data'."""
    import time
    monkeypatch.setenv("DEBUG", "true")                                      # inherited by the worker subprocess
    course = client.post("/api/v1/courses", headers=headers, json={"code": "ECHO-DEBUG", "title": "Sorting"}).json()["id"]
    base = f"/api/v1/courses/{course}"
    r = client.post(base + "/artifacts", headers=headers, data={"artifact_type": "slides"},
                    files={"file": ("lecture.txt", b"Merge sort splits the list and merges the sorted halves in n log n time.", "text/plain")})
    assert r.status_code == 201, r.text
    run = client.post(base + "/run-audit", headers=headers).json()["run_id"]
    for _ in range(600):
        state = client.get(f"/api/v1/runs/{run}", headers=headers).json()
        if state["status"] != "running":
            break
        time.sleep(.1)
    assert state["status"] in ("completed", "needs_review", "waiting_for_human"), state
    assert "Extra data" not in (state["error_message"] or "")


def test_drafts_without_supporting_material_are_reported_as_such_not_as_a_provider_error(client, headers):
    """A course without any teaching material: findings exist, but no draft can be grounded in a passage.
    The run must say that, instead of sending the lecturer to check an API key."""
    import time
    from test_multilingual_model import _upload
    course = client.post("/api/v1/courses", headers=headers, json={"code": "DE-NOEVIDENCE", "title": "Algorithmen"}).json()["id"]
    base = f"/api/v1/courses/{course}"
    for name, kind, mime in [("modulhandbuch.md", "syllabus", "text/markdown"), ("klausur.txt", "exam", "text/plain")]:
        _upload(client, headers, base, "de_algorithmen", name, kind, mime)
    run = client.post(base + "/run-audit", headers=headers).json()["run_id"]
    for _ in range(600):
        state = client.get(f"/api/v1/runs/{run}", headers=headers).json()
        if state["status"] != "running":
            break
        time.sleep(.1)
    assert state["status"] == "needs_review", state
    assert "no supporting passage was found" in state["error_message"] and "API key" not in state["error_message"]


# ── drafts aimed at the objective, in the course's language ──────────────────

def test_the_course_language_is_read_from_the_stated_objectives():
    from knowledge import language
    assert language.detect(["Die Studierenden können die binäre Suche erklären.", "Sie beherrschen die Grundlagen neuronaler Netze."]) == "de"
    assert language.detect(["Students will be able to explain binary search.", "They compare sorting algorithms."]) == "en"
    assert language.detect(["Transformer, BERT, GPT"]) is None                                # too little to tell
    assert "German" in language.instruction("de") and "English" in language.instruction("en")
    assert language.instruction(None, "the language of the purpose text") == "Write the draft in the language of the purpose text."


def _generation_state(objective_text, code="EXT-7", bloom="evaluate"):
    from agents.graph.state import AlignmentGap
    gap = AlignmentGap("gap-1", "clo_not_covered", "warning", f"{code} coverage score 0.36 is below threshold. Keyword coverage: 0%. Best semantic match: 0.61.",
                       "clo", "objective-1", 0.36, "Add teaching material.")
    state = {"course_id": "course-1", "run_id": "run-1", "course_metadata": {"title": "Deep Learning", "level": "graduate"},
             "modules": [{"clos": [{"id": "objective-1", "code": code, "text": objective_text, "bloom_level": bloom}]}]}
    return gap, state


def test_a_draft_for_an_uncovered_objective_is_built_and_searched_from_the_objective_in_its_language():
    """Found in the live runs: the prompt and the search held only "EXT-7 coverage score ...", so different findings got
    near-identical drafts; drafts for a German course came out in English."""
    from types import SimpleNamespace
    from agents.content_generation_agent import ContentGenerationAgent
    from knowledge import language
    objective = "Die Studierenden können Deep-Learning-Ansätze aus technischer, ethischer und betriebswirtschaftlicher Perspektive bewerten."
    gap, state = _generation_state(objective)
    calls = []
    agent = ContentGenerationAgent()
    agent._get_rag = lambda: SimpleNamespace(generate=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(content="Entwurf [SOURCE_1]", citations=[{"marker": "[SOURCE_1]"}], tokens_used=0))
    agent._language = language.instruction(language.detect([objective]))
    item, _ = agent._gen_clo(gap, "course-1", state, "")
    assert calls[0]["query"] == objective                                                      # searched for the objective itself
    assert objective in calls[0]["task_prompt"] and "EXT-7" in calls[0]["task_prompt"]
    assert "German" in calls[0]["extra_instructions"]
    assert "Upon completion" in calls[0]["task_prompt"]                                        # no language set on this agent yet: English frame
    agent._language_code = "de"
    agent._gen_clo(gap, "course-1", state, "")
    assert "Nach Abschluss des Moduls können die Studierenden" in calls[-1]["task_prompt"] and "Upon completion" not in calls[-1]["task_prompt"]
    calls[:] = calls[:1]
    assert item.title.startswith("Suggested CLO — EXT-7: Die Studierenden")
    question, _ = agent._gen_assessment_question(gap, "course-1", state, "")
    assert calls[1]["query"] == objective and "'EVALUATE' level" in calls[1]["task_prompt"]   # the objective's own level
    assert question.title.endswith("— EXT-7")


def test_topic_drafts_search_for_the_topic_and_unknown_objectives_fall_back_to_the_finding():
    from types import SimpleNamespace
    from agents.content_generation_agent import ContentGenerationAgent
    from agents.graph.state import AlignmentGap
    calls = []
    agent = ContentGenerationAgent()
    agent._get_rag = lambda: SimpleNamespace(generate=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(content="Draft [SOURCE_1]", citations=[], tokens_used=0))
    week = AlignmentGap("g2", "topic_not_delivered", "warning", "Week 5 topic 'Dynamic programming' has no corresponding slides or transcript content.",
                        "topic", None, 0.0, "Add material.")
    agent._gen_exercise(week, "course-1", {"modules": []}, "")
    assert calls[-1]["query"] == "Dynamic programming" and calls[-1]["where"]["artifact_type"]["$in"] == ["slides", "transcript", "reading", "other"]
    gap, state = _generation_state("Students can explain backpropagation.")
    gap.affected_entity_id = "not-in-this-course"
    agent._gen_clo(gap, "course-1", state, "")
    assert calls[-1]["query"] == gap.description and "extra_instructions" in calls[-1]      # no objective found: the finding, as before


def test_workbench_drafts_follow_the_language_of_the_request(client, headers, monkeypatch):
    from rag.generation.grounded_generator import GroundedGenerator
    seen = []
    original = GroundedGenerator.generate
    monkeypatch.setattr(GroundedGenerator, "generate", lambda self, task_prompt, context_chunks, extra_instructions=None:
                        seen.append(task_prompt) or original(self, task_prompt, context_chunks, extra_instructions))
    course = client.post("/api/v1/courses", headers=headers, json={"code": "LANG-DRAFT", "title": "Algorithmen"}).json()["id"]
    base = f"/api/v1/courses/{course}"
    assert client.post(base + "/artifacts", headers=headers, data={"artifact_type": "slides"},
                       files={"file": ("vorlesung.txt", "Die binäre Suche halbiert den Suchraum eines sortierten Arrays.".encode(), "text/plain")}).status_code == 201
    r = client.post(base + "/generate", headers=headers, json={"content_type": "exercise", "alternatives": 1,
                                                               "purpose": "Übung zur binären Suche für die Studierenden mit einer Aufgabe und der Lösung"})
    assert r.status_code == 201, r.text
    assert "Write the whole draft in German" in seen[-1]


def test_objective_drafts_rest_on_teaching_material_not_on_the_module_manual():
    from types import SimpleNamespace
    from agents.content_generation_agent import ContentGenerationAgent, TEACHING_ONLY
    calls = []
    agent = ContentGenerationAgent()
    agent._get_rag = lambda: SimpleNamespace(generate=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(content="Draft [SOURCE_1]", citations=[], tokens_used=0))
    gap, state = _generation_state("Students can explain backpropagation.")
    agent._gen_clo(gap, "course-1", state, "")
    agent._gen_assessment_question(gap, "course-1", state, "")
    assert calls[0]["where"] == TEACHING_ONLY == calls[1]["where"]
    assert "syllabus" not in str(TEACHING_ONLY) and "module_manual" not in str(TEACHING_ONLY)


# ── more drafts: one per distinct gap, merged across checks, written in parallel ──

def _gap(gid, gap_type, entity=None, description="d", severity="warning", score=0.3):
    from agents.graph.state import AlignmentGap
    return AlignmentGap(gid, gap_type, severity, description, "clo" if entity else "topic", entity, score, "r")


def test_findings_about_the_same_objective_get_one_draft_per_kind():
    from agents.content_generation_agent import plan_drafts
    gaps = [_gap("a1", "clo_not_covered", "obj-1", score=0.4), _gap("a2", "live_missing_objective", "obj-1", score=0.2),   # same objective, same kind: one CLO draft
            _gap("a3", "clo_not_assessed", "obj-1"),                                                                    # same objective, other kind: its own question draft
            _gap("b1", "topic_not_assessed", description="Topic 'Hash tables' has lecture content but no assessment questions."),
            _gap("b2", "topic_not_assessed", description="Topic 'hash tables' has lecture content but no assessment questions.", score=0.1),
            _gap("c1", "clo_not_covered", "obj-2", severity="critical", score=0.9)]
    planned = plan_drafts(gaps, 20)
    leads = {g.gap_id: merged for g, merged in planned}
    assert set(leads) == {"a2", "a3", "b2", "c1"}                                              # four drafts for six findings
    assert leads["a2"] == ["a1"] and leads["b2"] == ["b1"] and leads["a3"] == [] and leads["c1"] == []   # the lower score leads
    assert planned[0][0].gap_id == "c1"                                                         # critical first
    assert [g.gap_id for g, _ in plan_drafts(gaps, 2)] == ["c1", "b2"]                         # the cap still applies: critical, then the lowest score of another kind


def test_drafts_are_written_in_parallel_in_planned_order_each_with_its_own_model(monkeypatch):
    import threading
    import time
    from types import SimpleNamespace
    from config import settings
    from agents.content_generation_agent import ContentGenerationAgent
    monkeypatch.setattr(settings, "generation_concurrency", 4)
    monkeypatch.setattr(settings, "generation_max_items_per_run", 20)
    objectives = [{"id": f"obj-{i}", "code": f"EXT-{i}", "text": f"Students can explain topic number {i} in depth.", "bloom_level": "understand"} for i in range(8)]
    gaps = [_gap(f"g{i}", "clo_not_covered", f"obj-{i}", score=i / 10) for i in range(8)]
    seen, threads = [], set()

    def generate(**kwargs):
        threads.add(threading.get_ident())
        time.sleep(0.3)                                                                        # a model call
        seen.append(kwargs["model"])
        return SimpleNamespace(content=f"Upon completion of this module, students will be able to explain {kwargs['query']} in detail with an example. [SOURCE_1]",
                               citations=[{"marker": "[SOURCE_1]", "citation": "[Slides]"}], tokens_used=10)

    agent = ContentGenerationAgent()
    agent._get_rag = lambda: SimpleNamespace(generate=generate)
    agent._load_rejected = lambda course_id: set()
    state = {"course_id": "course-1", "run_id": "run-parallel", "course_metadata": {"title": "Algorithms"}, "all_gaps": gaps,
             "modules": [{"clos": objectives}], "error_log": [], "total_tokens": 0}
    started = time.monotonic()
    result = agent.run(state)
    elapsed = time.monotonic() - started
    items = result["generated_items"]
    assert len(items) == 8 and elapsed < 8 * 0.3 * 0.6 and len(threads) > 1                    # several at a time
    assert [i.source_gap_id for i in items] == ["g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7"]   # planned order (worst first)
    assert set(seen) == {settings.openrouter_model} and result["total_tokens"] == 80
