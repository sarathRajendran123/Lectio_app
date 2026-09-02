"""LECTIO — Alignment Reports Page"""
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
    by_run: dict = {}
    for r in reports:
        run_key = r["generated_at"][:10]
        by_run.setdefault(run_key, []).append(r)

    run_keys = sorted(by_run.keys(), reverse=True)
    selected_run = st.selectbox("Audit Run", run_keys,
                                format_func=lambda k: f"Run from {k} ({len(by_run[k])} checks)")
    run_reports  = by_run[selected_run]

    # ── Overall score cards ────────────────────────────────────────────────
    st.divider()
    cols = st.columns(4)
    report_map = {r["report_type"]: r for r in run_reports}

    for i, (rtype, label) in enumerate(REPORT_LABELS.items()):
        r = report_map.get(rtype)
        with cols[i]:
            if r:
                score = r["overall_score"]
                delta_c = "normal" if score >= 0.75 else ("off" if score >= 0.55 else "inverse")
                st.metric(label, f"{score:.0%}",
                          delta=r["status"].upper(), delta_color=delta_c)
            else:
                st.metric(label, "—", delta="not run", delta_color="off")

    # ── Radar chart ────────────────────────────────────────────────────────
    if len(run_reports) >= 2:
        _render_radar(run_reports)

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
    st.plotly_chart(fig, use_container_width=True)


def _render_report_detail(client, report_meta):
    report, err = safe_api_call(client.get_report, report_meta["id"])
    if err:
        st.error(err); return

    col1, col2, col3 = st.columns(3)
    col1.metric("Overall Score", f"{report['overall_score']:.0%}")
    col2.metric("Gaps Found",    report_meta.get("gap_count", len(report.get("gaps", []))))
    col3.metric("Status",        report["status"].upper())

    # ── Findings detail ────────────────────────────────────────────────────
    findings = report.get("findings", {})
    if "clo_scores" in findings:
        _render_clo_heatmap(findings["clo_scores"])
    if "assessment_scores" in findings:
        _render_assessment_table(findings["assessment_scores"])
    if "topic_coverage" in findings:
        _render_topic_coverage(findings["topic_coverage"])

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
    st.plotly_chart(fig, use_container_width=True)


def _render_assessment_table(assessment_scores: list):
    if not assessment_scores:
        return
    st.markdown("#### Assessment Coverage")
    df = pd.DataFrame([{
        "Assessment": a["title"],
        "Type":       a.get("type", "—").title(),
        "Coverage":   f"{a['score']:.0%}",
        "Status":     "Pass" if a["score"] >= 0.6 else "Fail",
    } for a in assessment_scores])
    st.dataframe(df, use_container_width=True, hide_index=True)


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
    st.plotly_chart(fig, use_container_width=True)
