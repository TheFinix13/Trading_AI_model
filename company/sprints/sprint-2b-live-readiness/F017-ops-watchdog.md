# F017 — Ops Watchdog: check registry + alert publisher + `/hq` strip

- **Sprint:** sprint-2b-live-readiness
- **Priority:** P0 — CEO no-black-boxes directive (2026-07-24).
- **Lane:** Observability. Lands BEFORE F018 so the executor is born
  observable.
- **Consumes:** F014 alerts bus (`alerts.publish`), F012
  `broker_health.list_health_states()`, `paper_loop.live_status()`,
  the company ledger + `company/rd/intake/` front matter.
- **Consumed by:** `/hq` (status strip), F014 SSE stream + Telegram
  bridge (`watchdog_alert` events), `scripts/run_watchdog.py`
  (cron / Task Scheduler).
- **Feature flags:** `auth: true` (status API install-token-gated on
  non-localhost), `legal_relevant: true` — new bus event type trips
  the F014 rolling constraint (Legal re-review inline).

## Problem statement

The CEO: "we can't have a black box system... we need to be notified
of irregular behaviors or problems within any of our systems,
including the company loop." Today a stalled squad runtime, a stale
news cache, a dead broker connection, a corrupted risk ledger, an
intake item rotting past its SLA, or a JSON↔MD ledger drift (the bug
that actually happened at Sprint 2 close, see D076–D080 history) are
all invisible until a human goes looking. F017 makes each of them a
named check with a colour.

## Scope (in)

### `agent/platform/watchdog.py` (new)

**Check registry** — every check returns
`{id, status: "ok"|"warn"|"alarm"|"na", detail, checked_at}`:

| id | Source | warn | alarm | na |
|---|---|---|---|---|
| `runtime_heartbeat` | squad_live `poll_heartbeat.txt` / `state.json` freshness via `paper_loop.live_status()` | age > 5 min | age > 30 min | live dir not configured / never started |
| `calendar_feed` | news cache `fetched_at` age (`data/news_calendar.json` shape) | > 12 h | > 48 h | cache absent |
| `broker_health` | `broker_health.list_health_states()` | any alias not alive (probed) | — | no aliases saved |
| `risk_state` | `risk_state.jsonl` parseable + rows not future-dated | — | corrupt line / future-dated row | file absent (clean install) |
| `intake_sla` | `company/rd/intake/I*.md` front matter | P1 `status: filed` > 7 d; any open item > 30 d | P0 `status: filed` > 4 h | intake dir absent |
| `sprint_pulse` | company_state.json | sprint `in_progress` with no ledger decision in 7 d | — | no in-progress sprint |
| `ledger_drift` | decisions count JSON vs MD | — | count mismatch | ledger files absent |

Public API:

```python
CHECK_IDS: tuple[str, ...]
run_checks(...) -> list[dict]          # full registry snapshot
run_check(check_id, ...) -> dict       # one check
snapshot(...) -> dict                  # {checks, overall, generated_at}, ~30s cache
publish_transitions(results) -> list   # state-change-only bus publishing
```

Every check takes injectable paths / clocks for tests; no check may
raise (fail to `alarm` with a descriptive detail, or `na`).

**Publisher.** On a `warn`/`alarm` transition ONLY (state change, not
every poll), publish a `watchdog_alert` event to the F014 bus so SSE
+ Telegram carry it. Recovery back to `ok` also publishes (transition
to ok = "resolved" notice). Last-known states persist at
`<config_dir>/watchdog_state.json` so restarts don't re-fire.

### `alerts.py` whitelist expansion (edit)

`EVENT_TYPES` gains `"watchdog_alert"`. The F014 rolling constraint
says this REQUIRES a Legal re-review: done inline this sprint —
verdict at `company/legal/F017-review.md`, claim register updated,
decision logged. `alerts_telegram._DEFAULT_PER_EVENT` gains
`watchdog_alert: True` (an ops alarm is exactly what Telegram is
for); `config.py` per_event defaults gain the same key.

### Surfaces

- `GET /api/watchdog/status` — runs `snapshot()` (cached ~30 s),
  install-token-gated on non-localhost like every `/api/*`.
- `/hq` status strip — compact green/amber/red chip per check at the
  top of the HQ page, rendered via `withStates()` fetch pattern.
- `scripts/run_watchdog.py` — one-shot (exit code 0 ok / 1 warn /
  2 alarm) or `--loop N` seconds mode with the standard
  heartbeat-file pattern (`<config_dir>/watchdog_heartbeat.txt`),
  publishing transitions to the bus each pass.

## Scope (out)

- Paging/incident SaaS (PagerDuty etc.) — Finance stays dormant.
- Auto-remediation of any kind — the watchdog observes and notifies,
  never mutates the systems it watches.
- Watching `agent/live/*` internals beyond the file artefacts it
  already emits (zero-diff invariant).

## Tests (target ≥ 35)

`tests/platform/test_watchdog_module.py` — per-check ok/warn/alarm/na
with tmp fixtures (freshness ages driven by injectable `now`);
`test_watchdog_transitions.py` — state-change-only publishing,
persistence across restarts, recovery notice;
`test_watchdog_api.py` — status endpoint + cache + auth gate;
`test_watchdog_page.py` — `/hq` strip smoke;
`test_run_watchdog_script.py` — one-shot exit codes + heartbeat file.

## Acceptance

- All checks green on a healthy dev checkout; each degraded fixture
  produces the documented colour.
- A transition publishes exactly ONE bus event; a repeated poll at
  the same state publishes ZERO.
- `watchdog_alert` registered in the claim register + Legal review on
  tape BEFORE ship.
- Full suite + claim audit green.

## Files touched

New: `agent/platform/watchdog.py`, `scripts/run_watchdog.py`,
5 test files, `company/legal/F017-review.md`.
Edited: `agent/platform/{alerts,alerts_telegram,config,pages}.py`,
`scripts/serve_platform.py`, `company/legal/claim_register.md`,
`company/ledger/{company_state.json,decisions_log.md}`.
