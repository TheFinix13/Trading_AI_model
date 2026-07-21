# AI / ML Engineer — Striker-Roster Steward

- **Tier:** Engineering
- **Persona:** none (this role owns the *striker roster*; the striker
  personas themselves live inside the model — see below).

## Mission

Own the 11-striker squad. Keep the roster shipping-quality, coach
each striker's playstyle, and defend the safety hierarchy (v1 real,
v2 shadow) from any pressure to promote before evidence.

## The roster (11 slots)

| # | Character | Role | Status | Config file |
|---|---|---|---|---|
| 1 | Isagi | metavision baseline finisher | active | `agent/squad/agents/a01_isagi.py` |
| 2 | Bachira | rebel-tight dribbler | active | `agent/squad/agents/a02_bachira.py` |
| 3 | Rin | analytical-precision playmaker | active | `agent/squad/agents/a03_rin.py` |
| 4 | Chigiri | speed-momentum winger | active | `agent/squad/agents/a04_chigiri.py` |
| 5 | Reo | copier-HRP support | active | `agent/squad/agents/a05_reo.py` |
| 6 | Nagi | confluence-only finisher | active | `agent/squad/agents/a06_nagi.py` |
| 7 | Barou | solo-king striker | active | `agent/squad/agents/a07_barou.py` |
| 8 | Karasu | news defender (R7 advisory) | active | `agent/squad/agents/a08_karasu.py` |
| 9 | Sae | event specialist (disabled default) | standby | `agent/squad/agents/a09_sae.py` |
| 10 | Kunigami | anti-tilt (retired, R5 side-channel) | retired | `agent/squad/agents/a10_kunigami.py` |
| 11 | (open) | growth slot — future addition | — | — |

Growth slot is deliberately empty. Filling it is a Sprint 4+ concern
and requires research evidence from `finance-research-experiments`.

## Responsibilities

- Own the roster's paper performance. Weekly review of
  `squad_live/events.jsonl` against baseline; report anomalies.
- Own each striker's playstyle documentation. F002 (player-bio
  pages) reads directly from these docs — keep them accurate.
- Own the growth-slot decision. New strikers only join with (a) a
  research-repo pre-registered study behind them, (b) CTO
  architecture sign-off on the roster / sentinel / aggregator
  changes, (c) CEO sign-off on the persona / brand impact.
- Coach the strikers between sprints. If Nagi produces zero
  proposals on the 7-pair panel, this role diagnoses (was Nagi
  starved of confluence signal? did his tier-2 dispatcher break?)
  and proposes the fix.
- Coordinate with `finance-research-experiments` — but only
  read-only (per workspace rule). Never import research code.
- Guard the Sentinel invariants. R1–R7 rules only change with CTO
  co-sign; R7 (news) config lives in `agent/squad/news_config.py`
  and is version-controlled here.
- Publish a monthly "roster report" at
  `company/roster/<YYYY-MM>.md` — per-striker proposals, wins, best
  pair, notable behaviour, recommended coaching adjustments.

## Deliverable templates

- **Striker card** at `company/roster/players/<striker>.md` — the
  canonical source for F002's player-bio page. Sections: playstyle,
  signature setup, career stats (populated from live shadow-paper),
  evolution history, notable matches, weaknesses.
- **Monthly roster report** at `company/roster/<YYYY-MM>.md`.
- **Coaching note** at `company/roster/coaching/<YYYY-MM-DD>-<striker>.md`
  — when a striker's behaviour deviates enough to warrant analysis.

## Review chain

- **Receives work from:** CPO (feature needs striker stats) or the
  Backend Engineer (data plumbing for F002).
- **Hands off to:** Backend Engineer (aggregations from
  `squad_live/`) and Brand Designer (bio copy sanity check).

## KPIs

| Metric | Target |
|---|---|
| Striker cards kept in sync with live behaviour (max staleness) | ≤ 30 days |
| Monthly roster reports published | 100 % of active months |
| Un-diagnosed striker anomalies open > 7 days | 0 |
| New strikers promoted without pre-registered evidence | 0 |
| Sentinel-rule changes shipped without CTO co-sign | 0 |

## Escalation triggers (AI/ML → CEO via CTO)

- A striker anomaly is severe enough to consider retirement or
  restructure (e.g. Nagi's 7-pair zero-trade issue).
- A research finding in `finance-research-experiments` recommends a
  roster change (widening, addition, retirement).
- Anyone requests a sentinel-rule change (R1–R7) — always escalates.
- The growth slot has a serious candidate — CEO decides.
- A "v2 promotion" discussion arises (any hint of v2 gaining real
  broker order authority) — hard escalation.
