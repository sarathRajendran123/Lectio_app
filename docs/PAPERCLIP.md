# Paperclip boundary

The exposé requires Paperclip orchestration/governance. This repository originally contained only LangGraph. LangGraph remains the inner specialist workflow. `scripts/paperclip_process.py` is an executable outer boundary for a Paperclip process adapter: starts a course audit through Lectio's authenticated API, polls to a terminal state, returns a structured JSON summary, and cancels after its time budget. It never approves proposals.

Configure the Paperclip agent with an absolute Python executable, an absolute script path, working directory and timeout (at least 570 seconds):

```json
{
  "adapterType": "process",
  "adapterConfig": {
    "command": "/absolute/path/to/venv/bin/python",
    "args": ["/absolute/path/to/LECTIO_APP/scripts/paperclip_process.py"],
    "cwd": "/absolute/path/to/LECTIO_APP",
    "timeoutSec": 570,
    "graceSec": 10
  }
}
```

Supply `LECTIO_API_URL`, `LECTIO_COURSE_ID`, and a short-lived `LECTIO_ACCESS_TOKEN` in the adapter's secure environment. Use a course-owner account, not an admin. Token expiry must exceed the run budget. `PAPERCLIP_RUN_ID` is included in the returned summary when present. Do not put secrets into versioned adapter JSON.

Verified boundary: script compilation; runtime tests use the Lectio API directly. Added and contract-tested: identity lookup, atomic checkout (never retry 409), `X-Paperclip-Run-Id` on mutations, completion handoff to `in_review`, and failure handoff to `blocked`. NOT verified: a running Paperclip company, agent provisioning, cross-agent governance or deployment-specific UI support for process adapters. Those require a Paperclip installation and credentials; no claim of full framework integration is made.

Primary references checked 2026-10-13:
- https://github.com/paperclipai/paperclip-docs/blob/main/docs/reference/adapters/process.md
- https://github.com/paperclipai/paperclip/blob/master/server/src/adapters/process/execute.ts

The documented process runtime accepts command, args, cwd, env, timeoutSec and graceSec; availability in the UI varies by release. Validate this configuration against your installed Paperclip release before enabling scheduled runs.

When Paperclip injects `PAPERCLIP_TASK_ID`, `PAPERCLIP_API_URL`, `PAPERCLIP_API_KEY` and `PAPERCLIP_RUN_ID`, the adapter executes the governed task protocol. An audit success hands the issue to `in_review`; it never marks lecturer approval as completed on the agent's authority. API/timeout failures are surfaced and an active Lectio job is cancelled when possible.

The automated tests use `httpx.MockTransport` to verify the Paperclip request/response contract and no-retry conflict rule. They do not claim an external Paperclip instance was exercised. API reference: https://github.com/paperclipai/paperclip/blob/master/docs/api/issues.md

## Decision needed from the supervisor (prepared 2026-11-13, not yet decided)

The exposé names Paperclip for orchestration and governance. No Paperclip installation was available during development, so the question "integrate fully, or keep the current design and document why" is open. This section sets out the facts for that decision. **No decision has been taken or is assumed here.**

What exists today:

| Governance need | In Lectio now | Verified how |
|---|---|---|
| Who may start work, on which course | login, course ownership on every endpoint | `tests/test_phase2_access.py` (every endpoint) |
| Record of what each agent did | append-only, hash-chained trace with an anchor file outside the database | `tests/test_phase1_governance.py`, `tests/test_phase1_completion.py` |
| Human approval before anything changes | drafts stay pending; apply only after approval, once | `tests/test_phase2_resilience.py` |
| Quality gate and bounded retries | Stakeholder gate, at most `QUALITY_MAX_RETRIES` | Phase 1 tests |
| Budget limits | output-token caps, draft cap per audit, one fallback model, result cache; no per-course money budget | `tests/test_llm_cost.py` |
| Stop a running job | cancel endpoint, time limit, restart recovery | `tests/test_phase2_access.py` |
| Outer task protocol for Paperclip | `scripts/paperclip_process.py`: identity, checkout, run header, hand-over to review | mocked contract tests only |

What Paperclip would add that Lectio does not have: an organisation-level view across several agents and projects, budgets in money per agent, a task board with hand-overs outside the application, and governance that does not depend on the application's own database.

Options:

| Option | Work | Risk | Consequence for the thesis |
|---|---|---|---|
| A. Keep LangGraph plus the built-in governance; Paperclip stays an untested adapter | none | the wording of the exposé is not met literally | needs a written deviation approved by the supervisor, with the table above as the argument |
| B. Run a real Paperclip instance and exercise the existing adapter end to end | install Paperclip, create company and agent, one governed audit, record the result | version and adapter-support differences; time | requirement met at the boundary; the internal flow is unchanged |
| C. Move orchestration of the agents into Paperclip | large rewrite of the workflow and its tests | high; the behaviour measured so far would have to be verified again | closest to the exposé; least compatible with the remaining time |

Needed from the supervisor: which option; for B or C, access to a Paperclip installation (URL, company, agent credentials supplied through the environment, never in the repository).

Until a decision is recorded here with a name and a date, the requirement stays "open" in `docs/PRD.md` (F14) and `docs/Tasks.md`.
