# Database schema

Generated from the SQLAlchemy models (`backend/db/models/`) on 2026-11-05: 28 tables. The PostgreSQL DDL for the production setup is `backend/db/migrations/versions/001_initial.sql`; ORM column types are checked against it by `tests/test_postgres_regressions.py`.

## Notes
- **Engines**: SQLite (local, `aiosqlite`) and PostgreSQL 15 (Docker, `asyncpg`). JSON columns compile to JSONB on PostgreSQL.
- **Vectors**: stored in `chunks.metadata` under `vector` (list of floats) together with `chunks.embedding_model`. Retrieval ignores vectors from another model. Exact cosine search, up to 10,000 chunks per course.
- **No migration system**: missing tables are created at start-up. Back up data before changing models.
- **Deletes**: artefact and course deletes cascade to chunks, reports and derived records.
- **Audit trail**: `agent_runs` and `agent_steps` record every run and agent step (status, tokens, duration); `audit_logs` records data-changing API calls; `approvals` and `finding_decisions` are append-only lecturer decisions.

## Main relationships
```
courses -< modules -< weeks -< topics -< subtopics
modules -< learning_objectives
courses -< assessments -< assessment_questions ; assessments -< assessment_sources >- chunks
courses -< course_artifacts -< chunks
courses -< agent_runs -< agent_steps ; agent_runs -< alignment_reports -< alignment_gaps -< finding_decisions
courses -< generated_content -< approvals ; generated_content -- applied_suggestions
users >-< roles (user_roles) ; users -< refresh_tokens ; departments -< users
```

## Tables
### `agent_memory`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| memory_type | VARCHAR(100) | no |  |
| user_id | UUID | yes | FK -> users.id (CASCADE) |
| course_id | UUID | yes | FK -> courses.id (CASCADE) |
| content | JSON | no |  |
| chroma_id | VARCHAR(255) | yes |  |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| expires_at | DATETIME | yes |  |

### `agent_runs`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| course_id | UUID | no | FK -> courses.id (CASCADE) |
| initiated_by | UUID | yes | FK -> users.id (SET NULL) |
| workflow_type | VARCHAR(100) | no |  |
| status | VARCHAR(50) | no |  |
| langgraph_run_id | VARCHAR(255) | yes |  |
| langsmith_run_id | VARCHAR(255) | yes |  |
| workflow_state | JSON | yes |  |
| error_message | TEXT | yes |  |
| started_at | DATETIME | no |  |
| completed_at | DATETIME | yes |  |
| total_tokens_used | INTEGER | yes |  |
| total_cost_usd | NUMERIC(10, 6) | yes |  |

### `agent_steps`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| run_id | UUID | no | FK -> agent_runs.id (CASCADE) |
| agent_name | VARCHAR(100) | no |  |
| step_type | VARCHAR(100) | yes |  |
| input_summary | TEXT | yes |  |
| output_summary | TEXT | yes |  |
| tokens_used | INTEGER | yes |  |
| duration_ms | INTEGER | yes |  |
| status | VARCHAR(50) | yes |  |
| error_message | TEXT | yes |  |
| created_at | DATETIME | no |  |

### `alignment_gaps`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| report_id | UUID | no | FK -> alignment_reports.id (CASCADE) |
| gap_type | VARCHAR(100) | yes |  |
| severity | VARCHAR(20) | no |  |
| description | TEXT | no |  |
| affected_entity_type | VARCHAR(100) | yes |  |
| affected_entity_id | UUID | yes |  |
| score | NUMERIC(5, 4) | yes |  |
| recommendation | TEXT | yes |  |
| is_resolved | BOOLEAN | no |  |
| resolved_by | UUID | yes | FK -> users.id (SET NULL) |
| resolved_at | DATETIME | yes |  |

### `alignment_reports`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| run_id | UUID | no | FK -> agent_runs.id (CASCADE) |
| course_id | UUID | no | FK -> courses.id (CASCADE) |
| report_type | VARCHAR(100) | no |  |
| overall_score | NUMERIC(5, 4) | yes |  |
| status | VARCHAR(50) | yes |  |
| gap_count | INTEGER | no |  |
| warning_count | INTEGER | no |  |
| findings | JSON | no |  |
| recommendations | JSON | yes |  |
| generated_at | DATETIME | no |  |
| reviewed_by | UUID | yes | FK -> users.id (SET NULL) |
| reviewed_at | DATETIME | yes |  |

### `applied_suggestions`

