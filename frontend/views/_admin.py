"""LECTIO — Admin Panel"""
import streamlit as st
import pandas as pd
from utils.session_utils import get_client, safe_api_call, is_admin
from components.ui_components import empty_state


def show_admin():
    st.title("Admin Panel")

    if not is_admin():
        st.error("This page requires the **Admin** role.")
        return

    client = get_client()
    tab1, tab2, tab3 = st.tabs(["Users", "Audit Logs", "System Stats"])

    with tab1:
        _show_users(client)

    with tab2:
        _show_audit_logs(client)

    with tab3:
        _show_system_stats(client)


# ── Users ─────────────────────────────────────────────────────────────────────

def _show_users(client):
    st.markdown("### User Management")

    with st.expander("Create New User", expanded=False):
        _create_user_form(client)

    users_data, err = safe_api_call(client.list_users)
    if err:
        st.error(err); return

    users = (users_data or {}).get("users", [])
    if not users:
        empty_state("No Users", "Create the first user above.")
        return

    # Filter bar
    col1, col2 = st.columns(2)
    search      = col1.text_input("Search by name or email", "")
    role_filter = col2.selectbox("Filter by role",
                                 ["All", "admin", "dept_head", "coordinator", "lecturer"])

    filtered = [
        u for u in users
        if (not search or search.lower() in u["email"].lower()
            or search.lower() in u["full_name"].lower())
        and (role_filter == "All" or role_filter in u["roles"])
    ]

    st.caption(f"Showing {len(filtered)} of {len(users)} users")

    for u in filtered:
        _render_user_row(client, u)


def _render_user_row(client, u: dict):
    role_tags = " ".join(f"`{r}`" for r in u["roles"])
    active    = "Active" if u["is_active"] else "Inactive"
    label     = f"[{active}] **{u['full_name']}** — {u['email']} | {role_tags}"

    with st.expander(label, expanded=False):
        col1, col2 = st.columns(2)
        col1.write(f"**Email:** {u['email']}")
        col1.write(f"**Roles:** {', '.join(u['roles']) or 'None'}")
        col1.write(f"**Active:** {'Yes' if u['is_active'] else 'No'}")
        col2.write(f"**Created:** {u['created_at'][:10]}")
        col2.write(f"**Last Login:** {u.get('last_login','Never')[:10] if u.get('last_login') else 'Never'}")

        st.markdown("**Actions:**")
        act1, act2, act3, act4 = st.columns(4)

        # Toggle active
        if act1.button(
            "Deactivate" if u["is_active"] else "Activate",
            key=f"toggle_{u['id']}"
        ):
            _, err = safe_api_call(client.update_user, u["id"],
                                   {"is_active": not u["is_active"]})
            if err:
                st.error(err)
            else:
                st.success("Updated."); st.rerun()

        # Assign role
        new_role = act2.selectbox("Assign role",
                                   ["—", "admin", "dept_head", "coordinator", "lecturer"],
                                   key=f"role_sel_{u['id']}")
        if act3.button("Assign", key=f"assign_{u['id']}") and new_role != "—":
            _, err = safe_api_call(client.assign_role, u["id"], new_role)
            if err:
                st.error(err)
            else:
                st.success(f"Role '{new_role}' assigned."); st.rerun()

        # Remove role
        if u["roles"]:
            remove_role = act4.selectbox("Remove role", ["—"] + u["roles"],
                                          key=f"rmrole_{u['id']}")
            if st.button("Remove", key=f"rm_{u['id']}") and remove_role != "—":
                _, err = safe_api_call(client.remove_role, u["id"], remove_role)
                if err:
                    st.error(err)
                else:
                    st.success(f"Role '{remove_role}' removed."); st.rerun()

        # Set a new password (also ends a lockout after five failed logins)
        with st.form(f"pw_form_{u['id']}", clear_on_submit=True):
            st.markdown("**Set a new password**")
            pc1, pc2 = st.columns(2)
            new_pw  = pc1.text_input("New password", type="password", key=f"pw_new_{u['id']}", help="At least 8 characters")
            new_pw2 = pc2.text_input("Repeat new password", type="password", key=f"pw_rep_{u['id']}")
            if st.form_submit_button("Set password"):
                problem = _password_problem(new_pw, new_pw2)
                if problem:
                    st.error(problem)
                else:
                    _, err = safe_api_call(client.update_user, u["id"], {"password": new_pw})
                    if err:
                        st.error(err)
                    else:
                        st.success(f"New password set for {u['email']}. Their open sessions were ended; "
                                   "a lockout from failed logins is lifted.")


