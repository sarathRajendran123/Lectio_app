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
    "analyse":    "#0dcaf0",
    "evaluate":   "#ffc107",
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


# ── Empty state ───────────────────────────────────────────────────────────────

def empty_state(title: str, message: str):
    st.markdown(
        f"""
        <div style="text-align:center; padding:3rem; color:#6c757d;">
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
