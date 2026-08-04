# Proposal: give the company off-hours shifts (2026-08-04)

Status: PROPOSAL — needs the user's go/no-go. Nothing here is built.

## The honest premise

The "company" (roles, ledger, intakes, sprints) currently executes
ONLY inside Cursor sessions — the employees do not exist between
chats. The autonomous layer on the VM (squad runtime, watchdog,
healthchecks, weekly bundler) pages on infrastructure failures but
performs no ANALYSIS: the last three P0s (silent week, crash-loop,
lookahead) were all caught by the user reading a weekly report, not
by the company. The gap is a shift that READS the tape while nobody
is around.

## Proposed tiers (cheapest first, each independently useful)

### Tier 1 — nightly deterministic auditor (no LLM, ~1 day to build)

A scheduled task (VM, 06:00 server time) running a plain Python
script over the last 24h of `events.jsonl` + heartbeats:

- bars seen vs expected (weekday H4 grid), abstention-reason
  histogram deltas, proposal/trade counts vs 4-week baseline,
  system_status error streaks, watchdog restarts.
- Output: one `morning_digest.md` on the tape + ONE Telegram message
  ("all nominal" or "3 anomalies: …"). Anomalies auto-draft intake
  STUBS (files, not decisions) for the next session to triage.
- This would have caught the silent week on DAY ONE (bars=0 against a
  weekday grid is anomaly #1 by construction).

### Tier 2 — weekly scheduled agent triage (Cursor automation)

A scheduled Cursor agent run (Mac, Monday pre-market) that reads the
week's digests + bundle, does the analyst pass the user currently
does by hand, and leaves a draft weekly review + prioritised intake
queue for the user to ratify. Human stays the decision-maker; the
agent only pre-chews.

### Tier 3 — research batch lane (only if 1–2 prove out)

Same scheduler pattern for long compute: pre-registered sweeps queued
by session-work land overnight with the heartbeat monitor, results
waiting in the morning. (Phase AF ran ~25 min today; an overnight
lane makes 8-hour grids feasible.)

## What this does NOT change

No autonomous parameter changes, no autonomous git pushes to
`product`, no live-order powers. Decisions stay in-session with the
user. The shifts only observe, digest, and draft.

## Cost

Tier 1: zero marginal cost (python + existing Telegram bot).
Tier 2: one scheduled agent run/week.
Tier 3: electricity.