| Column | Type | Null | Key / default |
|---|---|---|---|
| content_id | UUID | no | PK; FK -> generated_content.id (CASCADE) |
| target_type | VARCHAR(40) | no |  |
| target_id | UUID | no |  |
| applied_by | UUID | no | FK -> users.id (CASCADE) |
| accepted_snapshot | TEXT | no |  |
| created_at | DATETIME | no |  |

### `approvals`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| content_id | UUID | no | FK -> generated_content.id (CASCADE) |
| reviewer_id | UUID | no | FK -> users.id (CASCADE) |
| decision | VARCHAR(20) | no |  |
| comment | TEXT | yes |  |
| revision_text | TEXT | yes |  |
| decided_at | DATETIME | no |  |
| is_final | BOOLEAN | no |  |

### `assessment_questions`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| assessment_id | UUID | no | FK -> assessments.id (CASCADE) |
| text | TEXT | no |  |
| bloom_level | VARCHAR(50) | yes |  |
| marks | NUMERIC(10, 2) | yes |  |
| topic_id | UUID | yes | FK -> topics.id (SET NULL) |
| question_type | VARCHAR(50) | yes |  |

### `assessment_sources`

| Column | Type | Null | Key / default |
|---|---|---|---|
| assessment_id | UUID | no | PK; FK -> assessments.id (CASCADE) |
| artifact_id | UUID | no | FK -> course_artifacts.id (CASCADE) |
| chunk_id | UUID | no | FK -> chunks.id (CASCADE) |
| extraction_method | VARCHAR(60) | no |  |

### `assessments`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| course_id | UUID | no | FK -> courses.id (CASCADE) |
| title | VARCHAR(500) | no |  |
| type | VARCHAR(50) | yes |  |
| weight_percent | NUMERIC(5, 2) | yes |  |
| total_marks | NUMERIC(10, 2) | yes |  |
| week_due | INTEGER | yes |  |
| submission_format | VARCHAR(100) | yes |  |
| description | TEXT | yes |  |
| created_at | DATETIME | no |  |

### `audit_logs`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| user_id | UUID | yes | FK -> users.id (SET NULL) |
| action | VARCHAR(100) | no |  |
| resource_type | VARCHAR(100) | yes |  |
| resource_id | UUID | yes |  |
| ip_address | VARCHAR(45) | yes |  |
| user_agent | TEXT | yes |  |
| metadata | JSON | yes |  |
| created_at | DATETIME | no |  |

### `chunks`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| artifact_id | UUID | no | FK -> course_artifacts.id (CASCADE) |
| course_id | UUID | no | FK -> courses.id (CASCADE) |
| text | TEXT | no |  |
| token_count | INTEGER | yes |  |
| char_count | INTEGER | yes |  |
| chunk_index | INTEGER | yes |  |
| page_number | INTEGER | yes |  |
| slide_number | INTEGER | yes |  |
| section_title | VARCHAR(500) | yes |  |
| week_number | INTEGER | yes |  |
| document_position | NUMERIC(5, 4) | yes |  |
| chroma_id | VARCHAR(255) | yes |  |
| embedding_model | VARCHAR(100) | yes |  |
| embedded_at | DATETIME | yes |  |
| created_at | DATETIME | no |  |
| metadata | JSON | no |  |

### `course_artifacts`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| course_id | UUID | no | FK -> courses.id (CASCADE) |
| uploaded_by | UUID | yes | FK -> users.id (SET NULL) |
| filename | VARCHAR(500) | no |  |
| original_filename | VARCHAR(500) | yes |  |
| file_type | VARCHAR(50) | no |  |
| artifact_type | VARCHAR(100) | yes |  |
| file_size_bytes | BIGINT | yes |  |
| storage_path | VARCHAR(1000) | yes |  |
| processing_status | VARCHAR(50) | no |  |
| processing_error | TEXT | yes |  |
| page_count | INTEGER | yes |  |
| slide_count | INTEGER | yes |  |
| word_count | INTEGER | yes |  |
| checksum | VARCHAR(64) | yes |  |
| uploaded_at | DATETIME | no |  |
| processed_at | DATETIME | yes |  |
| metadata | JSON | no |  |

### `courses`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| code | VARCHAR(50) | no | unique |
| title | VARCHAR(500) | no |  |
| description | TEXT | yes |  |
| credits | INTEGER | yes |  |
| level | VARCHAR(20) | yes |  |
| nqf_level | INTEGER | yes |  |
| department_id | UUID | yes | FK -> departments.id (SET NULL) |
| coordinator_id | UUID | yes | FK -> users.id (SET NULL) |
| year | INTEGER | yes |  |
| semester | VARCHAR(20) | yes |  |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |

### `departments`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| name | VARCHAR(255) | no |  |
| code | VARCHAR(20) | no | unique |
| faculty | VARCHAR(255) | yes |  |
| created_at | DATETIME | no |  |

