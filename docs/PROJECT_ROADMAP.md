# Project roadmap

Based on the exposé work plan (two semesters) and what exists today.

## Semester 1: alignment auditing
| Phase | Planned | State |
|---|---|---|
| Foundation | Literature, requirements, architecture document (agent roles, course model schema, HITL protocol) | `docs/Architecture.md`, `PRD.md`; literature review is in the exposé |
| Ingestion and course model | Parsers, embeddings, semantic chunking, topic clustering, metadata schema, Course Director | Done; multilingual embeddings; topic clustering uses stored vectors |
| Division 1 and Stakeholder | Four alignment agents, quality brokering, decision capture, lecturer dashboard | Done |
| Hand-in: working alignment tool and research report | M6 | Tool done; report is the team's deliverable |

## Semester 2: creation and evaluation
| Phase | Planned | State |
|---|---|---|
| Division 2 | Grounded generation of objectives, exercises, module descriptions; live alignment feedback | Done (drafts, projected scores as live feedback) |
| Pluggable framework | Model and prompt variants, side-by-side comparison, preference logging | Allow-listed variants and decision logging done; richer comparison open |
| Evaluation study | Precision and recall against manual labels, instructor quality, acceptance rate | Open: protocol and scorer ready, no real data yet |
| Emergent-behaviour analysis | Goal propagation and unexpected outputs in interaction logs | Open: agent steps, tokens and durations are logged |
| Final workbench and report | Documentation and comparative study | In progress |

## Engineering phases (done in this iteration)
1. Baseline review and test run (revision 2).
2. Provider and embedding switch with cost controls.
3. Live hardening against real provider behaviour.
4. German and English extraction; derived outcomes; clear "not assessable" states.
5. Automatic capped drafts; projected scores.
6. UI speed and readability.

## Next
Docker and PostgreSQL verification, evaluation on real course materials, Paperclip integration, durable queue (see `Tasks.md`).
