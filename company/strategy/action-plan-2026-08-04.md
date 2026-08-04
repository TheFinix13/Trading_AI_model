# Action plan — week of 2026-08-04 (D147)

Directive: "we need substantial results… at least 1 agent finding
something," with all resources in play. Constraint that shapes
everything below: the banked FX H4 data is close to mined-out for the
squad (see research repo `programs/M001_multi_agent_ensemble/
DATA_LEDGER.md`) — substantial results now come from NEW data types,
NEW instruments, the LIVE tape, and mechanism fixes, not from
re-sweeping the same three pairs.

## Lane 1 — the surprise panel (highest expected value; BLOCKED ON USER)

- **USER ACTION: run `ExportCalendarHistory.mq5` on the VM's MT5
  terminal (MetaEditor → compile → run), copy the CSV from
  `MQL5\Files\` back to the Mac.** ~10 minutes of clicking.
- Then (agent, same day): `normalize_panel.py` → coverage audit →
  S1 protocol registers → AG-2 re-run with the surprise gate on the
  pristine 2022–2025 event-study reservation. Phase AG already showed
  +14–19 pips/trade in ≥8×ATR event moves; S1's surprise z-score is
  the instrument that identifies those AT release time. This is
  Sae's arming path and the single most likely "agent finds
  something" this week.

## Lane 2 — new fields with clean data (agent-executable)

- Bank XAUUSD / XAGUSD / USOIL / USTEC H4 history (Dukascopy pull or
  MT5 export — whichever tooling proves out). ZERO prior mining on
  these instruments = the cleanest offline data available to us.
- Pip-size / session-semantics audit per instrument (gold pips ≠ FX
  pips; oil settlement gaps), then pre-registered causal replays
  per agent×instrument. Any pass = first genuinely new field for the
  NEL.

## Lane 3 — the live measurement week (running now, free)

- First honest causal week on the fixed runtime started today.
  Night Auditor reports every morning at 06:30; tomorrow's digest
  must show `timestamp_miss = 0`.
- Friday: `league_table.py` on the live tape = the first NEL match
  window on genuinely unseen data. Live weeks are the validation
  resource that banked data can no longer provide (DATA_LEDGER
  rule 1).

## Lane 4 — mechanism fixes (agent-executable, no data cost)

- **DONE 2026-08-04:** I029 resolved — Reo never trades BY DESIGN
  (chameleon mirror for Nagi's confluence predicate); scoreboard
  exemption shipped; Phase AK ablation measures whether his assist
  earns the slot (roster defeat-trigger, never before evaluated).
- Isagi AF-2 (regime-conditioned impulse): honest design requires
  non-fingerprinted data — parked for live-tape corroboration or the
  new instruments, NOT re-tested on the consumed 2024–2026 window.

## Explicitly NOT this week

- No re-sweeps of EURUSD/GBPUSD/USDCAD H4 parameter grids (mined
  out; any "discovery" there is likely selection noise).
- No S4 presser listening (S3 dead), no headline lane build (parked
  behind S1), no F018 order powers for anyone (no validated edge has
  earned the $500 account yet).
