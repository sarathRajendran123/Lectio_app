"""Regression tests for defects that only appear on PostgreSQL.

The default suite runs on SQLite, which is lenient about column types and
lengths, so these classes of bug passed every test yet failed in Docker:

* generated_content.source_gap_id was VARCHAR in the ORM but UUID in the
  migration, so every generated-content INSERT was rejected by PostgreSQL.
* audit_logs.action is VARCHAR(100); deep URLs overflowed it and the audit
  entry was silently dropped.
* audit_logs.ip_address is INET; PostgreSQL returns ipaddress objects, which
  the response schema rejected (HTTP 500 on the Admin audit-log screen).

The first three tests always run. The schema-parity test needs a PostgreSQL
server that already has backend/db/migrations/versions/001_initial.sql applied:

    LECTIO_TEST_POSTGRES_DSN="host=127.0.0.1 port=5432 user=lectio_user \
        password=... dbname=lectio_db" pytest tests/test_postgres_regressions.py
"""
import ipaddress
import os
import uuid
from datetime import datetime, timezone

import pytest


def test_audit_action_is_templated_and_fits_the_column():
    from api.v1.middleware.audit_logger import _ACTION_MAX, _audit_action

    deep = (
        "/api/v1/courses/97b35a4f-70ef-4f60-bda8-74656f75dc27"
        "/modules/4998ab80-67c9-40ae-9d93-8694c2559970/clos"
    )
    action = _audit_action("POST", deep)
    assert action == "POST /api/v1/courses/{id}/modules/{id}/clos"
    assert len(action) <= _ACTION_MAX == 100
    # Pathological input must still be capped rather than overflow the column.
    assert len(_audit_action("DELETE", "/x/" + "a" * 500)) == 100


def test_audit_log_response_accepts_postgres_inet_objects():
    from schemas.admin import AuditLogResponse

    row = dict(
        id=uuid.uuid4(), user_id=None, action="POST /api/v1/auth/login",
        resource_type=None, resource_id=None, metadata=None,
        created_at=datetime.now(timezone.utc),
    )
    for ip in (ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1"), "10.0.0.5", None):
        parsed = AuditLogResponse(**row, ip_address=ip)
        assert parsed.ip_address == (None if ip is None else str(ip))


def test_gap_id_coercion_is_tolerant():
    from agents.stakeholder_agent import _as_uuid

    good = uuid.uuid4()
    assert _as_uuid(str(good)) == good
    assert _as_uuid(good) == good
    assert _as_uuid(None) is None
    assert _as_uuid("") is None
    assert _as_uuid("not-a-uuid") is None


def test_orm_column_types_match_the_postgres_migration():
    dsn = os.environ.get("LECTIO_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set LECTIO_TEST_POSTGRES_DSN to a database with 001_initial.sql applied")
    psycopg2 = pytest.importorskip("psycopg2")
    from sqlalchemy.dialects import postgresql

    import db.models  # noqa: F401  (registers every table)
    from db.base import Base

    def family(pg_type: str) -> str:
        t = pg_type.lower()
        for key in ("uuid", "inet", "jsonb", "timestamp"):
            if key in t:
                return key
        if "[]" in t or "array" in t:
            return "array"
        if t.startswith(("varchar", "character varying", "text", "string")):
            return "text"
        if t.startswith(("int", "bigint", "numeric", "float", "double", "real")):
            return "number"
        if "bool" in t:
            return "bool"
        return t

    def live_family(udt: str) -> str:
        if udt in ("uuid", "inet", "jsonb"):
            return udt
        if udt.startswith("timestamp"):
            return "timestamp"
        if udt.startswith("_"):
            return "array"
        if udt in ("varchar", "text", "bpchar"):
            return "text"
        if udt in ("int2", "int4", "int8", "numeric", "float4", "float8"):
            return "number"
        return "bool" if udt == "bool" else udt

    with psycopg2.connect(dsn) as con, con.cursor() as cur:
        cur.execute(
            "select table_name, column_name, udt_name, character_maximum_length "
            "from information_schema.columns where table_schema='public'"
        )
        live = {(t, c): (u, n) for t, c, u, n in cur.fetchall()}

    dialect = postgresql.dialect()
    problems = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            key = (table.name, col.name)
            if key not in live:
                continue  # tables/columns added by create_all are ORM-typed by construction
            udt, max_len = live[key]
            if family(col.type.compile(dialect=dialect)) != live_family(udt):
                problems.append(f"{key}: ORM {col.type.compile(dialect=dialect)} vs DB {udt}")
            orm_len = getattr(col.type, "length", None)
            if orm_len and max_len and orm_len > max_len:
                problems.append(f"{key}: ORM allows {orm_len} chars but DB column holds {max_len}")
    assert not problems, "ORM and PostgreSQL schema disagree:\n" + "\n".join(problems)
