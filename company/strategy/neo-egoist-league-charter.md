# Neo Egoist League charter — agent survival scoring (D145)

Date: 2026-08-04 · Status: CHARTERED; the scoreboard (Tier A) ships
same-day, everything that changes TRADING stays research-gated.

## The user's directive (restated honestly)

The squad is not a EURUSD cannibalisation contest. Every player must
(a) hone a weapon whose goals are REPRODUCIBLE, (b) prove it on
whatever field suits that weapon, and (c) contribute measurably to the
one objective that matters: **$500 → $1,000 on the demo account, in
the least time**. Sitting on the pitch publishing thoughts without
ever converting (Reo) is not a neutral act — it costs a roster slot
and dashboard legibility. Like the Neo Egoist League: every player
carries a score, the score is public, and careers are on the line.

One correction to fold in: this does NOT reverse the no-benching
directive. It SUPERSEDES ad-hoc benching with due process — a player
is only relegated after (1) his weapon has been honestly parameterised
under causal semantics (Phase AF and successors), (2) he has had pitch
time on the fields that suit the weapon, and (3) the public scoreboard
shows sustained HP exhaustion. Rin and Isagi were handed 100,000,000
in the story — everyone starts with the same HP here too.

## Tier A — the HP scoreboard (observe-only; SHIPPED with this charter)

`scripts/league_table.py` scores any tape (live `squad_live/` dir or a
batch-replay cell) per agent. **v1 scoring constants — changeable only
by charter amendment, never mid-match:**

| Rule | Value |
|---|---|
| Starting HP (per match window) | 100 |
| Closed trade | ΔHP = 10 × realized R |
| Overtime trade (`bars_held` > 30 H4 bars ≈ 1 trading week) | additional −3 |
| Zero-conversion drain (proposer with 0 trades) | −1 HP per 250 bars observed, cap −25 |
| HP ≤ 0 | `RELEGATION REVIEW` flag |

Design rationale:

- 10 × R means a clean full-stop loss costs 10 HP and a 1.5R winner
  earns 15 — ten consecutive stops without a winner puts a player at
  0. Harsh, legible, symmetric.
- The overtime rule is the "90-minute match clock" the user asked
  for, implemented at the SCORING layer: a trade that drags a week
  bleeds the player even if it eventually wins. This penalises
  capital-hogging without touching exits (see Tier C for why exits
  stay locked).
- The zero-conversion drain is the anti-Reo rule: thinking is free,
  but a striker who never shoots dies slowly and publicly.
- HP ≤ 0 flags a **relegation review** — a decision for the user at
  the weekly review, never an automatic bench. Due process, on tape.

## Tier B — more fields (multi-instrument expansion; research-gated)

Order of expansion, cheapest evidence first:

1. **Use the current three properly.** The pitch is already uneven:
   Rin plays EURUSD only, Barou USDCAD only, Chigiri EURUSD+GBPUSD —
   by design (weapons were parameterised per-symbol). Phase AF's
   grid can be re-run per symbol to answer "does Rin's weapon work
   on GBPUSD?" for pennies of compute. That is the first "new field".
2. **Metals/energy/indices on the SAME MT5 demo feed:** XAUUSD,
   XAGUSD, USOIL, USTEC (the NQ-proxy CFD) are one `--symbols` flag
   away runtime-wise — but each instrument needs (a) an H4 parquet
   history banked, (b) pip-size/session semantics audited (gold pips
   ≠ FX pips; oil has settlement gaps), (c) a pre-registered causal
   replay per agent before pitch time. No agent walks onto a new
   field unvalidated.
3. **Futures/stocks proper:** different broker plumbing entirely —
   out of scope until (2) produces at least one validated
   agent×instrument cell.

## Tier C — the trade time-limit (evidence honesty)

A hard "kill the trade at N bars" rule is an EXIT change, and exit
changes have a graveyard here: E020 (MFE-ratchet trail) DEAD, E024
(near-TP stall exit) DEAD, E026 (low-MFE time-stop) parked_low_yield —
0/45 cells alive; the aged-and-still-flat cohort fires 2–5 times per
symbol per DECADE on v1 zones. Time-stops on this family of H4
strategies have never survived validation.

Therefore: the match clock lives in the HP score (Tier A) NOW, and a
squad-specific time-stop (different exits than v1, so the E026 verdict
does not bind automatically) may be pre-registered later as its own
study using the `bars_held` distribution of causal squad trades. If it
passes floors, it graduates from scoring rule to execution rule. Not
before.

## What the scoreboard must never do

Score, flag, and publish — nothing else. No parameter mutation, no
roster mutation, no order powers. Same observe-and-draft discipline as
the Night Auditor (D144).
