---
id: I020
source: post-mortem
submitter: "self-observation"
submitted_at: 2026-07-28T17:20:00Z
classification: RESEARCH-QUESTION
priority: P2
status: routed
route: research
linked_features: []
linked_decisions: [D130]
linked_experiments: ["M001 Phase AD.2 (pre-reg DRAFT, research repo)"]
contact: null
resolved_at: null
history:
  - stage: filed
    at: 2026-07-28T17:20:00Z
    by: user_advocate
    note: "Surfaced during the I018 grid investigation: tape timestamps
      are bar OPEN labels, so Karasu's ±15-min window is anchored ~4 h
      before the actual entry moment on H4."
  - stage: routed
    at: 2026-07-28T17:20:00Z
    by: research_lead
    note: "CEO said 'proceed and start the research'. Pre-registration
      DRAFT opened in finance-research-experiments as M001 Phase AD.2
      (karasu window anchor semantics). No trading-agent code change
      until that study reports."
---

# I020 — Which moment should Karasu's news window protect?

## The question

`SquadEngine` evaluates Karasu with `as_of = bar.time` — the H4 bar's
**open** label. On the live tape a bar labelled 07:00 UTC is evaluated
at its close (~11:00 UTC), and any resulting entry executes after
that. So today's ±15-min blackout window protects the **start of the
just-closed bar**, roughly 4 hours before the moment a proposal would
actually enter the market. Three candidate semantics:

- **A (current):** anchor at bar-open label. Protects a moment that
  is already 4 h in the past at decision time.
- **B (entry-anchored):** anchor at bar close = the actual decision /
  entry moment (open + 4 h).
- **C (forward window):** protect the upcoming holding window —
  entry moment plus a look-ahead horizon.

## Concrete instance from this week

Jul 24: Karasu's advisory "French Flash Manufacturing PMI in +15 min"
fired on the 07:00-open bar. Relative to the open label the release
(07:15 UTC) was imminent; relative to the real decision moment
(~11:00 UTC close) it had already happened ~3 h 45 m earlier. Under
semantics B that advisory (and any R7 gating it fed) would not fire —
while a release at, say, 11:10 UTC would be *missed* by A but caught
by B.

## Why it's a research question, not a bug fix

The Phase AD pre-registration locked the ladder knobs (±15 min,
block/scale) against a walk-forward panel that used semantics A
throughout — silently changing the anchor in the live path would
break parity with the validated sim and constitute post-freeze
retuning. Whether B (or C) actually reduces drawdown better than A
must be measured on the panel, not asserted.

## Routing

Pre-registration DRAFT lives at
`finance-research-experiments/programs/M001_multi_agent_ensemble/experiments/phase_ad2_karasu_window_semantics/PROTOCOL.md`
(untracked working-tree draft, standard M001 WIP pattern; commits to
the research repo need that session's declared branch). Stage 1 is a
cheap descriptive audit (how often do A/B/C disagree on the frozen
calendar fixture); Stage 2 (counterfactual replay of the panel ledger
under B) only runs if disagreement is material. No trading-agent code
change lands until the study reports and the CEO ratifies.