def _password_problem(password: str, repeated: str):
    """Why a typed password cannot be used, in plain words; None when it is fine."""
    if len(password or "") < 8:
        return "The password needs at least 8 characters."
    if len(password.encode("utf-8")) > 72:
        return "The password is too long (at most 72 bytes)."
    if password != repeated:
        return "The two passwords do not match. Type the same password twice."
    if password != password.strip():
        return "The password starts or ends with a space. Remove it: spaces at the ends are easy to miss when logging in."
    return None


def _create_user_form(client):
    with st.form("create_user_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        email     = col1.text_input("Email *", placeholder="lecturer@uni.ac.za")
        full_name = col2.text_input("Full Name *", placeholder="Dr Jane Smith")
        col3, col4 = st.columns(2)
        password  = col3.text_input("Password *", type="password",
                                     help="Min 8 characters")
        repeated  = col4.text_input("Repeat password *", type="password")
        role      = st.selectbox("Initial Role",
                                    ["lecturer", "coordinator", "dept_head", "admin"])
        submitted = st.form_submit_button("Create User", type="primary")

    if submitted:
        email = (email or "").strip()
        if not email or not full_name or not password:
            st.error("Email, name, and password are required.")
            return
        problem = _password_problem(password, repeated)
        if problem:
            st.error(problem)
            return
        result, err = safe_api_call(client.create_user, {
            "email":     email,
            "full_name": full_name,
            "password":  password,
            "role":      role,
        })
        if err:
            st.error(err)
        else:
            # No rerun here: it would hide this message at once. The user list below is read after this form.
            st.success(f"User created with role `{role}`. They log in with the email **{result['email']}** "
                       "(stored in lower case) and the password you typed.")


# ── Audit Logs ────────────────────────────────────────────────────────────────

def _show_audit_logs(client):
    st.markdown("### Audit Logs")
    col1, col2 = st.columns(2)
    limit = col1.slider("Max entries", 10, 200, 50)
    if col2.button("Refresh"):
        st.rerun()

    logs_data, err = safe_api_call(client.list_audit_logs, skip=0, limit=limit)
    if err:
        st.error(err); return

    logs = (logs_data or {}).get("logs", [])
    if not logs:
        empty_state("No Audit Logs", "Logs appear after any data-changing action.")
        return

    rows = []
    for log in logs:
        rows.append({
            "Time":     log["created_at"][:19].replace("T", " "),
            "Action":   log["action"],
            "Resource": f"{log.get('resource_type','') or ''} {str(log.get('resource_id','') or '')[:8]}",
            "IP":       log.get("ip_address") or "—",
            "Status":   str((log.get("metadata") or {}).get("status_code", "—")),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch", hide_index=True,
                 column_config={
                     "Action": st.column_config.TextColumn(width="large"),
                     "Time":   st.column_config.TextColumn(width="medium"),
                 })


# ── System Stats ──────────────────────────────────────────────────────────────

def _show_system_stats(client):
    st.markdown("### System Statistics")

    stats, err = safe_api_call(client.get_system_stats)
    if err:
        st.error(err); return

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Users",            stats.get("total_users", 0))
    col2.metric("Courses",          stats.get("total_courses", 0))
    col3.metric("Artefacts",        stats.get("total_artifacts", 0))
    col4.metric("Agent Runs",       stats.get("total_runs", 0))
    col5.metric("Pending Approvals", stats.get("pending_approvals", 0))

    st.divider()
    st.markdown("### Backend Health")
    health, err = safe_api_call(client.health)
    if err:
        st.error(f"Backend unreachable: {err}")
    else:
        st.success(
            f"Backend healthy | App: **{health.get('app','')}** | "
            f"Version: **{health.get('version','')}** | "
            f"Env: **{health.get('env','')}**"
        )
