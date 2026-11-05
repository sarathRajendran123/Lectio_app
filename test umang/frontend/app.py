"""LECTIO — Streamlit Application Entry Point"""
import streamlit as st

st.set_page_config(
    page_title="LECTIO",
    layout="wide", initial_sidebar_state="auto",
)

st.markdown("""
<style>
:root { --lectio-ink:#182B3A; --lectio-accent:#24695D; }
/* Larger type: Streamlit sizes most text in rem, so one root size scales body, labels, captions, tabs and buttons together */
html { font-size:112.5%; }
[data-testid="stSidebar"] { background:#EDF1EF; border-right:1px solid #DCE3DF; }
.block-container { padding-top:2.5rem; max-width:1440px; }
h1 { font-size:2.5rem !important; letter-spacing:-.045em; font-weight:650 !important; }
h2 { font-size:1.9rem !important; letter-spacing:-.025em; }
h3 { font-size:1.45rem !important; letter-spacing:-.025em; }
[data-testid="stCaptionContainer"], .stCaption { font-size:.95rem; line-height:1.5; }
[data-testid="stWidgetLabel"] p { font-size:1rem; }
[data-testid="stSidebar"] [role="radiogroup"] label p { font-size:1.02rem; }
[data-testid="stMetric"] { background:white; border:1px solid #DEE4E0; border-radius:12px; padding:20px; }
[data-testid="stMetricLabel"] { color:#526461; }
[data-testid="stMetricLabel"] p { font-size:1rem; white-space:normal; overflow:visible; text-overflow:clip; }
[data-testid="stMetricValue"] { font-size:2.4rem; }
.stButton > button,.stDownloadButton > button { border-radius:8px; min-height:42px; }
button:focus-visible,input:focus-visible,textarea:focus-visible { outline:3px solid #B87928 !important; outline-offset:3px; }
[data-testid="stExpander"] { background:white; border-radius:10px; }
[data-testid="stTabs"] [role="tab"] { padding:12px 20px; }
@media(min-width:701px) { [data-testid="stSidebar"] { min-width:270px; } }
@media(max-width:700px) { html { font-size:106%; } .block-container { padding:1rem; } h1 {font-size:1.8rem !important;} h2 {font-size:1.5rem !important;} }
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
        ("Documents & upload", "upload"),
        ("Course workbench", "workbench"),
        ("Course Structure",  "structure"),
        ("Knowledge Graph",   "knowledge_graph"),
        ("Alignment Reports", "reports"),
        ("Generated Content", "generated"),
        ("Approval Center",   "approvals"),
        ("Analytics",         "analytics"),
        ("System status", "system"),
    ]
    if any(r in roles for r in ["admin","dept_head"]):
        PAGES.append(("Admin Panel","admin"))

    page_keys = {p[0]: p[1] for p in PAGES}
    if "nav_selection" not in st.session_state:
        st.session_state["nav_selection"] = list(page_keys)[0]
    if "nav_redirect" in st.session_state:
        st.session_state["nav_selection"] = st.session_state.pop("nav_redirect")
    selected  = st.radio("Navigation", list(page_keys), label_visibility="collapsed", key="nav_selection")
    page_key  = page_keys[selected]
    st.divider()
    if st.button("Logout", width="stretch"):
        from utils.session_utils import logout
        logout(); st.rerun()


def _show_dashboard():
    from utils.session_utils import get_client, safe_api_call
    from components.ui_components import empty_state
    st.caption("LECTIO / ACADEMIC QUALITY WORKSPACE")
    st.title("Your courses, in alignment")
    st.write(f"Welcome, {user.get('full_name','User')}. Review evidence, surface gaps, and refine your teaching materials.")
    client = get_client()

    stats,err = safe_api_call(client.workbench,'dashboard')
    if err: st.error(err)
    if stats:
        columns=st.columns(3)
        labels={'courses':'Courses','documents_processed':'Documents processed','audits_completed':'Audits finished','pending':'Awaiting review','approved':'Approved drafts','rejected':'Rejected drafts'}
        for index,(key,label) in enumerate(labels.items()):columns[index%3].metric(label,stats[key])
    courses_data,_ = safe_api_call(client.list_courses)
    courses=(courses_data or {}).get('courses',[])
    pending,_ = safe_api_call(client.list_approvals,'pending')

    st.divider()
    col_l, col_r = st.columns([2,1])

    with col_l:
        st.markdown("#### Recent Courses")
        if not courses:
            empty_state("No Courses Yet","Go to **Upload Course** to get started.")
        for c in courses[:5]:
            a,b,cc = st.columns([3,1,2])
            a.markdown(f"**{c['code']}** — {c['title'][:40]}")
            b.caption(c.get("level","") or "")
            cc.caption(f"{c.get('artifact_count',0)} artefacts")
            st.divider()

    with col_r:
        st.markdown("#### Quick Actions")
        if st.button("Upload Artefact", width="stretch"):
            st.session_state["nav_redirect"] = "Documents & upload"
            st.rerun()
        if st.button("Run Audit", width="stretch"):
            st.session_state["nav_redirect"] = "Documents & upload"
            st.rerun()
        if pending:
            if st.button(f"Review {len(pending)} Items",
                          width="stretch", type="primary"):
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

elif page_key == "workbench":
    from views._workbench import show_workbench; show_workbench()
elif page_key == "system":
    from views._workbench import show_system; show_system()
