"""LECTIO — Alignment Reports Page"""
from typing import List

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from utils.session_utils import get_client, safe_api_call
from components.ui_components import render_gap_table, empty_state


REPORT_LABELS = {
    "metadata_content":    "Metadata ↔ Content",
    "content_assessment":  "Content ↔ Assessment",
    "metadata_assessment": "Metadata ↔ Assessment",
    "content_delivery":    "Content ↔ Delivery",
}


def render_projection(client, course_id, compact=False):
    """Current heuristic score vs. projected score if approved drafts are adopted."""
    with st.spinner("Re-checking gaps against your approved drafts (first time after new approvals can take a few seconds)..."):
        data, err = safe_api_call(client.workbench, f"courses/{course_id}/projection")
    if err or not data or not data.get("dimensions"):
        return
    st.markdown("#### If your approved drafts are adopted")
    if not data["approved_drafts"]:
        st.caption("No approved drafts yet. Approve a suggested draft and this shows how far it would close the gaps, "
                   "without re-running the whole audit.")
        return
    st.caption(f"Projected from {data['approved_drafts']} approved draft(s). Only a full audit after you change the real "
               "course files gives a new audit score. Scores remain heuristic and require lecturer review.")
    cols = st.columns(4)
    for col, d in zip(cols, data["dimensions"]):
        label = REPORT_LABELS.get(d["report_type"], d["report_type"])
        if d["projected_score"] is None:
            col.metric(label, "Not assessable"); continue
        col.metric(label, f"{d['projected_score']:.0%}", delta=f"{d['delta']:+.0%} vs current {d['verified_score']:.0%}")
        col.caption(f"{len(d['addressed'])} of {d['gaps_total']} findings addressed")
    if compact:
        return
    for d in data["dimensions"]:
        if not (d["addressed"] or d["open"]):
            continue
        with st.expander(f"{REPORT_LABELS.get(d['report_type'], d['report_type'])}: addressed {len(d['addressed'])} / open {len(d['open'])}"):
            for a in d["addressed"]:
                st.success(f"**Addressed by:** {a['draft_title']}\n\n{a['description']}\n\n_{a['check']}_")
            for o in d["open"]:
                st.warning(f"{o['description']}\n\n_Still open: {o['reason']}_")


def show_reports():
    st.title("Alignment Reports")
    client = get_client()

    courses_data, err = safe_api_call(client.list_courses)
    if err:
        st.error(err); return

    courses = courses_data.get("courses", [])
    if not courses:
        empty_state("No Courses", "Create a course and run an audit first."); return

    course_options = {f"{c['code']} — {c['title']}": c["id"] for c in courses}
    selected_label = st.selectbox("Course", list(course_options.keys()))
    course_id      = course_options[selected_label]

    reports, err = safe_api_call(client.list_reports, course_id)
    if err:
        st.error(err); return
    if not reports:
        empty_state("No Reports Yet", "Run an alignment audit from the Upload page."); return

    # ── Report selector ────────────────────────────────────────────────────
    # Group by the actual run_id, NOT by calendar day. Grouping by day used
    # to silently merge every audit run from the same day into one bucket —
    # if you ran the audit twice today, you'd see 8 duplicated tabs instead
    # of 4, and (because report_map below is a dict keyed by report_type,
    # and reports arrive newest-first) the OLDER run's numbers would win and
    # keep showing even after a newer, fixed run completed.
    by_run: dict = {}
    run_order: List[str] = []   # preserve first-seen (= newest, since API returns desc) order
    for r in reports:
        run_key = r["run_id"]
        if run_key not in by_run:
            run_order.append(run_key)
        by_run.setdefault(run_key, []).append(r)

    def _run_label(k: str) -> str:
        reports_for_run = by_run[k]
        ts = reports_for_run[0]["generated_at"][:19].replace("T", " ")
        return f"Run at {ts} ({len(reports_for_run)} checks)"

    selected_run = st.selectbox("Audit Run", run_order, format_func=_run_label)
    run_reports  = by_run[selected_run]

    # ── Overall score cards ────────────────────────────────────────────────
    st.divider()
    st.caption('Scores are heuristic indicators based on retrieved evidence; they are not percentages of course quality or proof of missing content. Changes to documents, retrieval, or scoring can change the result.')
    cols = st.columns(4)
    report_map = {r["report_type"]: r for r in run_reports}

    for i, (rtype, label) in enumerate(REPORT_LABELS.items()):
        r = report_map.get(rtype)
        with cols[i]:
            if r:
                score = r["overall_score"]
                delta_c = "normal" if score >= 0.75 else ("off" if score >= 0.55 else "inverse")
                unscored = not has_statistics(r)
                # "Not assessable" does not fit the card's large value at normal widths, so it is the label below a dash
                st.metric(label, "—" if unscored else f"{score:.0%}",
                          delta=("NOT ASSESSABLE" if unscored else r["status"].upper().replace("_", " ")),
                          delta_color="off" if unscored else delta_c)
                st.caption(f"{r.get('gap_count') or 0} finding(s)")
                if unscored:
                    st.caption("No score, because: " + (r.get("reason") or "no reason was recorded."))
                elif r["status"] == "needs_review":
                    st.caption("Statistics shown, review needed: " + (r.get("reason") or "see the details below."))
                if r.get("model_review_error"):
                    st.warning("Model review unavailable: " + r["model_review_error"] + " Other checks are separate and should be interpreted with their stated limitations.")
            else:
                st.metric(label, "—", delta="not run", delta_color="off")

    render_projection(client, course_id)
    st.divider()

    # ── Radar chart ────────────────────────────────────────────────────────
    scored = [r for r in run_reports if has_statistics(r)]
    if len(scored) >= 2:
        _render_radar(scored)

    st.divider()

    # ── Detailed report tabs ───────────────────────────────────────────────
    tab_labels = [REPORT_LABELS.get(r["report_type"], r["report_type"]) for r in run_reports]
    tabs = st.tabs(tab_labels)

    for tab, report_meta in zip(tabs, run_reports):
        with tab:
            _render_report_detail(client, report_meta)


