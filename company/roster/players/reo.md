# Reo — Reo Mikage

- **id:** `reo`
- **canon_player:** `reo_mikage`
- **playstyle_tag:** Chameleon copier
- **status:** active
- **tier:** 2
- **weapon:** `chameleon_per_tick_mirror_v1`
- **symbols:** EURUSD, GBPUSD, USDCAD
- **home_tf:** H4
- **signature_blurb:** Reo does not propose his own trades. He watches his teammates and mirrors the one whose conviction and setup best fit the current regime. He is the assist king, not the goalscorer.

## Playstyle prose

Reo is the pass-master. His job is to look at every H4 thought
from every other striker and pick the one that best matches the
current regime — then re-emit it as his own with his signature.
He never generates a trade idea from scratch.

The mechanic is deliberate. When Isagi has a clean fade and Rin
does not, Reo mirrors Isagi. When Chigiri is on fire during a
volatility expansion, Reo mirrors Chigiri. The aggregator sees a
Reo proposal as a "second opinion" — a soft confirmation from the
striker whose only job is to identify the best available setup.

Reo's win rate mirrors whoever he is copying. His job on the
scoreboard is to add weight to the right proposals, not to bring
new ones. In match terms he is the striker who never scores from
open play but always turns up at the second post; on the ledger he
is the reason a marginal proposal makes it through the aggregator
into a real trade.

## Signature setup

Reo has no independent setup. His "signature" is the tick-by-tick
choice of whom to mirror:

```
     Isagi:     signal, conviction 0.65 -----+
                                              |
     Rin:       silence                       +---> Reo picks the
                                              |     best-fit peer,
     Chigiri:   signal, conviction 0.50 ------+     re-emits as
                                                     Reo's own.
```

## Evolution history

- v1.0 landed 2026-06-24.
- v1.1 (2026-07-12) — HRP-style copier heuristic added so Reo
  weights by realised recent hit-rate, not raw conviction.
- v1.2 (2026-07-14) — F20 provenance inherited from copied peer's
  thought.
