"""LECTIO — Generated Content Page"""
import streamlit as st
from utils.session_utils import get_client, safe_api_call
from components.ui_components import (
    render_citations, empty_state, status_badge, BLOOM_COLOURS,
)

CONTENT_LABELS = {
    "clo":         "CLO",
    "quiz":        "Quiz",
    "exercise":    "Exercise",
    "assessment":  "Assessment",
    "description": "Description",
}

STATUS_FILTER_OPTS = ["all", "pending", "approved", "revised", "rejected"]


def show_generated_content():
    st.title("Generated Content")
    st.caption("AI-generated CLOs, quiz questions, exercises, and assessments — grounded in your course materials.")
    client = get_client()

    # ── Filters ───────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    courses_data, _ = safe_api_call(client.list_courses)
    courses          = (courses_data or {}).get("courses", [])
    course_opts      = {"All Courses": None}
    course_opts.update({f"{c['code']} — {c['title']}": c["id"] for c in courses})
    selected_course  = col1.selectbox("Course", list(course_opts.keys()))
    course_id        = course_opts[selected_course]

    status_filter = col2.selectbox("Status", STATUS_FILTER_OPTS)
    type_filter   = col3.selectbox("Type",
                                    ["all", "clo", "quiz", "exercise", "assessment"])

    # ── Load items ─────────────────────────────────────────────────────────
    if status_filter == "all":
        all_items = []
        for s in ["pending", "approved", "revised", "rejected"]:
            items, _ = safe_api_call(client.list_approvals, s, course_id)
            all_items.extend(items or [])
    else:
        all_items, err = safe_api_call(client.list_approvals, status_filter, course_id)
        if err:
            st.error(err); return
        all_items = all_items or []

    if type_filter != "all":
        all_items = [i for i in all_items if i.get("content_type") == type_filter]

    if not all_items:
        empty_state(
            "No Generated Content",
            "Run an alignment audit to generate grounded content suggestions.",
        )
        return

    # ── Summary bar ────────────────────────────────────────────────────────
    counts = {}
    for i in all_items:
        s = i.get("approval_status", "pending")
        counts[s] = counts.get(s, 0) + 1

    st.markdown(
        " &nbsp;|&nbsp; ".join(
            f"{status_badge(s)}: **{n}**" for s, n in counts.items()
        )
    )
    st.divider()

    # ── Content cards ──────────────────────────────────────────────────────
    for item in all_items:
        _render_content_card(item)


def _render_content_card(item: dict):
    ctype    = item.get("content_type", "other")
    type_label = CONTENT_LABELS.get(ctype, ctype.title())
    bloom    = item.get("bloom_level", "")
    conf     = item.get("confidence_score", 0)
    astatus  = item.get("approval_status", "pending")
    colour   = BLOOM_COLOURS.get(bloom, "#6B7280")

    # Colour-coded left border by Bloom level
    border_style = f"border-left: 4px solid {colour};"

    with st.container():
        st.markdown(
            f"""<div style="background:#F8FAFC; padding:1rem; border-radius:8px;
            {border_style} margin-bottom:0.5rem;">
            <span style="color:#6B7280; font-size:0.85rem; text-transform:uppercase; letter-spacing:0.05em;">{type_label}</span>
            <strong> {item.get('title','Untitled')}</strong>
            &nbsp;&nbsp;
            <span style="background:{colour}; color:white; padding:2px 8px;
            border-radius:12px; font-size:0.75rem;">{bloom.title() if bloom else ''}</span>
            &nbsp;
            <span style="color:#6B7280; font-size:0.85rem;">
            Confidence: {conf:.0%} &nbsp;|&nbsp; {status_badge(astatus)}
            </span>
            </div>""",
            unsafe_allow_html=True,
        )

        with st.expander("View full content & citations", expanded=False):
            st.markdown("**Content:**")
            st.markdown(
                f"""<div style="white-space:pre-wrap; font-size:0.9rem;
                padding:0.75rem; background:#fff; border-radius:6px;
                border:1px solid #E2E8F0;">
                {item.get("content","").replace("<","&lt;").replace(">","&gt;")}
                </div>""",
                unsafe_allow_html=True,
            )
            st.markdown("")
            render_citations(item.get("citations", []))
