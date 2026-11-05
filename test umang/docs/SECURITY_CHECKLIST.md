# Security checklist

Status: Verified (a test or a run shows it), Implemented (in code, not separately tested), Open. No unconditional security certification is claimed. Details of the dependency work: `SECURITY_CHANGES.md`.

## Authentication and access
| Control | Status | Evidence |
|---|---|---|
| Password hashing (bcrypt); no default password, local admin password generated | Implemented | `auth/password_handler.py`, `scripts/setup_local.py` |
| JWT access tokens (PyJWT), short expiry (15 min) | Implemented | `auth/jwt_handler.py`, `config.py` |
| Refresh tokens stored hashed, rotated, inactivity check | Implemented | `auth/jwt_handler.py` |
| Logout revokes the refresh token | Verified | `test_failed_login_counter_and_logout` |
| Failed-login counter persisted | Verified | `test_failed_login_counter_and_logout` |
| Request rate limiting middleware | Implemented | `api/v1/middleware/rate_limit.py` (not separately tested) |
| Role hierarchy enforced server-side | Implemented | `auth/rbac.py` |
| Course and child-object ownership: other users cannot read or change them | Verified | `test_course_and_child_isolation`, `test_workflow_object_isolation_and_deleted_sources` |
| Strong secret validation at start-up (min 32 chars, no placeholders) | Implemented | `config.py` |

## Uploads and parsing
| Control | Status | Evidence |
|---|---|---|
| Size limit, extension, MIME and signature match, path tricks | Verified | `test_untrusted_office_and_paths`, `test_upload_errors_and_duplicate_cleanup` |
| Office archives validated and expansion bounded | Verified | `test_untrusted_office_and_paths`, `test_office_pdf_formats_and_empty_pdf` |
| Parsing in a subprocess with timeout; CPU/memory limits on Linux | Implemented | `services/safe_parser.py` (Windows needs OS or container limits) |
| Private upload directory, atomic writes | Implemented | `services/upload_service.py` |
| Corrupt or encrypted files fail safely | Verified | `test_parser_rejects_encrypted_pdf`, `test_office_pdf_formats_and_empty_pdf` |

## Data isolation
| Control | Status | Evidence |
|---|---|---|
| Vectors stored with the chunk row; retrieval scoped to the course and processed sources | Verified | `test_actual_sql_vectors_isolation_and_filters` |
| Vectors from another embedding model ignored | Verified | `tests/test_llm_cost.py` |

## LLM and prompt safety
| Control | Status | Evidence |
|---|---|---|
| Documents treated as untrusted data in prompts | Implemented | `live_review.py`, `grounded_generator.py` |
| Model output parsed and schema-validated before use | Verified | `test_strict_generation_schema_and_quotes`, live runs |
| Citations restricted to supplied chunks; findings citing others dropped | Verified | `test_citation_rejection`, `test_live_review_rejects_unretrieved_evidence`, live runs |
| Provider key never returned by status endpoints or logs | Implemented | `workbench.py`, `health_service.py`; key never printed during testing |
| Model variants allow-listed | Implemented | `api/v1/routes/workbench.py` |
| Output caps, one fallback, no retry loops, quota stop | Verified | `tests/test_llm_cost.py` |

## Secrets and repository hygiene
| Control | Status | Evidence |
|---|---|---|
| `.env` and local data ignored by Git | Verified | `.gitignore` |
| Tracked files scanned for keys and passwords before sharing | Verified 2026-11-05 | no matches for provider keys or known local passwords |
| Credentials that were pasted into chat during development | Open | **rotate the Groq key, the database password and the admin password** |

## Transport and deployment
| Control | Status |
|---|---|
| TLS and reverse proxy | Open (required before public use) |
| Shared rate limits for several instances | Open |
| Docker services bound to loopback | Implemented (`docker-compose.yml`) |
| `pip-audit` clean on installed set | Verified 2026-10-13 (see `DEPENDENCY_AUDIT.json`); re-run after the 2026-11-03 dependency changes |
| Retention policy, backup and restore | Open |
| Full accessibility and load review | Open |

## UI output safety
Draft and finding text is escaped before it is placed in HTML. Streamlit renders other text as plain markdown.
