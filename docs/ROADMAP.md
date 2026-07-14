# Future implementations — parked until conditions are met

Each item below is deliberately NOT being built yet. An item becomes
actionable only when its **trigger condition** is met AND it is discussed in
chat first. Nothing here bypasses the standing rule: live behaviour changes
go through the full validation pipeline (grid → holdout → walk-forward →
pre-registered gates), and the risk constitution (max risk %, catastrophe
stops, kill switch, demotion rules) is only ever changed by a human commit.

Last updated: 2026-07-13.

## 1) Near-term research items (existing data, human-run pipeline)

### 1.1 target_rr / structural-TP study
- **What:** `target_rr=1.5` was a fixed default, never grid-swept; all
  validation is conditional on it. Test {1.5, 1.8, 2.0, 2.5} and the dormant
  `target_via_structure` mode (TP at next opposite swing).
- **Trigger:** ~50 closed live trades with extension-ladder data, AND the
  ladder report (`scripts/report_target_ladders.py`) shows a persistent
  per-source reach rate worth chasing (e.g. swing rungs ≥ 40%).
- **Constraint:** validate on fresh pairs where possible — EURUSD dev data
  is exhausted.

### 1.2 Laddered partial-TP execution (scale-out at rungs)
- **What:** book part of the position at the mechanical TP, run remainders
  to ladder rungs (e.g. 0.4 lot @ 1.5R, 0.1 @ each rung). The monitor
  scaffold exists (`partial_exit_enabled`, `_manage_partial_scaleout`) but
  stays OFF.
- **Why parked:** splitting the position changes validated expectancy
  immediately; losers carry full size while winners carry partial size.
  Runner expectancy is unknown until 1.1 produces reach-rate evidence.
- **Trigger:** 1.1 completed and a written-down scale-out policy passes the
  full pipeline.

### 1.3 EURUSD D1 candidate promotion
- **Trigger:** more OOS years accumulated; currently insufficient.

### 1.4 Portfolio USD-exposure manager
- **What:** 3 deployed pairs ≈ one correlated USD bet; worst-case combined
  risk today ~4%. Cap concurrent same-direction USD exposure.
- **Trigger:** discuss before any 4th pair is deployed, or if live drawdowns
  show correlated same-day losses.

### 1.5 FVG / liquidity-sweep confluence ideas
- **Trigger:** fresh-pair data only; EURUSD dev span is exhausted.

### 1.6 Multi-position scale-in per symbol (pyramiding)
- **What:** allow the agent to intentionally hold >1 ticket on the same
  symbol/direction (e.g. add on after price moves ≥0.5R in favor), instead
  of today's hard `max_open_positions=1` per symbol. Mechanically the
  monitor already tracks tickets independently (keyed by broker ticket:
  entry context, MFE/MAE, breakeven/trailing, `get_closed_trade` per
  ticket) — this is an execution-policy question, not a plumbing gap.
