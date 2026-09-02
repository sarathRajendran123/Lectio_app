"""LECTIO — Streamlit Application Entry Point"""
import streamlit as st

st.set_page_config(
    page_title="LECTIO",
    layout="wide", initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] { min-width: 220px; }
[data-testid="metric-container"] { background:#F8FAFC; border-radius:8px; padding:0.5rem; }
.block-container { padding-top:1.5rem; }
</style>
""", unsafe_allow_html=True)

for key, val in [("access_token",None),("refresh_token",None),("user",None)]:
    if key not in st.session_state:
        st.session_state[key] = val

if not st.session_state.access_token:
    from views._login import show_login
    show_login()
    st.stop()

user  = st.session_state.user or {}
roles = user.get("roles", [])

with st.sidebar:
    st.markdown("## LECTIO")
    st.caption(f"**{user.get('full_name','User')}**")
    st.caption(" ".join(f"`{r}`" for r in roles))
    st.divider()

    PAGES = [
        ("Dashboard",         "dashboard"),
        ("Upload Course",     "upload"),
        ("Course Structure",  "structure"),
        ("Knowledge Graph",   "knowledge_graph"),
        ("Alignment Reports", "reports"),
        ("Generated Content", "generated"),
        ("Approval Center",   "approvals"),
        ("Analytics",         "analytics"),
    ]
    if any(r in roles for r in ["admin","dept_head"]):
        PAGES.append(("Admin Panel","admin"))

    page_keys = {p[0]: p[1] for p in PAGES}
    if "nav_selection" not in st.session_state:
        st.session_state["nav_selection"] = list(page_keys)[0]
    if "nav_redirect" in st.session_state:
        st.session_state["nav_selection"] = st.session_state.pop("nav_redirect")
    selected  = st.radio("", list(page_keys), label_visibility="collapsed", key="nav_selection")
    page_key  = page_keys[selected]
    st.divider()
    if st.button("Logout", use_container_width=True):
        from utils.session_utils import logout
        logout(); st.rerun()


def _show_dashboard():
    from utils.session_utils import get_client, safe_api_call
    from components.ui_components import empty_state
    st.title(f"Welcome, {user.get('full_name','User')}")
    client = get_client()

    c1,c2,c3,c4 = st.columns(4)
    courses_data,_ = safe_api_call(client.list_courses)
    courses = (courses_data or {}).get("courses",[])
    c1.metric("My Courses", len(courses))
    c2.metric("Artefacts", sum(c.get("artifact_count",0) for c in courses))
    pending,_ = safe_api_call(client.list_approvals,"pending")
    c3.metric("Pending Reviews", len(pending or []),
              delta="Needs attention" if pending else None,
              delta_color="inverse" if pending else "off")
    approved,_ = safe_api_call(client.list_approvals,"approved")
    c4.metric("Approved Items", len(approved or []))

    st.divider()
    col_l, col_r = st.columns([2,1])

    with col_l:
        st.markdown("#### Recent Courses")
        if not courses:
            empty_state("No Courses Yet","Go to **Upload Course** to get started.")
        for c in courses[:5]:
            a,b,cc = st.columns([3,1,1])
            a.markdown(f"**{c['code']}** — {c['title'][:40]}")
            b.caption(c.get("level","") or "")
            cc.caption(f"{c.get('artifact_count',0)} artefacts")
            st.divider()

    with col_r:
        st.markdown("#### Quick Actions")
        if st.button("Upload Artefact", use_container_width=True):
            st.session_state["nav_redirect"] = "Upload Course"
            st.rerun()
        if st.button("Run Audit", use_container_width=True):
            st.session_state["nav_redirect"] = "Upload Course"
            st.rerun()
        if pending:
            if st.button(f"Review {len(pending)} Items",
                          use_container_width=True, type="primary"):
                st.session_state["nav_redirect"] = "Approval Center"
                st.rerun()
        st.markdown("#### Guide")
        st.markdown("1. **Upload** course artefacts\n2. **Run Audit** to analyse\n"
                    "3. **Review** in Approval Center\n4. **Check** reports")


if page_key == "dashboard":
    _show_dashboard()
elif page_key == "upload":
    from views._upload import show_upload; show_upload()
elif page_key == "structure":
    from views._course_structure import show_course_structure; show_course_structure()
elif page_key == "knowledge_graph":
    from views._knowledge_graph import show_knowledge_graph; show_knowledge_graph()
elif page_key == "reports":
    from views._alignment_reports import show_reports; show_reports()
elif page_key == "generated":
   from views._generated_content import show_generated_content; show_generated_content()
elif page_key == "approvals":
    from views._approval_center import show_approval_center; show_approval_center()
elif page_key == "analytics":
    from views._analytics import show_analytics; show_analytics()
elif page_key == "admin":
    from views._admin import show_admin; show_admin()
