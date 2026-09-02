"""LECTIO — Course Upload Page"""
import time
import streamlit as st
from utils.session_utils import get_client, safe_api_call, is_coordinator_or_above
from components.ui_components import status_badge, empty_state, confirm_action


ARTIFACT_TYPES = ["syllabus", "slides", "assignment", "transcript", "module_manual", "other"]
FILE_TYPES     = ["pdf", "docx", "pptx", "txt", "vtt"]


def show_upload():
    st.title("Upload Course Artefacts")
    client = get_client()

    # ── Course selector ────────────────────────────────────────────────────
    courses_data, err = safe_api_call(client.list_courses)
    if err:
        st.error(err); return

    courses = courses_data.get("courses", [])
    if not courses:
        if is_coordinator_or_above():
            _create_course_form(client)
        else:
            empty_state("No Courses Yet", "Ask your coordinator to create a course.")
        return

    course_options = {f"{c['code']} — {c['title']}": c["id"] for c in courses}

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_label = st.selectbox("Select Course", list(course_options.keys()))
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if is_coordinator_or_above() and st.button("New Course"):
            st.session_state["show_create_course"] = True

    if st.session_state.get("show_create_course"):
        _create_course_form(client)
        return

    course_id = course_options[selected_label]

    st.divider()
    tab1, tab2, tab3 = st.tabs(["Upload Files", "Uploaded Artefacts", "Run Audit"])

    # ── TAB 1: Upload ──────────────────────────────────────────────────────
    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            artifact_type = st.selectbox("Artefact Type", ARTIFACT_TYPES)
        with col2:
            uploaded = st.file_uploader(
                "Choose file", type=FILE_TYPES,
                help="PDF, DOCX, PPTX, TXT, or VTT (max 50 MB)",
            )

        if uploaded:
            st.info(f"**{uploaded.name}** — {uploaded.size:,} bytes")
            if st.button("Upload & Process", type="primary"):
                with st.spinner(f"Uploading {uploaded.name}…"):
                    result, err = safe_api_call(
                        client.upload_artifact,
                        course_id, uploaded.read(),
                        uploaded.name, artifact_type,
                    )
                if err:
                    st.error(f"Upload failed: {err}")
                else:
                    artifact_id = result["id"]
                    st.success(f"Uploaded! Processing started (ID: `{artifact_id[:8]}…`)")
                    _poll_processing(client, course_id, artifact_id)

    # ── TAB 2: Artefact list ───────────────────────────────────────────────
    with tab2:
        _show_artifacts(client, course_id)

    # ── TAB 3: Run audit ───────────────────────────────────────────────────
    with tab3:
        st.markdown("### Run Full Alignment Audit")
        st.info(
            "The audit analyses all uploaded artefacts, checks alignment across "
            "4 dimensions, and generates content to fill identified gaps."
        )
        if st.button("Start Audit", type="primary"):
            result, err = safe_api_call(client.run_audit, course_id)
            if err:
                st.error(err)
            else:
                run_id = result["run_id"]
                st.success(f"Audit started! Run ID: `{run_id[:8]}…`")
                st.session_state["active_run_id"] = run_id
                _poll_run(client, run_id)

        if st.session_state.get("active_run_id"):
            _poll_run(client, st.session_state["active_run_id"])

