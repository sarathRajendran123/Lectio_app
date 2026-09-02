"""
LECTIO — Frontend API Client
Full typed HTTP client for all backend REST endpoints.
"""

import os
from typing import Any, Optional
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
TIMEOUT     = 60.0


class APIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(f"[{status_code}] {detail}")


class LectioClient:
    def __init__(self, access_token: Optional[str] = None):
        self._base  = BACKEND_URL.rstrip("/")
        self._token = access_token

    def _headers(self, token: Optional[str] = None) -> dict:
        t = token or self._token
        h = {"Content-Type": "application/json"}
        if t:
            h["Authorization"] = f"Bearer {t}"
        return h

    def _check(self, r: httpx.Response) -> Any:
        if not r.is_success:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise APIError(r.status_code, str(detail))
        if r.status_code == 204:
            return {}
        return r.json()

    # ── Auth ──────────────────────────────────────────────────────────────
    def login(self, email: str, password: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(f"{self._base}/api/v1/auth/login",
                json={"email": email, "password": password}))

    def refresh(self, refresh_token: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(f"{self._base}/api/v1/auth/refresh",
                json={"refresh_token": refresh_token}))

    def logout(self, refresh_token: str) -> None:
        with httpx.Client(timeout=TIMEOUT) as c:
            c.post(f"{self._base}/api/v1/auth/logout",
                json={"refresh_token": refresh_token},
                headers=self._headers())

    def get_me(self) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/auth/me",
                headers=self._headers()))

    # ── Courses ───────────────────────────────────────────────────────────
    def list_courses(self, skip=0, limit=50) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/courses",
                params={"skip": skip, "limit": limit},
                headers=self._headers()))

    def get_course(self, course_id: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/courses/{course_id}",
                headers=self._headers()))

    def create_course(self, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(f"{self._base}/api/v1/courses",
                json=data, headers=self._headers()))

    def list_modules(self, course_id: str) -> list:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/courses/{course_id}/modules",
                headers=self._headers()))

    def create_module(self, course_id: str, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(f"{self._base}/api/v1/courses/{course_id}/modules",
                json=data, headers=self._headers()))

    def list_weeks(self, course_id: str, module_id: str) -> list:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(
                f"{self._base}/api/v1/courses/{course_id}/modules/{module_id}/weeks",
                headers=self._headers()))

    def create_week(self, course_id: str, module_id: str, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/courses/{course_id}/modules/{module_id}/weeks",
                json=data, headers=self._headers()))

    def list_topics(self, course_id: str, module_id: str, week_id: str) -> list:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(
                f"{self._base}/api/v1/courses/{course_id}/modules/{module_id}/weeks/{week_id}/topics",
                headers=self._headers()))

    def create_topic(self, course_id: str, module_id: str, week_id: str, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/courses/{course_id}/modules/{module_id}/weeks/{week_id}/topics",
                json=data, headers=self._headers()))

    def list_clos(self, course_id: str, module_id: str) -> list:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(
                f"{self._base}/api/v1/courses/{course_id}/modules/{module_id}/clos",
                headers=self._headers()))

    def create_clo(self, course_id: str, module_id: str, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/courses/{course_id}/modules/{module_id}/clos",
                json=data, headers=self._headers()))

    def list_assessments(self, course_id: str) -> list:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(
                f"{self._base}/api/v1/courses/{course_id}/assessments",
                headers=self._headers()))

    def create_assessment(self, course_id: str, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/courses/{course_id}/assessments",
                json=data, headers=self._headers()))

    # ── Artifacts ─────────────────────────────────────────────────────────
    def upload_artifact(self, course_id: str, file_bytes: bytes,
                        filename: str, artifact_type: str) -> dict:
        with httpx.Client(timeout=120.0) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/courses/{course_id}/artifacts",
                headers={"Authorization": f"Bearer {self._token}"},
                files={"file": (filename, file_bytes)},
                data={"artifact_type": artifact_type}))

    def list_artifacts(self, course_id: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(
                f"{self._base}/api/v1/courses/{course_id}/artifacts",
                headers=self._headers()))

    def get_artifact_status(self, course_id: str, artifact_id: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(
                f"{self._base}/api/v1/courses/{course_id}/artifacts/{artifact_id}/status",
                headers=self._headers()))

    def delete_artifact(self, course_id: str, artifact_id: str) -> None:
        with httpx.Client(timeout=TIMEOUT) as c:
            self._check(c.delete(
                f"{self._base}/api/v1/courses/{course_id}/artifacts/{artifact_id}",
                headers=self._headers()))

    # ── Agent Runs ────────────────────────────────────────────────────────
    def run_audit(self, course_id: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/courses/{course_id}/run-audit",
                headers=self._headers()))

    def get_run_status(self, run_id: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/runs/{run_id}",
                headers=self._headers()))

    def get_run_steps(self, run_id: str) -> list:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/runs/{run_id}/steps",
                headers=self._headers()))

    # ── Reports ───────────────────────────────────────────────────────────
    def list_reports(self, course_id: str) -> list:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(
                f"{self._base}/api/v1/courses/{course_id}/reports",
                headers=self._headers()))

    def get_report(self, report_id: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/reports/{report_id}",
                headers=self._headers()))

    def resolve_gap(self, report_id: str, gap_id: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/reports/{report_id}/gaps/{gap_id}/resolve",
                headers=self._headers()))

    # ── Approvals ─────────────────────────────────────────────────────────
    def list_approvals(self, status: str = "pending",
                       course_id: Optional[str] = None) -> list:
        params: dict = {"status": status}
        if course_id:
            params["course_id"] = course_id
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/approvals",
                params=params, headers=self._headers()))

    def approve(self, content_id: str, comment: str = "") -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/approvals/{content_id}/approve",
                json=comment or None, headers=self._headers()))

    def revise(self, content_id: str, revision: str, comment: str = "") -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/approvals/{content_id}/revise",
                json={"revision": revision, "comment": comment},
                headers=self._headers()))

    def reject(self, content_id: str, comment: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/approvals/{content_id}/reject",
                json=comment, headers=self._headers()))

    # ── Admin ─────────────────────────────────────────────────────────────
    def list_users(self, skip=0, limit=50) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/admin/users",
                params={"skip": skip, "limit": limit},
                headers=self._headers()))

    def create_user(self, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(f"{self._base}/api/v1/admin/users",
                json=data, headers=self._headers()))

    def update_user(self, user_id: str, data: dict) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.patch(
                f"{self._base}/api/v1/admin/users/{user_id}",
                json=data, headers=self._headers()))

    def deactivate_user(self, user_id: str) -> None:
        with httpx.Client(timeout=TIMEOUT) as c:
            self._check(c.delete(f"{self._base}/api/v1/admin/users/{user_id}",
                headers=self._headers()))

    def assign_role(self, user_id: str, role: str) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.post(
                f"{self._base}/api/v1/admin/users/{user_id}/roles",
                json={"role": role}, headers=self._headers()))

    def remove_role(self, user_id: str, role_name: str) -> None:
        with httpx.Client(timeout=TIMEOUT) as c:
            self._check(c.delete(
                f"{self._base}/api/v1/admin/users/{user_id}/roles/{role_name}",
                headers=self._headers()))

    def get_system_stats(self) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/admin/system-stats",
                headers=self._headers()))

    def list_audit_logs(self, skip=0, limit=100) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            return self._check(c.get(f"{self._base}/api/v1/admin/audit-logs",
                params={"skip": skip, "limit": limit},
                headers=self._headers()))

    # ── Health ────────────────────────────────────────────────────────────
    def health(self) -> dict:
        with httpx.Client(timeout=10.0) as c:
            return self._check(c.get(f"{self._base}/health"))
