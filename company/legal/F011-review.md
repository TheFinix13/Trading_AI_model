# F011 — Legal review

- **Feature:** F011 kill-switches infrastructure (per-symbol + global, hot-reload)
- **Timestamp:** 2026-07-22T01:52:00Z
- **Reviewer:** Legal
- **Verdict:** **pass**

## Public claims added to `company/legal/claim_register.md`

- `agent/platform/kill_switches.py` — three public accessors + four
  public constants; `is_killed(None)` and `is_killed(symbol)` both
  documented with human meaning + code path.
- `agent/platform/kill_switch_admin.py` — four public accessors
  including `activate_kill` / `clear_kill` / `recent_events`.

## Rolling constraints logged (Legal will re-check on Sprint 3+)

1. **Scope-verbatim rule.** Any future UI or Telegram alert citing an
   active kill MUST render the scope value verbatim (never paraphrase
   "GLOBAL" as "everything" without also citing the reason string).
2. **Hot-reload preservation.** The phrase "kill switches with hot-
   reload" is only accurate while `kill_switches._read_state`
   continues to stat-check the directory on every call. A future
   perf optimisation that removes hot-reload must strike the claim
   from any copy that cites it.

## Coverage of user-facing text

- The `/settings/kill-switches` page copy was reviewed against the
  D047 "trust markers" checklist. Approved as-is:
  - The subtitle explicitly discloses that Sprint 2 "ships the
    switch, not the wiring" — no false claim of active order-
    blocking.
  - The activate button is red-tinted so the visual weight matches
    the safety-action semantics.
  - The reason textarea is required on activate — an empty reason
    is refused with an inline status message.

## Cross-references to future features

- F013's live-mode warning MUST document the four-check pathway
  including `kill_switches.is_killed()` as the second gate. F011's
  claim register entry pins the exact function signature so F013's
  Legal copy cites accurate code paths.
- F014's alerts config includes a `kill_switch_trip` event type.
  The event MUST be raised by any future integration that observes
  `is_killed()` transitioning from False to True — but Sprint 2's
  F011 code doesn't fire the alert itself (that's the integration's
  job).

## No user-facing legal warning file needed for F011

The kill switch is a safety primitive whose user-facing consequence
is documented in F013's `live-mode-warning.md`. Standalone Legal file
would duplicate that text.

## Sign

- Legal: **pass** → CPO signoff on behalf of CEO.
