"""LECTIO — Approval Center Page"""
import streamlit as st
from utils.session_utils import get_client, safe_api_call
from components.ui_components import render_citations, bloom_chip, empty_state, status_badge

CONTENT_LABELS = {
    "clo": "CLO", "quiz": "Quiz", "exercise": "Exercise",
    "assessment": "Assessment", "description": "Description",
}


def show_approval_center():
    st.title("Approval Center")
    client = get_client()

    col1, col2, col3 = st.columns(3)
    status_filter  = col1.selectbox("Filter by Status",
                                    ["pending", "approved", "rejected", "revised"])
    courses_data, _ = safe_api_call(client.list_courses)
    courses          = (courses_data or {}).get("courses", [])
    course_opts      = {"All Courses": None}
    course_opts.update({f"{c['code']} — {c['title']}": c["id"] for c in courses})
    selected_course_label = col2.selectbox("Course", list(course_opts.keys()))
    course_filter    = course_opts[selected_course_label]

    if col3.button("Refresh"):
        st.rerun()

    items, err = safe_api_call(client.list_approvals, status_filter, course_filter)
    if err:
        st.error(err); return
    items = items or []

    if not items:
        empty_state(f"No {status_filter.title()} Items",
                    "All generated content will appear here for review."); return

    st.caption(f"Showing **{len(items)}** {status_filter} item(s)")
    st.divider()

    for item in items:
        _render_approval_card(client, item, status_filter)


def _render_approval_card(client, item: dict, status_filter: str):
    type_label   = CONTENT_LABELS.get(item.get("content_type", ""), "")
    bloom        = item.get("bloom_level", "")
    confidence   = item.get("confidence_score", 0)
    content_id   = item["id"]

    header = (
        f"**{item.get('title','Untitled')}**  "
        f"&nbsp;`{type_label}`&nbsp;{bloom_chip(bloom)}&nbsp; "
        f"Confidence: `{confidence:.0%}`"
    )

    with st.expander(header, expanded=(status_filter == "pending")):
        # ── Content display ────────────────────────────────────────────────
        st.markdown("**Generated Content:**")
        st.markdown(
            f"""<div style="background:#f8f9fa; padding:1rem; border-radius:6px;
            border-left:4px solid #4F46E5; white-space:pre-wrap; font-size:0.9rem;">
            {item.get("content","").replace("<","&lt;").replace(">","&gt;")}
            </div>""",
            unsafe_allow_html=True,
        )

        render_citations(item.get("citations", []))

        if status_filter != "pending":
            st.caption(f"Status: {status_badge(item.get('approval_status',''))}")
            return

        # ── Action buttons ─────────────────────────────────────────────────
        st.divider()
        action_key = f"action_{content_id}"
        current    = st.session_state.get(action_key, "")

        btn_col1, btn_col2, btn_col3 = st.columns(3)
        if btn_col1.button("Approve", key=f"app_{content_id}", type="primary"):
            st.session_state[action_key] = "approve"
        if btn_col2.button("Edit & Approve", key=f"edit_{content_id}"):
            st.session_state[action_key] = "revise"
        if btn_col3.button("Reject", key=f"rej_{content_id}"):
            st.session_state[action_key] = "reject"

        # ── Inline forms ───────────────────────────────────────────────────
        if current == "approve":
            comment = st.text_input("Optional comment", key=f"cmt_app_{content_id}")
            if st.button("Confirm Approval", key=f"conf_app_{content_id}", type="primary"):
                _, err = safe_api_call(client.approve, content_id, comment)
                if err:
                    st.error(err)
                else:
                    st.success("Approved and recorded.")
                    st.session_state.pop(action_key, None)
                    st.rerun()

        elif current == "revise":
            revision = st.text_area(
                "Edit content below then submit:",
                value=item.get("content", ""),
                key=f"rev_txt_{content_id}",
                height=200,
            )
            comment = st.text_input("Revision reason (optional)", key=f"cmt_rev_{content_id}")
            if st.button("Submit Revision", key=f"conf_rev_{content_id}", type="primary"):
                if not revision.strip():
                    st.warning("Revision text cannot be empty.")
                else:
                    _, err = safe_api_call(client.revise, content_id, revision, comment)
                    if err:
                        st.error(err)
                    else:
                        st.success("Revision submitted.")
                        st.session_state.pop(action_key, None)
                        st.rerun()

        elif current == "reject":
            reason = st.text_input("Rejection reason (required):", key=f"rej_rsn_{content_id}")
            if st.button("Confirm Rejection", key=f"conf_rej_{content_id}"):
                if not reason.strip():
                    st.warning("Please provide a rejection reason.")
                else:
                    _, err = safe_api_call(client.reject, content_id, reason)
                    if err:
                        st.error(err)
                    else:
                        st.error("Rejected and recorded.")
                        st.session_state.pop(action_key, None)
                        st.rerun()
