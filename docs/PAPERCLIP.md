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
