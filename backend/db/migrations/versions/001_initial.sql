-- ═══════════════════════════════════════════════════════════════════════
--  LECTIO — Initial Database Schema
--  Migration: 001_initial
--  PostgreSQL 15
-- ═══════════════════════════════════════════════════════════════════════

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search on names

-- ═══════════════════════════════════════════════════════════════════════
-- DEPARTMENTS
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS departments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    code        VARCHAR(20)  UNIQUE NOT NULL,
    faculty     VARCHAR(255),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════════════════════════
-- USERS & AUTH
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS users (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email                   VARCHAR(255) UNIQUE NOT NULL,
    hashed_password         VARCHAR(255) NOT NULL,
    full_name               VARCHAR(255) NOT NULL,
    is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
    is_verified             BOOLEAN      NOT NULL DEFAULT FALSE,
    department_id           UUID         REFERENCES departments(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login              TIMESTAMPTZ,
    failed_login_attempts   INTEGER      NOT NULL DEFAULT 0,
    locked_until            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email        ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_department   ON users(department_id);

CREATE TABLE IF NOT EXISTS roles (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id     UUID REFERENCES roles(id) ON DELETE CASCADE,
    granted_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      VARCHAR(64) NOT NULL,   -- SHA-256 of the actual opaque token
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    revoke_reason   VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id    ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);

-- ═══════════════════════════════════════════════════════════════════════
-- COURSES & KNOWLEDGE MODEL
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS courses (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(50) UNIQUE NOT NULL,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    credits         INTEGER,
    level           VARCHAR(20),         -- 'undergraduate' | 'postgraduate'
    nqf_level       INTEGER,
    department_id   UUID        REFERENCES departments(id) ON DELETE SET NULL,
    coordinator_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    year            INTEGER,
    semester        VARCHAR(20),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_courses_department   ON courses(department_id);
CREATE INDEX IF NOT EXISTS idx_courses_coordinator  ON courses(coordinator_id);

CREATE TABLE IF NOT EXISTS course_lecturers (
    course_id   UUID REFERENCES courses(id) ON DELETE CASCADE,
    user_id     UUID REFERENCES users(id)   ON DELETE CASCADE,
    role        VARCHAR(50) NOT NULL DEFAULT 'lecturer',
    PRIMARY KEY (course_id, user_id)
);

CREATE TABLE IF NOT EXISTS modules (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id       UUID        NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    sequence_number INTEGER     NOT NULL,
    credit_weight   DECIMAL(5,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_modules_course ON modules(course_id);

CREATE TABLE IF NOT EXISTS weeks (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id   UUID        NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    week_number INTEGER     NOT NULL,
    title       VARCHAR(500),
    theme       TEXT,
    UNIQUE(module_id, week_number)
);

CREATE TABLE IF NOT EXISTS topics (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    week_id         UUID        NOT NULL REFERENCES weeks(id) ON DELETE CASCADE,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    sequence_order  INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subtopics (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id        UUID        NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    sequence_order  INTEGER
);

CREATE TABLE IF NOT EXISTS learning_objectives (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id           UUID        NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    text                TEXT        NOT NULL,
    code                VARCHAR(50),            -- e.g. CLO1, CLO2
    bloom_level         VARCHAR(50),            -- remember|understand|apply|analyse|evaluate|create
    bloom_verb          VARCHAR(100),
    source_document_id  UUID,                   -- FK to course_artifacts (set later)
    is_generated        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learning_objectives_module ON learning_objectives(module_id);

CREATE TABLE IF NOT EXISTS assessments (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id           UUID        NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title               VARCHAR(500) NOT NULL,
    type                VARCHAR(50),            -- assignment|quiz|exam|project|practical
    weight_percent      DECIMAL(5,2),
    total_marks         DECIMAL(10,2),
    week_due            INTEGER,
    submission_format   VARCHAR(100),
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assessment_questions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id   UUID        NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    text            TEXT        NOT NULL,
    bloom_level     VARCHAR(50),
    marks           DECIMAL(10,2),
    topic_id        UUID        REFERENCES topics(id) ON DELETE SET NULL,
    question_type   VARCHAR(50) -- mcq|short_answer|essay|practical
);

CREATE TABLE IF NOT EXISTS rubrics (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id   UUID        NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    title           VARCHAR(500),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rubric_criteria (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rubric_id       UUID        NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
    criterion_text  TEXT        NOT NULL,
    weight_percent  DECIMAL(5,2),
    clo_id          UUID        REFERENCES learning_objectives(id) ON DELETE SET NULL
);

-- ═══════════════════════════════════════════════════════════════════════
-- COURSE ARTEFACTS & CHUNKS (RAG)
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS course_artifacts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id           UUID        NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    uploaded_by         UUID        REFERENCES users(id) ON DELETE SET NULL,
    filename            VARCHAR(500) NOT NULL,
    original_filename   VARCHAR(500),
    file_type           VARCHAR(50)  NOT NULL,   -- pdf|docx|pptx|txt|vtt
    artifact_type       VARCHAR(100),            -- syllabus|slides|assignment|transcript|manual
    file_size_bytes     BIGINT,
    storage_path        VARCHAR(1000),
    processing_status   VARCHAR(50)  NOT NULL DEFAULT 'pending',  -- pending|processing|done|error
    processing_error    TEXT,
    page_count          INTEGER,
    slide_count         INTEGER,
    word_count          INTEGER,
    checksum            VARCHAR(64),
    uploaded_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    processed_at        TIMESTAMPTZ,
    metadata            JSONB        NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_artifacts_course     ON course_artifacts(course_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_status     ON course_artifacts(processing_status);

-- Add FK from learning_objectives to course_artifacts (now that table exists)
ALTER TABLE learning_objectives
    ADD CONSTRAINT fk_lo_source_doc
    FOREIGN KEY (source_document_id) REFERENCES course_artifacts(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS chunks (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id         UUID        NOT NULL REFERENCES course_artifacts(id) ON DELETE CASCADE,
    course_id           UUID        NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    text                TEXT        NOT NULL,
    token_count         INTEGER,
    char_count          INTEGER,
    chunk_index         INTEGER,
    page_number         INTEGER,
    slide_number        INTEGER,
    section_title       VARCHAR(500),
    week_number         INTEGER,
    document_position   DECIMAL(5,4),
    chroma_id           VARCHAR(255),            -- ID stored in ChromaDB
    embedding_model     VARCHAR(100),
    embedded_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    metadata            JSONB        NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_chunks_artifact  ON chunks(artifact_id);
CREATE INDEX IF NOT EXISTS idx_chunks_course    ON chunks(course_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chroma_id ON chunks(chroma_id);

-- ═══════════════════════════════════════════════════════════════════════
-- AGENT RUNS & MEMORY
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS agent_runs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id           UUID        NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    initiated_by        UUID        REFERENCES users(id) ON DELETE SET NULL,
    workflow_type       VARCHAR(100) NOT NULL,   -- full_audit|alignment_only|generation_only
    status              VARCHAR(50)  NOT NULL DEFAULT 'running',
    langgraph_run_id    VARCHAR(255),
    langsmith_run_id    VARCHAR(255),
    workflow_state      JSONB,
    error_message       TEXT,
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    total_tokens_used   INTEGER,
    total_cost_usd      DECIMAL(10,6)
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_course  ON agent_runs(course_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status  ON agent_runs(status);

CREATE TABLE IF NOT EXISTS agent_steps (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID        NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    agent_name          VARCHAR(100) NOT NULL,
    step_type           VARCHAR(100),
    input_summary       TEXT,
    output_summary      TEXT,
    tokens_used         INTEGER,
    duration_ms         INTEGER,
    status              VARCHAR(50),
    error_message       TEXT,
    langsmith_span_id   VARCHAR(255),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON agent_steps(run_id);

CREATE TABLE IF NOT EXISTS agent_memory (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_type     VARCHAR(100) NOT NULL,
    user_id         UUID        REFERENCES users(id) ON DELETE CASCADE,
    course_id       UUID        REFERENCES courses(id) ON DELETE CASCADE,
    content         JSONB       NOT NULL,
    chroma_id       VARCHAR(255),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ
);

-- ═══════════════════════════════════════════════════════════════════════
-- ALIGNMENT REPORTS
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS alignment_reports (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID        NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    course_id       UUID        NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    report_type     VARCHAR(100) NOT NULL,   -- metadata_content|content_assessment|metadata_assessment|content_delivery
    overall_score   DECIMAL(5,4),
    status          VARCHAR(50),             -- pass|warning|fail
    gap_count       INTEGER      NOT NULL DEFAULT 0,
    warning_count   INTEGER      NOT NULL DEFAULT 0,
    findings        JSONB        NOT NULL,
    recommendations JSONB,
    generated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    reviewed_by     UUID        REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reports_course   ON alignment_reports(course_id);
CREATE INDEX IF NOT EXISTS idx_reports_run      ON alignment_reports(run_id);

CREATE TABLE IF NOT EXISTS alignment_gaps (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id               UUID        NOT NULL REFERENCES alignment_reports(id) ON DELETE CASCADE,
    gap_type                VARCHAR(100),
    severity                VARCHAR(20)  NOT NULL,  -- critical|warning|info
    description             TEXT        NOT NULL,
    affected_entity_type    VARCHAR(100),
    affected_entity_id      UUID,
    evidence_chunk_ids      UUID[],
    score                   DECIMAL(5,4),
    recommendation          TEXT,
    is_resolved             BOOLEAN     NOT NULL DEFAULT FALSE,
    resolved_by             UUID        REFERENCES users(id) ON DELETE SET NULL,
    resolved_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gaps_report      ON alignment_gaps(report_id);
CREATE INDEX IF NOT EXISTS idx_gaps_severity    ON alignment_gaps(severity);

-- ═══════════════════════════════════════════════════════════════════════
-- GENERATED CONTENT & APPROVALS
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS generated_content (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID        REFERENCES agent_runs(id) ON DELETE SET NULL,
    course_id           UUID        NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    content_type        VARCHAR(100),           -- clo|description|exercise|quiz|assessment
    title               VARCHAR(500),
    content             TEXT        NOT NULL,
    content_structured  JSONB,
    bloom_level         VARCHAR(50),
    source_gap_id       UUID        REFERENCES alignment_gaps(id) ON DELETE SET NULL,
    source_chunk_ids    UUID[],
    citations           JSONB,
    confidence_score    DECIMAL(5,4),
    model_used          VARCHAR(100),
    prompt_version      VARCHAR(50),
    generation_metadata JSONB,
    approval_status     VARCHAR(50)  NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|revised
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generated_course     ON generated_content(course_id);
CREATE INDEX IF NOT EXISTS idx_generated_status     ON generated_content(approval_status);

CREATE TABLE IF NOT EXISTS approvals (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id      UUID        NOT NULL REFERENCES generated_content(id) ON DELETE CASCADE,
    reviewer_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    decision        VARCHAR(20)  NOT NULL,   -- approved|rejected|revised
    comment         TEXT,
    revision_text   TEXT,
    decided_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    is_final        BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS feedback (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_id              UUID        REFERENCES generated_content(id) ON DELETE SET NULL,
    rating                  INTEGER     CHECK (rating BETWEEN 1 AND 5),
    feedback_type           VARCHAR(100),
    feedback_text           TEXT,
    episode_embedding_id    VARCHAR(255),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════════════════════════
-- AUDIT LOGS
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audit_logs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(100),
    resource_id     UUID,
    ip_address      INET,
    user_agent      TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_user        ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_resource    ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at  ON audit_logs(created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════
-- SEED DATA
-- ═══════════════════════════════════════════════════════════════════════

INSERT INTO roles (name, description) VALUES
    ('admin',       'System administrator with full access'),
    ('dept_head',   'Department head with cross-programme visibility'),
    ('coordinator', 'Programme coordinator managing multiple courses'),
    ('lecturer',    'Course lecturer with access to own courses')
ON CONFLICT (name) DO NOTHING;

INSERT INTO departments (name, code, faculty) VALUES
    ('Computer Science', 'CS', 'Faculty of Engineering'),
    ('Information Technology', 'IT', 'Faculty of Engineering')
ON CONFLICT (code) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════════════
-- END OF MIGRATION 001
-- ═══════════════════════════════════════════════════════════════════════
