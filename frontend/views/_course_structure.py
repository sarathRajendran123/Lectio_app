"""LECTIO — Course Structure Page
Lets a coordinator build out a course's structured skeleton (Modules, Weeks,
Topics, Learning Objectives/CLOs, Assessments) — the data the alignment
audit actually checks uploaded content against. Without this, "Run Audit"
has nothing meaningful to compare files to.
"""
import streamlit as st
from utils.session_utils import get_client, safe_api_call, is_coordinator_or_above
from components.ui_components import bloom_chip, empty_state

BLOOM_LEVELS      = ["remember", "understand", "apply", "analyse", "evaluate", "create"]
ASSESSMENT_TYPES  = ["assignment", "quiz", "exam", "project", "practical"]


def show_course_structure():
    st.title("Course Structure")
    st.caption(
        "Add Modules, Weeks/Topics, Learning Objectives (CLOs), and Assessments here. "
        "The alignment audit compares your uploaded files against **this** data — "
        "without it, every check either fails immediately or passes trivially."
    )
    client = get_client()

    # ── Course selector (same pattern as Upload page) ───────────────────────
    courses_data, err = safe_api_call(client.list_courses)
    if err:
        st.error(err); return

    courses = courses_data.get("courses", [])
    if not courses:
        empty_state("No Courses Yet", "Create a course from the Upload page first.")
        return

    course_options = {f"{c['code']} — {c['title']}": c["id"] for c in courses}
    selected_label = st.selectbox("Select Course", list(course_options.keys()))
    course_id = course_options[selected_label]

    st.divider()

    can_edit = is_coordinator_or_above()
    if not can_edit:
        st.info("You have read-only access here. Ask a coordinator to make changes.")

    tab1, tab2, tab3, tab4 = st.tabs([
        "Modules", "Weeks & Topics", "Learning Objectives", "Assessments",
    ])

    with tab1:
        _show_modules(client, course_id, can_edit)
    with tab2:
        _show_weeks_and_topics(client, course_id, can_edit)
    with tab3:
        _show_clos(client, course_id, can_edit)
    with tab4:
        _show_assessments(client, course_id, can_edit)


# ── Modules ───────────────────────────────────────────────────────────────────

def _show_modules(client, course_id, can_edit):
    if can_edit:
        with st.expander("Add Module", expanded=False):
            with st.form("add_module_form"):
                title    = st.text_input("Title", placeholder="e.g. Introduction to Algorithms")
                seq      = st.number_input("Sequence number", min_value=1, step=1, value=1)
                credit   = st.number_input("Credit weight (optional, %)", min_value=0.0, max_value=100.0, value=0.0)
                desc     = st.text_area("Description (optional)")
                if st.form_submit_button("Add Module"):
                    if not title.strip():
                        st.error("Title is required.")
                    else:
                        data = {
                            "title": title.strip(),
                            "sequence_number": int(seq),
                            "description": desc.strip() or None,
                            "credit_weight": credit or None,
                        }
                        _, err = safe_api_call(client.create_module, course_id, data)
                        if err:
                            st.error(err)
                        else:
                            st.success("Module added.")
                            st.rerun()

    modules_data, err = safe_api_call(client.list_modules, course_id)
    if err:
        st.error(err); return

    if not modules_data:
        empty_state("No Modules Yet", "Add your first module above.")
        return

    for m in sorted(modules_data, key=lambda x: x["sequence_number"]):
        with st.expander(f"**{m['sequence_number']}. {m['title']}**"):
            if m.get("description"):
                st.write(m["description"])
            if m.get("credit_weight"):
                st.caption(f"Credit weight: {m['credit_weight']}%")


# ── Weeks & Topics ──────────────────────────────────────────────────────────────

def _show_weeks_and_topics(client, course_id, can_edit):
    modules_data, err = safe_api_call(client.list_modules, course_id)
    if err:
        st.error(err); return
    if not modules_data:
        empty_state("No Modules Yet", "Add a module in the Modules tab first.")
        return

    module_options = {f"{m['sequence_number']}. {m['title']}": m["id"] for m in modules_data}
    module_label = st.selectbox("Module", list(module_options.keys()), key="wt_module_select")
    module_id = module_options[module_label]

    if can_edit:
        with st.expander("Add Week", expanded=False):
            with st.form("add_week_form"):
                week_num = st.number_input("Week number", min_value=1, max_value=52, step=1, value=1)
                w_title  = st.text_input("Title (optional)", placeholder="e.g. Sorting Algorithms")
                theme    = st.text_input("Theme (optional)")
                if st.form_submit_button("Add Week"):
                    data = {
                        "week_number": int(week_num),
                        "title": w_title.strip() or None,
                        "theme": theme.strip() or None,
                    }
                    _, err = safe_api_call(client.create_week, course_id, module_id, data)
                    if err:
                        st.error(err)
                    else:
                        st.success("Week added.")
                        st.rerun()

    weeks_data, err = safe_api_call(client.list_weeks, course_id, module_id)
    if err:
        st.error(err); return
    if not weeks_data:
        empty_state("No Weeks Yet", "Add a week above for this module.")
        return

    for w in sorted(weeks_data, key=lambda x: x["week_number"]):
        label = f"Week {w['week_number']}" + (f" — {w['title']}" if w.get("title") else "")
        with st.expander(label):
            if w.get("theme"):
                st.caption(f"Theme: {w['theme']}")

            if can_edit:
                with st.form(f"add_topic_form_{w['id']}"):
                    t_title = st.text_input("Topic title", key=f"topic_title_{w['id']}")
                    t_desc  = st.text_area("Description (optional)", key=f"topic_desc_{w['id']}")
                    if st.form_submit_button("Add Topic"):
                        if not t_title.strip():
                            st.error("Topic title is required.")
                        else:
                            data = {"title": t_title.strip(), "description": t_desc.strip() or None}
                            _, err = safe_api_call(
                                client.create_topic, course_id, module_id, w["id"], data
                            )
                            if err:
                                st.error(err)
                            else:
                                st.success("Topic added.")
                                st.rerun()

            topics_data, terr = safe_api_call(client.list_topics, course_id, module_id, w["id"])
            if terr:
                st.error(terr)
            elif topics_data:
                for t in topics_data:
                    st.markdown(f"- {t['title']}")
            else:
                st.caption("No topics yet for this week.")


