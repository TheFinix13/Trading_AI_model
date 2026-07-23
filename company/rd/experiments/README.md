# company/rd/experiments/ — active-research portfolio index

Live index of every research campaign in flight or recently closed
across the workspace pair. Research Lead maintains; sync cadence is
weekly (Monday, before the intake drain) or on-demand when a
campaign transitions state.

Source-of-truth for compute artefacts:
- **Strategy / model research** →
  `finance-research-experiments/EXPERIMENTS.md` +
  `finance-research-experiments/programs/**/PROTOCOL.md +
  REPORT.md`.
- **Product-side research** → feature spec (`§Hypothesis` section
  per `literature-standards.md` §5) + measurement artefact on the
  product server.

This file is the index — not the canonical record. If a discrepancy
exists between this index and the source, the source wins; open an
intake item and re-sync.

## Strategy / model — `finance-research-experiments`

### M001 multi-agent-ensemble (branch: `multi-agent-ensemble`)

| Campaign | PROTOCOL | Status | FDR budget | Verdict | Findings link |
|---|---|---|---|---|---|
| Phase AC pitch assignment | `programs/M001_multi_agent_ensemble/experiments/phase_ac_pitch_assignment/PROTOCOL.md` (`083c0e9`) + AMENDMENT (`0ac645a`) | **closed — negative, finding published** | q=0.10, 28-test family, 3 rejects (STRICT: 1 authorising) | AC.2 A2 FAIL (delta −0.006, p=0.861); stay with A1 baseline | `company/rd/findings/2026-07-phase-ac-pitch-assignment.md` (published 2026-07-23, D089) |
| Nagi extended-panel diagnostic | (not yet pre-registered) | **candidate** | tbd | tbd | — |
| Kunigami un-retirement wiring fix | (not yet pre-registered) | **candidate** | tbd | tbd | — |
| `SquadEngineMulti` build (unblocks B1-hard / B1-soft) | (engineering pre-req, not statistical) | **candidate** | n/a | n/a | — |
| Panel-size sensitivity study (3, 4, 5, 6, 7 pairs) | (not yet pre-registered) | **candidate** | tbd | tbd | — |

### E-line (branch: `main`)

| Campaign | PROTOCOL | Status | Verdict | Findings link |
|---|---|---|---|---|
| E004 walk-forward (deployed cell chosen) | `experiments/E004_walk_forward/` | **closed — deployed** | H4/all 7/7 positive OOS windows | (deployed strategy — no separate finding doc; verdict on `/research`) |
| E017 parked_capital_cost | `experiments/E017_confidence_gated_cooldown/` | **closed — killed** | 2026-07-13 — Pareto-fails equity vs HK baseline | tbd |
| E018 stand-aside R2 | `experiments/E018_regime_aware_fade_gating/` | **closed — negative** | 2026-07-14 — R2 stand-aside not negative-expectancy | tbd |
| E019 risk-adjusted E017 redesign | `experiments/E019_confidence_recovery_riskadjusted/` | **closed — negative** | 2026-07-14 — annualised return collapses | tbd |
| E020-E025 exit-management campaign | `experiments/E020_*` through `experiments/E025_*` | **pre-registered 2026-07-20** | in-flight | (multiple pending) |

## Product-side experiments

### F013 30-day approval-review rate

| Field | Value |
|---|---|
| Feature | F013 trade approval mode |
| Hypothesis | At least 30 % of proposed live orders will be reviewed within the 5-minute approval-queue timeout. |
| Panel | First 30 days of live-mode traffic (post F013 ship AND live-mode-enabled). |
| Measurement | `approval_queue` jsonl audit: count `approved` + `rejected` events with `latency_ms < 300_000`, divide by total `submitted`. |
| Statistic | Proportion + 95 % Wilson CI. |
| Success | Proportion ≥ 0.30, lower CI bound ≥ 0.20. |
| Kill | Proportion ≤ 0.05 for 3 consecutive days → auto-timeout is too aggressive, re-scope. |
| Status | **awaiting panel** — no live-mode traffic yet (F013 ships live-mode-default-OFF per D065). |
| Findings link | `company/rd/findings/F013-30d-approval-review-rate.md` (staged) |

Product-side experiments are seeded here at feature-ship; the panel
accumulates over the reporting window; Research Lead files the
condensed finding when the panel closes.

## How to add a campaign to this index

1. If it's a strategy / model campaign — first pre-register it in
   `finance-research-experiments/programs/**/PROTOCOL.md` (or
   `experiments/E0##_.../PROTOCOL.md` for E-line). Follow the
   pre-registration rules in `literature-standards.md` §1.
2. If it's a product-side campaign — the feature spec's §Hypothesis
   section is the pre-registration. Cite it from the row here.
3. Append a row to the appropriate table above (M001 / E-line /
   product-side).
4. When the campaign closes, update the Status + Verdict cells and
   file the condensed finding at `../findings/<slug>.md` (see
   `../findings/README.md`).

## Cross-repo bridge — see also

- `finance-research-experiments/EXPERIMENTS.md` (canonical registry).
- `finance-research-experiments/PROTOCOL_DISCIPLINE.md` (research-lane
  discipline).
- `finance-research-experiments/programs/M001_multi_agent_ensemble/07-research-standards.md`
  §11 (verdict-comparator discipline).
- `company/protocols/literature-standards.md` (the company-wide
  wrapper protocol).
- `company/protocols/rd-loop.md` §5 (the intake → pre-registration
  bridge).
