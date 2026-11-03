"""LECTIO — Frontend Session Utilities (lazy streamlit import for testability)"""
from api_client.lectio_client import LectioClient, APIError


def _st():
    import streamlit as st
    return st


def get_client() -> LectioClient:
    token = _st().session_state.get("access_token")
    return LectioClient(access_token=token)


def try_refresh() -> bool:
    st = _st()
    rt = st.session_state.get("refresh_token")
    if not rt:
        return False
    try:
        result = LectioClient().refresh(rt)
        st.session_state.access_token  = result["access_token"]
        st.session_state.refresh_token = result["refresh_token"]
        return True
    except Exception:
        return False


def require_auth():
    st = _st()
    if not st.session_state.get("access_token"):
        st.warning("Please log in.")
        st.stop()


def is_admin() -> bool:
    user = _st().session_state.get("user", {}) or {}
    return "admin" in user.get("roles", [])


def is_coordinator_or_above() -> bool:
    user  = _st().session_state.get("user", {}) or {}
    roles = user.get("roles", [])
    return any(r in roles for r in ["admin", "dept_head", "coordinator"])


def current_user() -> dict:
    return _st().session_state.get("user", {}) or {}


def safe_api_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), None
    except APIError as e:
        if e.status_code == 401:
            if try_refresh():
                try:
                    return fn(*args, **kwargs), None
                except APIError as e2:
                    return None, str(e2)
            else:
                st = _st()
                st.session_state.clear()
                st.rerun()
        return None, str(e)
    except Exception as e:
        return None, f"Connection error: {e}"


def logout():
    st = _st()
    try:
        token = st.session_state.get("refresh_token")
        if token:
            LectioClient().logout(token)
    except Exception:
        pass
    st.session_state.clear()