### `finding_decisions`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| gap_id | UUID | no | FK -> alignment_gaps.id (CASCADE) |
| reviewer_id | UUID | no | FK -> users.id (CASCADE) |
| decision | VARCHAR(30) | no |  |
| rationale | TEXT | yes |  |
| revised_recommendation | TEXT | yes |  |
| version_context | JSON | no |  |
| created_at | DATETIME | no |  |

### `generated_content`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| run_id | UUID | yes | FK -> agent_runs.id (SET NULL) |
| course_id | UUID | no | FK -> courses.id (CASCADE) |
| content_type | VARCHAR(100) | yes |  |
| title | VARCHAR(500) | yes |  |
| content | TEXT | no |  |
| bloom_level | VARCHAR(50) | yes |  |
| source_gap_id | UUID | yes | FK -> alignment_gaps.id (SET NULL) |
| citations | JSON | yes |  |
| confidence_score | NUMERIC(5, 4) | yes |  |
| model_used | VARCHAR(100) | yes |  |
| approval_status | VARCHAR(50) | no |  |
| created_at | DATETIME | no |  |

### `learning_objectives`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| module_id | UUID | no | FK -> modules.id (CASCADE) |
| text | TEXT | no |  |
| code | VARCHAR(50) | yes |  |
| bloom_level | VARCHAR(50) | yes |  |
| bloom_verb | VARCHAR(100) | yes |  |
| source_document_id | UUID | yes | FK -> course_artifacts.id (SET NULL) |
| is_generated | BOOLEAN | no |  |
| created_at | DATETIME | no |  |

### `modules`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| course_id | UUID | no | FK -> courses.id (CASCADE) |
| title | VARCHAR(500) | no |  |
| description | TEXT | yes |  |
| sequence_number | INTEGER | no |  |
| credit_weight | NUMERIC(5, 2) | yes |  |
| created_at | DATETIME | no |  |

### `refresh_tokens`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| user_id | UUID | no | FK -> users.id (CASCADE) |
| token_hash | VARCHAR(64) | no |  |
| issued_at | DATETIME | no |  |
| expires_at | DATETIME | no |  |
| revoked_at | DATETIME | yes |  |
| revoke_reason | VARCHAR(50) | yes |  |

### `roles`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| name | VARCHAR(50) | no | unique |
| description | VARCHAR | yes |  |
| created_at | DATETIME | no |  |

### `rubric_criteria`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| rubric_id | UUID | no | FK -> rubrics.id (CASCADE) |
| criterion_text | TEXT | no |  |
| weight_percent | NUMERIC(5, 2) | yes |  |
| clo_id | UUID | yes | FK -> learning_objectives.id (SET NULL) |

### `rubrics`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| assessment_id | UUID | no | FK -> assessments.id (CASCADE) |
| title | VARCHAR(500) | yes |  |
| created_at | DATETIME | no |  |

### `subtopics`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| topic_id | UUID | no | FK -> topics.id (CASCADE) |
| title | VARCHAR(500) | no |  |
| description | TEXT | yes |  |
| sequence_order | INTEGER | yes |  |

### `topics`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| week_id | UUID | no | FK -> weeks.id (CASCADE) |
| title | VARCHAR(500) | no |  |
| description | TEXT | yes |  |
| sequence_order | INTEGER | yes |  |
| created_at | DATETIME | no |  |

### `user_roles`

| Column | Type | Null | Key / default |
|---|---|---|---|
| user_id | UUID | no | PK; FK -> users.id (CASCADE) |
| role_id | UUID | no | PK; FK -> roles.id (CASCADE) |
| granted_by | UUID | yes | FK -> users.id (SET NULL) |
| granted_at | DATETIME | no |  |

### `users`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| email | VARCHAR(255) | no | unique |
| hashed_password | VARCHAR(255) | no |  |
| full_name | VARCHAR(255) | no |  |
| is_active | BOOLEAN | no |  |
| is_verified | BOOLEAN | no |  |
| department_id | UUID | yes | FK -> departments.id (SET NULL) |
| created_at | DATETIME | no |  |
| updated_at | DATETIME | no |  |
| last_login | DATETIME | yes |  |
| failed_login_attempts | INTEGER | no |  |
| locked_until | DATETIME | yes |  |

### `weeks`

| Column | Type | Null | Key / default |
|---|---|---|---|
| id | UUID | no | PK |
| module_id | UUID | no | FK -> modules.id (CASCADE) |
| week_number | INTEGER | no |  |
| title | VARCHAR(500) | yes |  |
| theme | TEXT | yes |  |