def _render_radar(reports):
    labels  = [REPORT_LABELS.get(r["report_type"], r["report_type"]) for r in reports]
    scores  = [r["overall_score"] for r in reports]
    labels += [labels[0]]
    scores += [scores[0]]

    fig = go.Figure(go.Scatterpolar(
        r=scores, theta=labels,
        fill="toself",
        line_color="#4F46E5",
        fillcolor="rgba(79,70,229,0.2)",
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 1], tickformat=".0%")),
        showlegend=False,
        title="Alignment Radar",
        height=350,
        margin=dict(t=50, b=20),
    )
    st.plotly_chart(fig, width="stretch")


def has_statistics(report: dict) -> bool:
    """The API says whether the check computed its numbers; older API versions only sent the status."""
    if "has_statistics" in report:
        return bool(report["has_statistics"])
    return report.get("status") not in ("needs_review", "failed")


def report_findings(report: dict) -> dict:
    """The agent's findings: a report stores the whole AlignmentResult, with its findings one level down."""
    outer = report.get("findings") or {}
    inner = outer.get("findings") if isinstance(outer, dict) else None
    return inner if isinstance(inner, dict) else (outer if isinstance(outer, dict) else {})


def _render_report_detail(client, report_meta):
    report, err = safe_api_call(client.get_report, report_meta["id"])
    if err:
        st.error(err); return

    col1, col2, col3 = st.columns(3)
    unscored = not has_statistics(report)
    col1.metric("Overall Score", "Not assessable" if unscored else f"{report['overall_score']:.0%}")
    col2.metric("Gaps Found",    report_meta.get("gap_count", len(report.get("gaps", []))))
    col3.metric("Status",        report["status"].upper())

    # ── Findings detail ────────────────────────────────────────────────────
    findings = report_findings(report)
    reason = report.get("reason") or report_meta.get("reason")
    if unscored:
        st.warning("Not assessable: " + (reason or "no reason was recorded."))
    elif report["status"] == "needs_review":
        st.warning("NEEDS REVIEW. The statistics below were computed, but: " + (reason or "the audit asked for a review of this check."))
    review = findings.get("live_review") if isinstance(findings.get("live_review"), dict) else {}
    if review.get("confirmed"):
        st.markdown("#### Confirmed by the model review")
        for point in review["confirmed"]:
            st.text("- " + str(point))
    if review.get("limitations"):
        st.caption("Model review limits: " + str(review["limitations"]))
    check = findings.get("delivery_verification")
    if isinstance(check, dict) and check.get("ran") is False and check.get("reason"):
        st.info("Transcript comparison not run: " + str(check["reason"]))
    if "clo_scores" in findings:
        _render_clo_heatmap(findings["clo_scores"])
    if "assessment_scores" in findings:
        _render_assessment_table(findings["assessment_scores"])
    if findings.get("uncovered_topics"):
        st.markdown("#### Taught topics without an assessment question")
        for topic in findings["uncovered_topics"]:
            st.text("- " + str(topic))
    if "topic_coverage" in findings:
        _render_topic_coverage(findings["topic_coverage"])
    for note in [findings.get("score_notice"), *(findings.get("limitations") or [])]:
        if note:
            st.caption(str(note))

    st.markdown("#### Identified Gaps")
    render_gap_table(report.get("gaps", []))

    recs = report.get("recommendations") or []
    if recs:
        st.markdown("#### Recommendations")
        for r in recs:
            st.info(r)


def _render_clo_heatmap(clo_scores: list):
    if not clo_scores:
        return
    st.markdown("#### CLO Coverage Scores")
    df = pd.DataFrame(clo_scores)
    if df.empty:
        return
    fig = px.bar(
        df, x="code", y="score", color="score",
        color_continuous_scale=["#dc3545","#ffc107","#198754"],
        range_color=[0, 1],
        labels={"code": "CLO", "score": "Coverage Score"},
        title="Coverage Score per CLO",
        height=300,
    )
    fig.add_hline(y=0.75, line_dash="dash", line_color="green",
                  annotation_text="Pass threshold")
    fig.add_hline(y=0.55, line_dash="dash", line_color="orange",
                  annotation_text="Warning threshold")
    fig.update_layout(margin=dict(t=40, b=10), coloraxis_showscale=False)
    st.plotly_chart(fig, width="stretch")


def _render_assessment_table(assessment_scores: list):
    if not assessment_scores:
        return
    st.markdown("#### Assessment Coverage")
    df = pd.DataFrame([{
        "Assessment": a["title"],
        "Type":       a.get("type", "—").title(),
        "Coverage":   f"{a['score']:.0%}",
        "Status":     (a.get("status") or ("pass" if a["score"] >= 0.6 else "fail")).upper(),
    } for a in assessment_scores])
    st.dataframe(df, width="stretch", hide_index=True)


def _render_topic_coverage(topics: list):
    if not topics:
        return
    st.markdown("#### Topic Delivery Coverage")
    delivered     = sum(1 for t in topics if t.get("delivered"))
    not_delivered = len(topics) - delivered
    fig = go.Figure(go.Pie(
        labels=["Delivered", "Not Delivered"],
        values=[delivered, not_delivered],
        hole=0.5,
        marker_colors=["#198754","#dc3545"],
    ))
    fig.update_layout(height=250, margin=dict(t=10, b=10), showlegend=True)
    st.plotly_chart(fig, width="stretch")
