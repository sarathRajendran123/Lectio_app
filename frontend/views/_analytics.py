"""LECTIO — Analytics Page"""
import streamlit as st
import plotly.express as px
import pandas as pd
from utils.session_utils import get_client, safe_api_call
from components.ui_components import empty_state


def show_analytics():
    st.title("Analytics")
    client = get_client()

    courses_data, err = safe_api_call(client.list_courses)
    if err:
        st.error(err); return

    courses = (courses_data or {}).get("courses", [])
    if not courses:
        empty_state("No Data Yet", "Run alignment audits to see analytics."); return

    # ── Overview metrics ───────────────────────────────────────────────────
    st.markdown("### Platform Overview")
    cols = st.columns(4)
    cols[0].metric("Total Courses",   len(courses))

    total_artifacts = sum(c.get("artifact_count", 0) for c in courses)
    cols[1].metric("Total Artefacts", total_artifacts)

    pending_items, _ = safe_api_call(client.list_approvals, "pending")
    cols[2].metric("Pending Approvals", len(pending_items or []))

    approved_items, _ = safe_api_call(client.list_approvals, "approved")
    cols[3].metric("Approved Items", len(approved_items or []))

    st.divider()

    tab1, tab2, tab3 = st.tabs(["Alignment Scores", "Approval Stats", "Course Overview"])

    # ── TAB 1: Alignment Scores ────────────────────────────────────────────
    with tab1:
        _show_alignment_analytics(client, courses)

    # ── TAB 2: Approval Stats ──────────────────────────────────────────────
    with tab2:
        _show_approval_analytics(client)

    # ── TAB 3: Course Overview ─────────────────────────────────────────────
    with tab3:
        _show_course_table(courses)


def _show_alignment_analytics(client, courses):
    st.markdown("#### Alignment Scores Across Courses")

    all_scores = []
    for course in courses[:10]:  # cap to avoid too many API calls
        reports, _ = safe_api_call(client.list_reports, course["id"])
        if not reports:
            continue
        latest = {}
        for r in (reports or []):
            rt = r["report_type"]
            if rt not in latest or r["generated_at"] > latest[rt]["generated_at"]:
                latest[rt] = r
        for rt, r in latest.items():
            all_scores.append({
                "Course":      course["code"],
                "Check":       rt.replace("_", " ↔ ").replace("metadata", "Metadata")
                                  .replace("content", "Content").replace("assessment", "Assessment")
                                  .replace("delivery", "Delivery").title(),
                "Score":       r["overall_score"],
                "Status":      r["status"],
            })

    if not all_scores:
        empty_state("No Report Data", "Run audits to see alignment analytics.")
        return

    df = pd.DataFrame(all_scores)

    # Grouped bar chart
    fig = px.bar(
        df, x="Course", y="Score", color="Check", barmode="group",
        color_discrete_sequence=px.colors.qualitative.Set2,
        title="Latest Alignment Score per Course per Check",
        labels={"Score": "Score (0–1)"},
        height=400,
    )
    fig.add_hline(y=0.75, line_dash="dash", line_color="green",
                  annotation_text="Pass (0.75)")
    fig.add_hline(y=0.55, line_dash="dash", line_color="orange",
                  annotation_text="Warning (0.55)")
    fig.update_layout(yaxis_tickformat=".0%", margin=dict(t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    summary = df.groupby("Course")["Score"].mean().reset_index()
    summary.columns = ["Course", "Avg Score"]
    summary["Avg Score"] = summary["Avg Score"].map("{:.0%}".format)
    summary["Overall"] = summary["Avg Score"].apply(
        lambda s: "Pass" if float(s.strip("%")) / 100 >= 0.75
        else ("Warning" if float(s.strip("%")) / 100 >= 0.55 else "Fail")
    )
    st.dataframe(summary, use_container_width=True, hide_index=True)


def _show_approval_analytics(client):
    st.markdown("#### Approval Decision Breakdown")

    all_items = []
    for status in ["approved", "rejected", "revised", "pending"]:
        items, _ = safe_api_call(client.list_approvals, status)
        for item in (items or []):
            all_items.append({
                "status":       status,
                "content_type": item.get("content_type", "unknown"),
            })

    if not all_items:
        empty_state("No Approval Data", "Generated content will appear here after an audit.")
        return

    df = pd.DataFrame(all_items)

    col1, col2 = st.columns(2)

    with col1:
        status_counts = df["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        colour_map = {
            "approved": "#198754", "rejected": "#dc3545",
            "revised": "#ffc107", "pending": "#6c757d",
        }
        fig = px.pie(
            status_counts, names="Status", values="Count",
            color="Status", color_discrete_map=colour_map,
            title="Decisions by Status", hole=0.4,
        )
        fig.update_layout(height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        type_counts = df.groupby(["content_type", "status"]).size().reset_index(name="Count")
        fig2 = px.bar(
            type_counts, x="content_type", y="Count", color="status",
            barmode="stack",
            color_discrete_map=colour_map,
            title="Content Type Breakdown",
            labels={"content_type": "Type", "Count": "Items"},
        )
        fig2.update_layout(height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    # Approval rate metric
    total    = len(df)
    approved = len(df[df["status"] == "approved"])
    rate     = approved / total if total else 0
    st.metric("Overall Approval Rate", f"{rate:.0%}",
              help="Fraction of generated items approved without rejection")


def _show_course_table(courses):
    st.markdown("#### Course Summary")
    rows = []
    for c in courses:
        rows.append({
            "Code":       c["code"],
            "Title":      c["title"][:40],
            "Level":      (c.get("level") or "—").title(),
            "Credits":    c.get("credits") or "—",
            "Year":       c.get("year") or "—",
            "Artefacts":  c.get("artifact_count", 0),
            "Modules":    c.get("module_count", 0),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Artifact distribution
    if any(r["Artefacts"] > 0 for r in rows):
        fig = px.bar(
            df, x="Code", y="Artefacts",
            title="Artefacts per Course",
            color="Artefacts",
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=300, margin=dict(t=40, b=10),
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
