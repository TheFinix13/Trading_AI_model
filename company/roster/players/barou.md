# Barou — Shoei Barou

- **id:** `barou`
- **canon_player:** `barou_shoei`
- **playstyle_tag:** USDCAD lone-wolf king
- **status:** active
- **tier:** 2
- **weapon:** `lone_wolf_baseline_zone_usdcad`
- **symbols:** USDCAD
- **home_tf:** H4
- **signature_blurb:** Barou trades one pair — USDCAD — and only that pair. He is the specialist. When USDCAD is quiet he is invisible; when USDCAD is in play he is the loudest voice in the room.

## Playstyle prose

Barou is the king of one pair. His entire symbol whitelist is
`("USDCAD",)` and by doctrine he does not cross-trade. His
production alpha is the same zone-based fade the metavision family
uses, but tuned to USDCAD's slower rhythm and wider spreads.

The v1.3 weapon (`weapon_v13=True` in the roster factory) is the
Phase Y "with-trend" variant — Barou faded against the daily trend
in earlier versions, but Phase Y walked forward with better
expectancy when he leaned *with* it on USDCAD specifically. That
is not a portfolio-wide claim; the doctrine holds only for his
one pair.

Because he is USDCAD-only, Barou goes long stretches without
proposing. He is the pinch-hitter. When USDCAD's daily trend
turns and price reaches back into an H4 zone, he takes the trade
with a longer target hold (about 32 hours) — the pair rewards
patience.

## Signature setup

```
   USDCAD only, D1 uptrend, H4 zone continuation
                          ______
   ______                /
         \              /
          \____________/  <-- H4 pullback into demand zone
                       \
                        \  Barou LONGS here with a wide 32h horizon
                         \
                          v
                          target ~1.5R follow-through
```

## Evolution history

- v1.0 landed 2026-06-24 (against-trend baseline).
- v1.2 (2026-07-06) — continuation-entry knob added (Phase X).
- v1.3 (2026-07-14) — Phase Y "with-trend" variant walked forward
  and became the roster default.
