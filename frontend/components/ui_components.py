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
        st.success("No gaps found — alignment checks passed.")
        return

    import pandas as pd
    rows = []
    for g in gaps:
        rows.append({
            "Severity":    severity_badge(g.get("severity", "")),
            "Type":        g.get("gap_type", "").replace("_", " ").title(),
            "Description": g.get("description", "")[:120],
            "Score":       f"{g.get('score', 0):.0%}",
            "Resolved":    "Yes" if g.get("is_resolved") else "No",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ── Citation viewer ───────────────────────────────────────────────────────────

def render_citations(citations: list):
    """Render source citations as an expandable list."""
    if not citations:
        st.caption("No citations attached.")
        return
    with st.expander(f"{len(citations)} source citation(s)", expanded=False):
        for i, c in enumerate(citations, 1):
            st.markdown(
                f"**[SOURCE_{i}]** {c.get('citation', '')}  \n"
                f"<small>Artifact: {c.get('artifact_type','')}"
                f"{' · Page ' + str(c['page_number']) if c.get('page_number') else ''}"
                f"{' · Slide ' + str(c['slide_number']) if c.get('slide_number') else ''}"
                f"{' · Week ' + str(c['week_number']) if c.get('week_number') else ''}"
                f"</small>",
                unsafe_allow_html=True,
            )


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
