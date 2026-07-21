# Bachira — Meguru Bachira

- **id:** `bachira`
- **canon_player:** `bachira_meguru`
- **playstyle_tag:** Rebel dribbler (tight-stop specialist)
- **status:** active
- **tier:** 2
- **weapon:** `monstrous_dribble_rebel_baseline_zone`
- **symbols:** EURUSD, GBPUSD, USDCAD
- **home_tf:** H4
- **signature_blurb:** Bachira looks for the same zones Isagi looks for — but he takes them with a tighter stop and a bigger stride. High conviction, low patience.

## Playstyle prose

Bachira is the "monster in the dark" of the squad. Where Isagi
waits for the daily trend to confirm, Bachira does not need
permission. He fades the same zones, but his stop sits closer to
price and his position size accounts for the tighter risk.

He is the tight-stop rebel — the striker who is willing to be
wrong faster in exchange for asymmetric R when he is right. On the
scoreboard this looks like a slightly lower win rate than Isagi
but a chunkier average winner. On the pitch it looks like a player
who fires when nobody else does.

Bachira and Isagi share the same signal-source (production zone
alpha) but with different personality settings — `htf_align_mode`
is looser, `min_stop_pips` is lower, and ego is higher. When the
squad votes and Bachira is the only proposer, the aggregator has
learned to trust him: his fill rate is real.

## Signature setup

```
                  ___
                 /
   H4 zone tag  o           <-- shared entry with Isagi
                |
                |  Bachira's stop is HERE  ---> tight
                +-----.
                       \
                        \_       target ~1.3R
                          \_
                            \_
```

## Evolution history

- v1.0 landed 2026-06-24.
- v1.1 (2026-07-06) — "rebel-tight stop" refinement locked (Phase
  M): stop moves from structural zone-edge to tight-fixed distance.
- v1.2 (2026-07-14) — F20 provenance + F19 variance inherited from
  the shared metavision framework.
