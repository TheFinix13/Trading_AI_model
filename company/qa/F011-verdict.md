# F011 — QA verdict

- **Feature:** F011 kill-switches infrastructure (per-symbol + global, hot-reload)
- **Timestamp:** 2026-07-22T01:50:00Z
- **Verdict:** **pass**

## Evidence

| Artifact | Result |
|---|---|
| `.venv/bin/python -m pytest tests/platform/test_kill_switches_*.py -q` | 45 passed, 0 failed |
| `.venv/bin/python scripts/check_claim_register.py` | exit 0, register in sync (10 audited, 10 exempted) |
| `.venv/bin/python -m pytest -q` (full suite) | 1340 passed, 1 skipped (playwright, pre-existing) |

## Acceptance criteria (from spec)

- [x] 20+ new tests pass (delivered 45: 11 module + 13 admin + 8 page + 13 api)
- [x] Full suite green
- [x] Golden-path test proves activating global kill masks every symbol (`test_global_kill_masks_all`)
- [x] Mobile pass at 375 px (grid-template-columns collapses to `1fr` inside the F011-specific media query)
- [x] Page renders empty-state cleanly (test_status_empty_state)
- [x] No import from `agent/live/*` or `agent/risk/*` or `agent/squad/*` (grep-verified)
- [x] Live-mode-off gate contract: `is_killed()` shape matches the 4-check pathway

## Risk notes

- Write path (`kill_switch_admin.py`) split from read path (`kill_switches.py`) so a
  compromised read-only accessor can't accidentally trip an activate.
- Audit log at `<config_dir>/kill_events.jsonl` is append-only.
- Reason strings trimmed to 200 chars to bound audit-line size.
- `_bump_mtime()` after every write forces the read-path cache to
  invalidate immediately (some filesystems don't reflect a
  same-second child change on the parent dir mtime).
- Zero diffs in `agent/live/*`, `agent/risk/*`, `agent/squad/*`.
- Live-mode-off contract: `is_killed()` is a *check*, not a *do*.
  Sprint 2 provides the function only; wiring into a live pathway is
  future-sprint work.

## Sign

- QA: **pass** → Legal review → CEO signoff (via CPO on behalf of CEO;
  this feature has a safety-primitive claim that Legal signs off in
  the same commit as the register entry).
