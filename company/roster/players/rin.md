# Rin — Rin Itoshi

- **id:** `rin`
- **canon_player:** `itoshi_rin`
- **playstyle_tag:** Cold geometric precision
- **status:** active
- **tier:** 2
- **weapon:** `precision_geometry_strict_rr_zone`
- **symbols:** EURUSD
- **home_tf:** H4
- **signature_blurb:** Rin trades only EURUSD, only when the geometry is clean, and only when the risk-to-reward is a hard 2 R. He is the striker who says "no" the most and the striker who wins the highest percentage.

## Playstyle prose

Rin is the coldest player on the squad. He watches EURUSD and
EURUSD only. He is not a generalist and he does not pretend to be
one — the doctrine (`03-agent-rin.md`) explicitly forbids him from
trading anything he has not studied in depth.

His filter is the strictest in the roster. Stops must be at least
twenty pips deep (a "structural cleanliness floor" that keeps him
from taking shape-less setups). The take-profit must sit at exactly
2 R from entry — not 1.8 R, not 1.5 R. If either constraint fails,
Rin passes. When both hold, his conviction jumps because the trade
matched his mental picture perfectly.

The result is a low proposal count and a high acceptance rate. Rin
is not the striker who scores the most goals on the season; he is
the striker whose goals matter the most in a knockout round. When
the aggregator is trying to decide between conflicting proposals,
a Rin proposal is a signal that the setup is genuinely clean.

## Signature setup

```
     H4 zone touch on EURUSD
             |
             v
    _______  o
              \   entry
               \  |
                \ |   stop >= 20 pips (structural floor)
                 \|
                  +----- 2R target ------+
                                          \
                                           target
```

## Evolution history

- v1.0 landed 2026-06-24.
- v1.1 (2026-07-07) — precision-geometry stop-floor (20 pips) and
  strict-2R take-profit locked. Rin stops taking sub-structural
  fades.
- v1.2 (2026-07-14) — F20 provenance stamping added.
