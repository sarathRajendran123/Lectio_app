# Release checklist: production readiness

`[x]` done and evidenced, `[ ]` not done. Lectio is a research prototype; this list says what is still needed before real lecturers rely on it.

## Quality
- [x] Automated suite passes (`python -m pytest -q`: 60 passed, 1 skipped on 2026-11-05)
- [x] Live provider check passes (`scripts/verify_live.py`)
- [x] German and English retrieval verified on the real models
- [x] End-to-end run on an English and a German sample course
- [ ] PostgreSQL regression test run (`LECTIO_TEST_POSTGRES_DSN`)
- [ ] Evaluation on real MAAI course materials with manual ground truth (`docs/EVALUATION.md`)
- [ ] Load test with a realistic corpus (limit today: 10,000 chunks per course)

## Security (details: `SECURITY_CHECKLIST.md`)
- [ ] Rotate every credential that was shared in chat (provider key, database password, admin password)
- [ ] Fresh `SECRET_KEY` (32+ random characters) and database password per environment
- [ ] `pip-audit` re-run on the final dependency set
- [ ] TLS in front of the app (reverse proxy), request body limits, shared rate limits
- [ ] Course-sharing rules decided (today: owner and admin only)
- [ ] Retention and deletion policy for uploaded documents and prompts sent to the model provider

## Deployment
- [ ] `docker compose up --build` verified (the daemon was unavailable during development)
- [ ] Model weights downloaded once into the `hf_cache` volume (about 2.8 GB)
- [ ] `RUNTIME_MODE=live`, `RETRIEVAL_BACKEND=neural`, `ARTIFACT_STORAGE_PATH=/app/uploads`
- [ ] One API worker only, or a durable job queue added first
- [ ] Database backup and restore rehearsed; migration approach decided (tables are created at start-up)
- [ ] Health and status page checked (`System status`)
- [ ] Logs reviewed for secrets

## Cost and models
- [x] Free default model with a fallback; caches and caps in place
- [ ] Decide the production model and budget: the free tier allows 50 requests per day without credit (about 5 audits)
- [ ] Confirm the provider's data handling is acceptable for the documents used

## Product
- [x] Every generated item is a suggestion; nothing writes back to sources
- [x] "Not assessable" instead of "Unknown"; projected scores labelled
- [ ] Accessibility review with a screen reader
- [ ] Lecturer acceptance test with at least one real course
- [ ] Paperclip governance integration, if required by the project

## Documentation
- [x] PRD, architecture, design, rules, memory, tasks, roadmap, progress, security, testing, schema
- [ ] Operator guide for backup, upgrades and incident handling