# ── Learning Objectives (CLOs) ─────────────────────────────────────────────────

def _show_clos(client, course_id, can_edit):
    modules_data, err = safe_api_call(client.list_modules, course_id)
    if err:
        st.error(err); return
    if not modules_data:
        empty_state("No Modules Yet", "Add a module in the Modules tab first.")
        return

    module_options = {f"{m['sequence_number']}. {m['title']}": m["id"] for m in modules_data}
    module_label = st.selectbox("Module", list(module_options.keys()), key="clo_module_select")
    module_id = module_options[module_label]

    if can_edit:
        with st.expander("Add Learning Objective", expanded=False):
            with st.form("add_clo_form"):
                code  = st.text_input("Code (optional)", placeholder="e.g. CLO1")
                text  = st.text_area(
                    "Objective text",
                    placeholder="Students will be able to implement and analyse sorting algorithms.",
                )
                bloom = st.selectbox("Bloom's Taxonomy level (optional)", ["(none)"] + BLOOM_LEVELS)
                if st.form_submit_button("Add CLO"):
                    if len(text.strip()) < 10:
                        st.error("Objective text must be at least 10 characters.")
                    else:
                        data = {
                            "code": code.strip() or None,
                            "text": text.strip(),
                            "bloom_level": None if bloom == "(none)" else bloom,
                        }
                        _, err = safe_api_call(client.create_clo, course_id, module_id, data)
                        if err:
                            st.error(err)
                        else:
                            st.success("Learning objective added.")
                            st.rerun()

    clos_data, err = safe_api_call(client.list_clos, course_id, module_id)
    if err:
        st.error(err); return
    if not clos_data:
        empty_state("No Learning Objectives Yet", "Add one above for this module.")
        return

    for clo in clos_data:
        cols = st.columns([5, 1])
        with cols[0]:
            label = f"**{clo['code']}** — {clo['text']}" if clo.get("code") else clo["text"]
            st.markdown(label)
        with cols[1]:
            if clo.get("bloom_level"):
                st.markdown(bloom_chip(clo["bloom_level"]))
        if clo.get("is_generated"):
            st.caption("AI-generated")
        st.divider()


# ── Assessments ───────────────────────────────────────────────────────────────

def _show_assessments(client, course_id, can_edit):
    if can_edit:
        with st.expander("Add Assessment", expanded=False):
            with st.form("add_assessment_form"):
                title   = st.text_input("Title", placeholder="e.g. Assignment 2 — Sorting")
                a_type  = st.selectbox("Type (optional)", ["(none)"] + ASSESSMENT_TYPES)
                weight  = st.number_input("Weight (%, optional)", min_value=0.0, max_value=100.0, value=0.0)
                marks   = st.number_input("Total marks (optional)", min_value=0.0, value=0.0)
                week    = st.number_input("Week due (optional)", min_value=0, max_value=52, value=0)
                desc    = st.text_area("Description (optional)")
                if st.form_submit_button("Add Assessment"):
                    if not title.strip():
                        st.error("Title is required.")
                    else:
                        data = {
                            "title": title.strip(),
                            "type": None if a_type == "(none)" else a_type,
                            "weight_percent": weight or None,
                            "total_marks": marks or None,
                            "week_due": int(week) or None,
                            "description": desc.strip() or None,
                        }
                        _, err = safe_api_call(client.create_assessment, course_id, data)
                        if err:
                            st.error(err)
                        else:
                            st.success("Assessment added.")
                            st.rerun()

    assessments_data, err = safe_api_call(client.list_assessments, course_id)
    if err:
        st.error(err); return
    if not assessments_data:
        empty_state("No Assessments Yet", "Add one above.")
        return

    for a in assessments_data:
        with st.expander(f"**{a['title']}**" + (f" ({a['type']})" if a.get("type") else "")):
            if a.get("weight_percent"):
                st.caption(f"Weight: {a['weight_percent']}%")
            if a.get("total_marks"):
                st.caption(f"Total marks: {a['total_marks']}")
            if a.get("week_due"):
                st.caption(f"Due: Week {a['week_due']}")
            if a.get("description"):
                st.write(a["description"])
