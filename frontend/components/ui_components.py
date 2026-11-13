"""
LECTIO — Shared UI Components
Reusable widgets used across multiple pages.
"""

import streamlit as st
from typing import Optional


BLOOM_COLOURS = {
    "remember":   "#6c757d",
    "understand": "#0d6efd",
    "apply":      "#198754",
    "analyse":    "#087990",   # darker than the usual cyan: white text needs 4.5:1
    "evaluate":   "#946200",   # darker than the usual amber: white text needs 4.5:1
    "create":     "#dc3545",
}


def status_badge(status: str) -> str:
    return status.replace('_', ' ').title()


def bloom_chip(level: Optional[str]) -> str:
    if not level:
        return ""
    return f"`{level.title()}`"


# ── Gap table ──────────────────────────────────────────────────────────────────

def severity_badge(severity: str) -> str:
    return severity.title()


def render_gap_table(gaps: list):
    """Render a list of alignment gaps as an interactive table."""
    if not gaps:
        st.info("No findings recorded. Check evidence sufficiency and report status before drawing conclusions.")
        return

    import pandas as pd
    rows = []
    for g in gaps:
        rows.append({
            "Severity":    severity_badge(g.get("severity", "")),
            "Type":        g.get("gap_type", "").replace("_", " ").title(),
            "Description": g.get("description", "")[:120],
            "Score":       f"{(g.get('score') or 0):.0%}",
            "Resolved":    "Yes" if g.get("is_resolved") else "No",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True)


# ── Citation viewer ───────────────────────────────────────────────────────────

def render_citations(citations: list):
    """Render source citations as an expandable list."""
    if not citations:
        st.caption("No citations attached.")
        return
    with st.container(border=True):
        st.caption(f"{len(citations)} source citation(s)")
        for c in citations:
            st.write(f"{c.get('marker','Source')} {c.get('citation','')}")
            st.caption(f"Document: {c.get('artifact_id','unknown')} · chunk: {c.get('chunk_id','unknown')}")
            if c.get('quote'): st.text(c['quote'])
            st.caption(c.get('verification','Source reference; verify relevance against the document.'))


def render_draft_feedback(result: dict):
    """Provisional check of unsaved text: level, objectives, findings with their uncertainty, source excerpts."""
    with st.container(border=True):
        st.caption("PROVISIONAL CHECK · " + result.get("notice", ""))
        bloom = result.get("bloom") or {}
        level = bloom.get("level") or "not recognised"
        st.write(f"Cognitive level read from the text: {level}" + (f" (verb: {bloom['verb']})" if bloom.get("verb") else "")
                 + (f" · intended: {bloom['intended']}" if bloom.get("intended") else ""))
        for objective in result.get("objectives", []):
            st.write(f"Objective addressed: {objective.get('code') or ''} {objective['text']}")
            st.caption(f"Level: {objective.get('bloom_level') or 'unknown'} · " + ("selected by you" if objective.get("selected") else "found by shared words"))
        findings = result.get("findings", [])
        if not findings:
            st.write("No provisional finding for this text.")
        for finding in findings:
            st.write(f"{finding['severity'].upper()}: {finding['message']}")
            st.caption("Uncertainty: " + finding["uncertainty"])
        for reason in result.get("not_checked", []):
            st.caption("Not checked: " + reason)
        for title, excerpts in (("Closest passages in the teaching material", result.get("evidence", [])),
                                ("Closest assessment tasks", result.get("assessment_evidence", []))):
            if excerpts:
                st.caption(title)
                for e in excerpts:
                    place = " · ".join(str(p) for p in (e.get("artifact_type"), f"page {e['page']}" if e.get("page") else None,
                                                         f"slide {e['slide']}" if e.get("slide") else None, f"search match {e['match']:.2f}") if p)
                    st.caption(place)
                    st.text(e["excerpt"])


# ── Empty state ───────────────────────────────────────────────────────────────

def empty_state(title: str, message: str):
    st.markdown(
        f"""
        <div style="text-align:center; padding:3rem; color:#526461;">
            <h3>{title}</h3>
            <p>{message}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Confirmation dialog (via session state) ───────────────────────────────────

def confirm_action(key: str, label: str, message: str) -> bool:
    """
    Two-click confirmation. First click shows warning; second click confirms.
    Returns True only on the confirming click.
    """
    confirm_key = f"confirm_{key}"
    if not st.session_state.get(confirm_key):
        if st.button(label, key=key):
            st.session_state[confirm_key] = True
            st.rerun()
        return False
    else:
        st.warning(message)
        col1, col2 = st.columns(2)
        if col1.button("Confirm", key=f"{key}_yes"):
            st.session_state[confirm_key] = False
            return True
        if col2.button("Cancel", key=f"{key}_no"):
            st.session_state[confirm_key] = False
            st.rerun()
        return False
