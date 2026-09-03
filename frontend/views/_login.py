"""LECTIO — Login Page"""
import streamlit as st
from api_client.lectio_client import LectioClient, APIError


def show_login():
    st.markdown("""
    <style>
    .login-box { max-width: 420px; margin: 4rem auto; }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("## LECTIO")
        st.markdown("**AI Course Curation Platform**")
        st.divider()

        with st.form("login_form"):
            email    = st.text_input("Email", placeholder="you@university.ac.za")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True, type="primary")

        if submitted:
            if not email or not password:
                st.error("Enter your email and password.")
                return
            with st.spinner("Authenticating…"):
                try:
                    client = LectioClient()
                    tokens = client.login(email, password)
                    st.session_state.access_token  = tokens["access_token"]
                    st.session_state.refresh_token = tokens["refresh_token"]
                    authed = LectioClient(access_token=tokens["access_token"])
                    st.session_state.user = authed.get_me()
                    st.rerun()
                except APIError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Cannot reach server: {e}")

        st.caption("Contact your administrator if you cannot log in.")