- **Why parked (2026-07-06 discussion):** it's a strategy change, not a
  config bump — today's `position_size()` sizes each ticket independently
  off account balance, so two same-direction tickets silently run 2×
  intended per-trade risk (the 5% portfolio cap is the only backstop, and
  it wasn't built for this). Also untested how it interacts with
  `PostLossGuard` (only watches revenge-adds after a loss, not size-ups
  after a win). User decision: hold off until after the M001 multi-agent
  ensemble track wraps (or pursue on a separate branch first) — "the
  system is good as it is" for now.
- **If revisited:** pre-register as an E-series study (E017 candidate) in
  `finance-research-experiments` — hypothesis, add-on trigger, risk-split
  mechanics (the add-on must take a *slice* of the existing per-trade risk
  budget, not stack an additional full slice), same
  ablation → holdout → walk-forward gate as E011-E016 before any
  `max_open_positions` / sizing code changes land here.
- **Trigger:** M001 graduation gate lands (or explicit decision to branch
  off and run this in parallel).

### 1.7 Confidence-gated risk cooldown (replaces binary kill-switch on DD halts)
- **What:** continuous loss-magnitude-scaled confidence score + shadow-
  trade recovery instead of a persistent `kill.txt` blind after daily-DD /
  circuit-breaker events — each symbol process still decides independently,
  with an account-wide drawdown gauge modulating all three (no new IPC).
- **Status (2026-07-13):** E017 validation **complete, verdict
  `parked_capital_cost`** in `finance-research-experiments`. Graduated
  confidence (GC-S) eliminates blind dead time (median 0 h vs 6,500 h for
  hard kill-switch) and cuts max DD (2.5% vs 16.9%) but **fails Pareto**
  on terminal equity vs compounding under the bootstrap ledger. **Phase 3
  blocked** — binary `kill.txt` stays; see
  `experiments/E017_confidence_gated_cooldown/STOP_NOTICE.md`.
- **If revisited:** fresh pre-reg (E018+) with a redesigned success metric
  or recovery function; no production wiring without a positive verdict.
- **Trigger:** explicit user decision to reopen after reading E017 REPORT;
  separate from the open ops question of whether daily-DD halts should
  auto-clear at UTC day rollover (still undecided, not E017 scope).

## 2) Autonomy ladder (agent self-improvement without breaking guardrails)

Framing: the validation pipeline IS the learning algorithm; autonomy means
automating its stages, never skipping them. Binding constraint is sample
size (~250 trades/yr portfolio), not decision speed — weekly human review
adds zero delay against that bottleneck.

### Level 0 — today
Automated memory (vaults, ladders, logs), human decisions. VM trades and
records; research runs on the Mac; user pastes report summaries into chat.

### Level 1a — decay monitor / automated demotion  ← build FIRST
- **What:** live process compares each cell's running live expectancy
  against its walk-forward OOS distribution; if it drops below a
  pre-registered floor (e.g. 5th percentile), auto-reduce risk_scale or
  halt the cell that day and notify. Protection-only: can cut risk, can
  never raise it.
- **Why first:** asymmetric payoff — the agent earns the right to stop
  itself before earning the right to change itself.
- **Trigger:** enough live trades per cell to define a meaningful running
  expectancy (≈30+ per cell).

### Level 1b — shadow-policy harness
- **What:** generalise the extension ladder: score N hypothetical policies
  (exits, gates, sizing variants) against live prices in parallel with zero
  lots at risk; JSONL + periodic report, same observation-only contract and
  no-behaviour-change regression test.
- **Trigger:** a concrete policy list from 1.1/1.2 worth shadowing.

### Level 1c — research runner (automated hypothesis testing)
- **What:** scheduled job reads vault/ladder summaries, enqueues
  PRE-REGISTERED hypotheses (rule-based: "if swing reach ≥40% over ≥50
  trades, sweep target_rr"), runs the existing validation scripts
  unattended, applies BH-FDR across ALL auto-generated tests, outputs a
  ranked surviving-candidates list for human sign-off.
- **Hard rules:** hypotheses and pass/fail gates written before results are
  seen; multiple-testing correction mandatory (otherwise it is an automated
  p-hacking machine); LLM/reasoning components may only generate hypotheses,
  never render verdicts.
- **Trigger:** Level 1a running + recurring backlog of vault hypotheses that
  weekly manual review can't keep up with.

### Level 2 — auto-promotion inside a constitutional envelope
- **What:** candidates passing pre-registered gates auto-deploy at tiny
  scale (0.1×) with pre-written demotion rules. The learner can never edit
  the constitution (risk envelope, validation thresholds, promotion/demotion
  rules) — human commit only.
- **Trigger:** Level 1c proven over months; realistically only worth it at
  ~30 pairs, not 3. May never be needed.

### Level 3 — online adaptation (narrow scope only)
- **What:** continuous updates ONLY for high-sample fast-feedback quantities:
  slippage/fill models, conviction calibration within the existing sizing
  band. Never entry/exit logic — ~66 trades/yr/pair cannot support online
  edge updates.
- **Trigger:** live fill data shows systematic deviation from modelled costs.

## 3) Infrastructure conveniences (no evidence impact)

- **Vault transport:** VM syncs `TradingAgentLogs/` to a cloud folder the
  Mac can read, so reports/JSONLs are readable in-session without manual
  copying. Changes who carries the data, not who decides.
- **Broker-reject vault tag:** order rejections after all gates pass (e.g.
  retcode=10027 on 2026-06-11) are currently invisible to the near-miss
  vault; add a `broker_reject` reason so the resolver scores what the miss
  cost.
