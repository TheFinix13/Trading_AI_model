# Legal review — F018 demo-order executor (Sprint 2b)

- **Reviewer:** legal (persona)
- **Date:** 2026-07-24
- **Decision:** D102 (see `company/ledger/decisions_log.md`)
- **Verdict:** APPROVED with rolling constraints
- **Scope:** `agent/platform/live_executor.py`,
  `POST /api/executor/execute/<approval_id>`,
  `GET /api/executor/status`, `GET /api/executor/warning`,
  the `/approvals` Execute button + warning copy
  (`company/legal/executor-demo-warning.md`), and the
  `docs/RUNBOOK_demo_launch.md` demo-wiring section.

## What was reviewed

1. **The D065 supersession is narrow and documented.** Sprint 2
   shipped four gates and forbade wiring them (D064/D065). D097
   supersedes that for DEMO accounts only. The executor is the ONE
   caller of `approval_queue.can_send_live_order`, and the DEMO-ONLY
   guard makes a real-money pathway structurally unreachable rather
   than merely policy-forbidden. This satisfies the repo's "Demo MT5
   only, never live keys" rule in code.

2. **Claims substantiated.** "Default disabled": `enabled` falls back
   to False on absent/junk config (`load_executor_config`), pinned by
   the extended P0 invariant file. "Demo only": literal
   `demo_only = true` acknowledgement + case-sensitive fnmatch
   allowlist over the server name the adapter ACTUALLY connected to,
   fail-closed on blank/missing/unmatched — not the configured or
   intended server. "Single use": consumption is persisted to
   `executions.jsonl` and survives restarts; an errored send also
   consumes. "No auto-retry": no retry loop exists on any path.

3. **No credential leakage.** The adapter receives an ALIAS only and
   loads the tuple itself via `broker_connection.load_credentials`
   (F006 keyring path). `executor_status` exposes
   `broker_alias_configured: bool` — never the alias's credentials.
   Execution rows carry symbol/side/volume/status/reason/ticket only.
   The runbook references the designated demo account's login + server
   (login 436983644, Exness-MT5Trial9) which Legal treats as
   non-sensitive for a DEMO trial account; the password appears
   nowhere in the repo and must only ever enter via `/settings/broker`.

4. **Warning copy.** `executor-demo-warning.md` renders on
   `/approvals` when the executor is enabled: demo-not-live framing,
   no-performance-implication line, single-use consumption, volume
   cap, kill-switch pointer. No profit language anywhere on the
   surface.

## Rolling constraints

1. **DEMO-ONLY guard is a safety claim.** Accepting `demo_only`
   values other than literal `true`, loosening the allowlist match,
   defaulting `enabled` to true, raising the `max_volume_lots`
   default, or caching the four-gate check across executions requires
   a fresh Legal review of this file.
2. **Single-use consumption is a safety claim.** Removing or
   weakening the consumption marking (including the errored-send
   consumption) allows replay of a single human approval and requires
   a fresh Legal review.
3. **Real-broker connection remains a hard NO** per `escalation.md`
   Section 5 — it is out of scope for this review and would require
   pen test + a dedicated legal review per D095's ordering.
