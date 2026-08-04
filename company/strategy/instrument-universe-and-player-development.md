# Instrument universe + player development doctrine (D148)

Filed 2026-08-04 on user directive: extend to every pair we never
used BEFORE new instrument classes; list the whole tradable universe;
analyse fields first, then rework players (or create new ones) from
the analysis; iterate in small balance patches ("Apex seasons"), not
big-bang updates; the goal is every player reaching an ultimate v1
that provably does something on the field.

## 1. The tradable universe (concrete list, tiered by readiness)

**Tier 1 — banked now, start immediately (FX majors never squad-mined):**
AUDUSD, NZDUSD, USDJPY, USDCHF — H4+D1 parquet already in the cache
(2015→2025). Lightly fingerprinted once by Phase AC under void
lookahead semantics; usable for design on pre-2023 data with the
2023→present seal per DATA_LEDGER rule 4.

**Tier 2 — Dukascopy/MT5-bankable this week (needs symbol-map extension):**
- FX crosses: EURGBP, EURJPY, GBPJPY, EURCHF, EURAUD, AUDJPY,
  CADJPY, AUDNZD, GBPCHF, NZDJPY
- Metals: XAUUSD (gold), XAGUSD (silver), XPTUSD (platinum)
- Energy: USOIL (WTI), UKOIL (Brent), NATGAS
- Index CFDs (Exness offers them on the same MT5 terminal): USTEC
  (Nasdaq-100), US500 (S&P), US30 (Dow), DE40 (DAX), UK100, JP225
- Crypto CFDs: BTCUSD, ETHUSD (24/7 sessions — needs its own
  calendar semantics before any study)

**Tier 3 — different infrastructure, explicitly later:**
- Futures proper (ES/NQ/CL/GC): needs a new data vendor + contract
  roll logic; do not fake it with CFDs and call it futures.
- Single-name stocks: OUT OF SCOPE for this repo — the stock
  portfolio lane lives in `global-portfolio-assistant` (brain-box
  separation rule). Index CFDs above are the equity exposure here.

**Field-audit prerequisite (per instrument, before any replay):** pip
/point size, spread regime, session hours and gaps (oil/indices gap
daily; FX doesn't), swap/rollover, and which calendar currencies
drive it. A one-page FIELD_CARD per instrument, committed before the
first study touches it.

## 2. Rework doctrine — how a player gets changed without rigging the test

The invariant: **we change the PLAYER, never the TEST.** Floors,
windows and verdict rules are frozen by pre-registration before any
replay; a rework is a new weapon version taking the SAME exam on
data it has never selected on. "Enough of all the failures" is
answered by better weapons and cleaner fields — never by moving
goalposts. The balance-patch loop:

1. **Autopsy (free, no new data):** mine the agent's EXISTING losing
   tape — where do losses cluster (session, regime, hold time, stop
   distance)? The diagnosis must name a mechanism, not a wish.
2. **Ground the redesign in evidence that exists outside us:**
   documented strategy families with academic/practitioner support —
   time-series momentum (Moskowitz et al. 2012), conditional
   momentum (2025 lit: trade momentum only when volatility and
   dispersion are low), carry (Lustig et al.), session/opening-range
   effects (London-open breakout), event drift (our own Phase AG
   +14–19 pips result). No invented indicators.
3. **Design on design fields, validate on sealed fields:** pre-2023
   Tier-1 pairs for tuning; ONE opening of a sealed window (or live
   weeks) for the verdict. Thin-n agents use the multi-start
   standard (METHODOLOGY_thin_sample_replays.md).
4. **Small patches, versioned:** Chigiri v1.1, not Chigiri v2.0 —
   one mechanism change per patch so the ablation is interpretable.
   Reverts are legitimate outcomes (Apex reverts too).

## 3. First reworks chartered under this doctrine

- **Chigiri v1.1 (the sprinter, currently negative on every field):**
  step 1 autopsy of his AF loss tape this week. Redesign hypothesis
  space (declared now, selection later, from the autopsy): (a)
  session-anchored breakout (London-open range) — canon-consistent
  with a speed weapon; (b) conditional-momentum gate (only run when
  volatility/dispersion regime favors continuation, per the 2025
  conditional-momentum literature); (c) revert-and-narrow (his v1
  ATR logic restricted to the sessions where the autopsy shows it
  ever worked). One candidate advances to pre-registration on Tier-1
  design fields.
- **Reo striker mode (AK-2, user direction: "in the NEL he played
  without Nagi"):** his mirror thoughts already carry full
  coordinates and the leader's trade plan — replay them as
  counterfactual TRADES on the existing tape (zero new data, shared
  counterfactual_replay tooling). If mirror-as-trade shows positive
  expectancy, Reo earns a provable two-mode charter (Nagi-filter +
  striker); if not, he stays the filter. Pre-registration next.
- **Barou n-growth** continues under the multi-start standard on
  Tier-1 USD pairs (his home semantics travel: USDCAD → USDJPY/
  USDCHF are USD-base fields).

## 4. Sequencing (small patches, weekly cadence)

Week of 08-04: field cards + autopsies + S1 panel (user VM action) +
live measurement week. Then one pre-registered study per week per
lane, ledgered, with DATA_LEDGER updated at every window-open. The
scoreboard (NEL) reads results; it never writes them.