def _poll_processing(client, course_id, artifact_id):
    placeholder = st.empty()
    consecutive_errors = 0
    for _ in range(90):
        time.sleep(2)
        status_data, err = safe_api_call(
            client.get_artifact_status, course_id, artifact_id
        )
        if err:
            consecutive_errors += 1
            # Tolerate occasional network hiccups instead of dying silently
            # on the first one — but give up and tell the user after a few
            # in a row, rather than looping forever with no feedback.
            with placeholder.container():
                st.info(f"Checking status… (connection hiccup, retrying: {err})")
            if consecutive_errors >= 5:
                st.error(
                    f"Lost contact with the server while polling: {err}. "
                    "Check the **Uploaded Artefacts** tab — processing may "
                    "still be running in the background."
                )
                break
            continue
        consecutive_errors = 0
        s = status_data.get("processing_status", "pending")
        chunks = status_data.get("chunk_count", 0)
        with placeholder.container():
            st.info(f"Status: {status_badge(s)} | Chunks: {chunks}")
        if s in ("done", "error"):
            if s == "done":
                st.success(f"Processing complete — {chunks} chunks indexed.")
            else:
                st.error(f"Processing error: {status_data.get('processing_error','')}")
            break
    else:
        st.warning("Still processing — check the **Uploaded Artefacts** tab in a moment; this is taking longer than usual.")
        
def _poll_run(client, run_id):
    placeholder = st.empty()
    for _ in range(60):
        time.sleep(3)
        data, err = safe_api_call(client.get_run_status, run_id)
        if err:
            break
        s = data.get("status", "running")
        with placeholder.container():
            st.info(f"Run status: {status_badge(s)} | Tokens: {data.get('total_tokens', 0):,}")
        if s in ("completed", "failed", "waiting_for_human"):
            if s == "completed":
                st.success("Audit complete! Check Alignment Reports.")
            elif s == "waiting_for_human":
                st.warning("Audit complete — items awaiting your review in Approval Center.")
            else:
                st.error(f"Audit failed: {data.get('error_message','')}")
            break
        if _ == 59:
            st.warning("Audit is taking longer than expected. Check back in Alignment Reports.")


def _show_artifacts(client, course_id):
    data, err = safe_api_call(client.list_artifacts, course_id)
    if err:
        st.error(err); return

    artifacts = data.get("artifacts", []) if isinstance(data, dict) else data
    if not artifacts:
        empty_state("No Artefacts Yet", "Upload course files in the Upload tab.")
        return

    for a in artifacts:
        with st.expander(
            f"{status_badge(a['processing_status'])} "
            f"**{a['original_filename'] or a['filename']}** "
            f"| {a['artifact_type']} | {(a['file_size_bytes'] or 0) // 1024} KB",
            expanded=False,
        ):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Chunks", a.get("chunk_count", 0))
            col2.metric("Pages", a.get("page_count") or "—")
            col3.metric("Slides", a.get("slide_count") or "—")
            col4.metric("Words", a.get("word_count") or "—")
            if a.get("processing_error"):
                st.error(a["processing_error"])
            if confirm_action(
                key=f"del_{a['id']}",
                label="Delete",
                message=f"Permanently delete **{a['original_filename']}** and all its indexed chunks?",
            ):
                _, err = safe_api_call(client.delete_artifact, course_id, a["id"])
                if err:
                    st.error(err)
                else:
                    st.success("Deleted."); st.rerun()


def _create_course_form(client):
    st.markdown("### Create New Course")
    with st.form("create_course"):
        col1, col2 = st.columns(2)
        code     = col1.text_input("Course Code *", placeholder="CS301")
        title    = col2.text_input("Course Title *", placeholder="Data Structures")
        col3, col4, col5 = st.columns(3)
        level    = col3.selectbox("Level", ["undergraduate", "postgraduate"])
        year     = col4.number_input("Year", 2024, 2030, 2025)
        semester = col5.selectbox("Semester", ["S1", "S2", "Full Year"])
        credits  = st.number_input("Credits", 1, 120, 16)
        desc     = st.text_area("Description (optional)")
        submitted = st.form_submit_button("Create Course", type="primary")

    if submitted:
        if not code or not title:
            st.error("Course code and title are required.")
            return
        data = {"code": code, "title": title, "level": level,
                "year": year, "semester": semester, "credits": credits}
        if desc:
            data["description"] = desc
        result, err = safe_api_call(client.create_course, data)
        if err:
            st.error(err)
        else:
            st.success(f"Course **{result['code']}** created!")
            st.session_state.pop("show_create_course", None)
            st.rerun()
