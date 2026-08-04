# Sae v2 charter — event CONTENT, not event timing (D141)

Date: 2026-08-04 · Status: IN EXECUTION (same-day ladder progress below)

## Ladder status (updated 2026-08-04, same session as chartering)

- **S0 — DONE** (`product` commit `66c3bb7`): `NewsEvent` carries
  `forecast`/`previous` (verbatim) + `actual` (schema-ready);
  `parse_numeric` + `surprise` helpers; pinned tests. The weekly FF
  feed has no `<actual>` and no historical archive (probed live).
- **S2 — RAN (Phase AG, research repo): no arm promoted; registered
  NEAR-MISS.** All 12 pre-registered arms direction-positive on
  EURUSD IS 2015–2021; the ≥8×ATR arms earn +14–19 pips/trade with
  both sub-halves positive but n=25–28 misses the n≥30 floor;
  smaller-impulse arms flip sign 2018–2021. GBPUSD robustness
  confirms the shape. Verdict: n-starved, not random — the edge
  lives in the ~4 events/year that move violently. Hand-off: S1's
  surprise gate is exactly the instrument to identify those AT t0.
- **S1 — TOOLING READY, DATA PENDING (Phase AI):** free feeds have
  no consensus/actual history; chosen source is the MT5 terminal's
  MetaQuotes calendar on the VM (`ExportCalendarHistory.mq5` +
  `normalize_panel.py` written). One VM run + pull-back produces the
  surprise panel; protocol registers after coverage audit.
- **S3 — RAN (Phase AH, research repo): DEAD.** Dictionary hawk/dove
  ΔTone on all 87 statements: sign agreement 38%, Spearman ρ +0.14
  (wrong sign, n.s.) at 1h. Statement prose tone (dictionary-read)
  does not predict drift. Revival path: AH-2 with a frozen LLM
  rubric instead of dictionaries — needs fresh pre-registration.
- **S4 — GATED SHUT (as designed).** The presser-listening spike is
  not built: its premise (text tone carries direction) failed in S3.
  No audio engineering until an AH-2-class study passes.
- **Headline/political lane:** design note at
  `company/strategy/headline-shock-advisory-design.md` — defense-only
  architecture, observe-first arming plan, parked behind S1/AG-2.
Owner lane: research_lead → `finance-research-experiments` (fresh
pre-registrations; none of this repo's sealed data may be reused).

## Why Phase AE's FAIL does not close the Sae concept

Phase AE (D111, 2026-07-24) tested Sae's fade/ride mechanics
UNCONDITIONALLY across all 349 NFP/CPI/FOMC events 2015–2025: OOS mean
TQS 0.097 vs 0.30/0.20 floors, 28.7% wins at 1.5R. Verdict correct and
binding for that claim: "trade every event mechanically" is dead.

The user's counter-hypothesis (2026-08-04, this charter's trigger) was
never tested: **most scheduled events are non-events; the tradable edge
is conditional on the event's CONTENT — the surprise vs consensus and
the market's first reaction — not on its existence.** Sae's concept
role ("score only inside high-impact windows, quick and efficient")
requires content awareness that the current plumbing does not have:
the FF feed's `forecast`/`previous` fields are parsed out and DROPPED
by `agent/news/calendar.py::NewsEvent`, and `actual` (post-release) is
never captured at all. Karasu can see THAT news exists; nobody can see
WHAT it said.

## The design thesis to validate

News provides the WHEN and the initial direction; chart structure
provides the WHERE (targets). Sae v2 = wait for the release, read the
content (surprise) and/or the first impulse, then ride the move to
pre-existing structure targets (liquidity levels / zone edges — the
levels the user highlights manually on charts). No anticipation, no
positioning before the print.

## Study ladder (strictly ordered; each gates the next)

### S0 — data foundation (engineering, this repo, no verdict)

Capture `forecast`/`previous` from the live FF feed instead of
dropping them; capture `actual` on the post-release refresh. Build the
HISTORICAL panel for the 349-event frozen calendar: actual + consensus
for NFP (payrolls), CPI (m/m, y/y core), FOMC (rate decision vs
expected). Primary sources have actuals; archived CONSENSUS is the
data risk — if consensus can't be reconstructed cleanly pre-2020,
truncate the panel rather than backfill from memory.

### S1 — surprise-conditioned reaction (research repo, pre-reg)

Question: does |surprise z-score| predict the M15 post-release
impulse/drift, and is there a threshold above which the Phase AE
mechanics (or simple continuation) clear the TQS floors? This directly
tests "past FOMC weren't eventful": if the conditional edge exists,
the unconditional AE2 mean was diluted by duds, as hypothesized.

### S2 — follow-the-first-move (research repo, pre-reg; NO NLP needed)

The user's own described method, made mechanical: condition on the
first M5/M15 post-release impulse ≥ k×ATR; enter WITH it on the first
shallow retrace; target the next untouched structure level (zone edge
/ session high-low / swing); stop beyond the release bar extreme.
Measures: win rate at structure targets, time-to-target, MAE. This is
fully price-based, fully historical, cheap — and it is the honest
mechanisation of "we don't jump to conclusions, we wait for the news
to make a move and follow it."

### S3 — statement content direction (research repo, pre-reg; offline NLP)

FOMC statements are timestamped public text (full archive on
federalreserve.gov). Score each statement hawkish/dovish offline (LLM
+ frozen rubric; also diff-vs-previous-statement, the classic quant
feature). Question: does the score's SIGN predict 1–4h USD drift after
the 18:00 UTC statement drop? If S3 passes, the LIVE path is easy —
the statement is text at a known second; scoring latency is seconds,
well inside an M5 bar. No audio needed for this tier.

### S4 — press-conference live listening (engineering spike; gated on S3)

Only if S3 shows content direction predicts drift: streaming
transcription (e.g. Whisper) of the 18:30 presser + incremental
hawkish/dovish scoring, acting on M5/M15. Spike must produce a latency
budget (audio → transcript → score → order intent) and a cost/benefit
vs simply trading the statement text at 18:00. High engineering cost —
do not start before S3 delivers.

### Headline/political lane (Trump tweets, conference remarks) — ADVISORY ONLY

Honest assessment: unscheduled headline shocks are an HFT latency race
in the first seconds; our runtime is a 45s-poll shadow loop on
H4/M15 and will never win that race. The defensible scope is a
Karasu-style RISK ADVISORY: a headline-shock detector (newswire/social
firehose, high-credibility filter) that flattens/blocks new entries
and widens assumptions when a bomb drops — protecting positions, not
scalping the spike. Historical validation is genuinely hard (clean
timestamped headline archives are messy); this lane stays parked
behind S1–S3 and gets its own charter if pursued. It must never be a
proposer.

## Hard rules carried over

- `sae_enabled` stays False until a study on this ladder PASSES its
  pre-registered floors and the verdict is ratified on the ledger.
- No reuse of Phase AE's consumed panel for tuning; new pre-regs
  declare their own splits. Burnt windows are priors-only.
- All studies run under the CAUSAL detector semantics (D138) — any
  structure targets in S2 use post-fix `fresh_zones`.

## Interaction with the causal re-validation (D139)

D139's roster re-validation is the higher-priority research lane (the
whole squad's expectations depend on it). S0 (engineering) can proceed
in parallel; S1–S3 queue behind the D139 study unless the user
reprioritises.
