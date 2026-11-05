# Product Requirements: Lectio

Lectio is a course-alignment workbench for university lecturers. It audits whether the artefacts of a course (module manual or syllabus, lecture content, assessments) agree with each other, links every finding to its source, drafts grounded fixes, and keeps the lecturer in control of every change. Origin: the MAAI application project "Lectio: the AI course curation company" (see `Lectio_Project_Description.pdf`).

## Problem
Course artefacts are written at different times by different people and are rarely cross-checked. Learning objectives drift from what is taught, exams probe topics the slides barely cover, module descriptions misstate depth. Checking this by hand means reading everything at once.

## Users
| Role | What they do |
|---|---|
| Lecturer | Uploads materials, runs audits, reviews findings, approves, edits or rejects drafts |
| Coordinator | Same, for the courses they coordinate |
| Department head | Read and review across courses |
| Admin | Users, roles, audit log, system status |

Hierarchy in code: `lecturer < coordinator < dept_head < admin` (`backend/auth/rbac.py`).

## Core workflow
1. **Create a course** and upload documents with their type (syllabus, module manual, slides, transcript, reading, assignment, exam, assessment, schedule, other). Formats: PDF, DOCX, PPTX, Markdown, TXT, VTT.
2. **Ingest**: parse, split into chunks (a heading stays with its text), embed (multilingual), store with source location.
3. **Course model**: learning objectives and the weekly schedule are extracted from the files (English and German phrasing). If none are stated anywhere, outcomes are *derived* from the taught material and flagged as generated.
4. **Audit** four boundaries: metadata and content, content and assessment, metadata and assessment, content and planned delivery. Each has rule-based checks plus a bounded model review that must cite supplied evidence.
5. **Findings** with severity, the evidence excerpts, and a suggested action. Confirmations ("this is supported") are kept separate from problems.
6. **Drafts** for the worst gaps (capped per audit): objectives, quiz or exam questions, exercises. Each cites its sources.
7. **Decide**: approve, edit, or reject every draft. Original, edits and decisions are kept.
8. **Projection**: approved drafts are re-checked against the findings they could close, showing a projected score next to the verified one without re-running the audit.
9. **Apply** an approved draft to the course model, re-run the audit to verify, and **export** reports, evidence and decisions.

## Functional requirements and status
| # | Requirement | Status |
|---|---|---|
| F1 | Ingest PDF, DOCX, PPTX, MD, TXT, VTT safely (size, MIME, archive limits, parser isolation) | Done |
| F2 | Multilingual retrieval (German and English): dense + BM25 + reranker | Done, tested on real models |
| F3 | Extract objectives and weekly schedule from stated text | Done |
| F4 | Derive outcomes when none are stated, flagged for review | Done |
| F5 | Four-dimension audit with source-linked findings | Done |
| F6 | Findings never claim a source was not taught; absence is "insufficient evidence" | Done |
| F7 | Grounded draft generation with validated citations | Done (live-verified on free models) |
| F8 | Human approval for every change; nothing writes back to sources | Done |
| F9 | Projected scores after approvals | Done |
| F10 | Lecturer dashboard, reports, approval center, workbench | Done (Streamlit) |
| F11 | Audit trail of agent steps, tokens and durations | Done |
| F12 | Pluggable model and prompt variants, side-by-side comparison | Done (allow-listed variants) |
| F13 | Evaluation study with real MAAI course materials | Open (protocol and scorer exist: `docs/EVALUATION.md`, `scripts/evaluate.py`) |
| F14 | Governance and orchestration through an external Paperclip deployment | Open (process adapter only: `docs/PAPERCLIP.md`) |
| F15 | Emergent-behaviour analysis of interaction logs | Open |

## Non-functional requirements
- **Human in the loop**: no automatic write-back; every generated item is labelled a suggestion.
- **Languages**: German and English materials and outputs.
- **Cost**: runs on free-tier models; identical validated requests are cached; capped drafts per audit.
- **Privacy**: embeddings are computed locally; document text goes to the model provider only inside prompts for reviews and drafts.
- **Honesty**: scores are heuristic evidence indicators, not probabilities; projected scores are labelled as projections.

## Out of scope
Automatic edits to course systems, grading, student-facing features, and any claim of calibrated accuracy.

## Success measures (from the exposé; not yet measured on real data)
Alignment precision and recall against manual ground truth, instructor-rated draft quality, and draft acceptance rate. The scoring script exists; no real measurements are claimed.
