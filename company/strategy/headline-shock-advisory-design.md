# Headline-shock advisory lane — design note (D141 annex)

Date: 2026-08-04 · Status: DESIGN ONLY (build gated on the D141
ladder producing an armed event trader worth protecting, or on the
user explicitly prioritising defense for the existing proposers).

## Scope decision (restated from D141)

Unscheduled headline shocks — presidential posts/remarks, geopolitical
bombs, surprise policy announcements — are an HFT latency race in the
first seconds. Our runtime polls every 45s on M15/H4 shadow paper. We
do not compete on reaction speed, so this lane is **defense, never a
proposer**: its only powers are (a) block new entries, (b) recommend
flatten/tighten on open positions, (c) annotate the tape so weekly
review can attribute damage to the shock.

This mirrors Karasu's scheduled-event advisory pattern (R7), which is
already wired and tested — the headline lane is "Karasu for
unscheduled events."

## Architecture (when built)

1. **Ingest:** one or more headline firehoses polled on the existing
   45s loop. Candidates, cheapest first:
   - RSS/Atom: Reuters top news, AP, Fed press feed (free, minutes
     latency — acceptable for H4/M15 defense, useless for scalping).
   - Truth Social / X via third-party API for the specific
     high-impact political accounts (paid, fragile TOS; only if the
     RSS tier proves too slow in shadow measurement).
2. **Shock classifier:** a small LLM prompt scoring each headline
   {market_moving: yes/no, currencies affected, severity 1-3} with a
   frozen rubric. Latency budget ≤ 5s per batch; cost pennies/day at
   headline volume.
3. **Advisory emission:** severity ≥ 2 on a squad symbol's currency →
   `system_status` row + Karasu-style advisory consumed by R7
   (block new proposals for N minutes) + optional flatten
   recommendation on Telegram. All parameters (N, severity floor)
   pre-registered before arming.
4. **Measurement before power:** like Sae, the lane runs
   OBSERVE-ONLY for its first weeks: advisories land on the tape but
   gate nothing. The weekly bundle then answers "would this have
   saved pips?" with real counterfactuals before R7 enforcement is
   enabled.

## Research prerequisite (why this is parked)

A historical validation needs timestamped headline archives aligned
to tick/M1 data; clean public archives for political posts are messy
and the market reaction to them is regime-dependent (the 2018-2019
tariff-tweet regime is the canonical sample). Rather than a weak
backtest, the honest path is the shadow measurement in step 4 —
which costs one LLM prompt and zero risk. Priority stays behind
S1/AG-2 per D141.
