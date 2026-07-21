# Isagi — Yoichi Isagi

- **id:** `isagi`
- **canon_player:** `isagi_yoichi`
- **playstyle_tag:** Metavision zone reader
- **status:** active
- **tier:** 1
- **weapon:** `metavision_seed_zone_d1_against`
- **symbols:** EURUSD, GBPUSD, USDCAD
- **home_tf:** H4
- **signature_blurb:** Isagi is the striker who sees the whole field. He waits for price to touch a fresh supply / demand zone and only fires when the daily bias points the other way — a counter-trend fade with a story.

## Playstyle prose

Isagi is the anchor of the squad. His job is not to be the loudest
gun; it is to see the pitch first. Every H4 close, he asks the same
two questions: did price just tag a zone, and is the daily trend
pointing the *other* way? If both answers are yes, he takes the
fade. If either is no, he watches.

The metavision part is not marketing. Isagi reads every other
striker's H4 thought before deciding. When his own signal fires and
his teammates are already leaning the same direction, he plays with
more conviction; when they lean the opposite way, he trims it back.
This is F19 conviction variance in code terms — Phase S doctrine —
but the story on the field is straightforward: he trusts the room.

Because he trades against the daily trend, Isagi does not chase.
His trades are patient, structural, and often start with a small
adverse move before the fade develops. When it works, the profit
comes from a tight stop and a 1.5 R target; when it does not, the
loss is capped by a hard structural stop at the zone edge.

## Signature setup

```
   D1 uptrend                     H4 zone tag on the way up
        \                          |
         \                         v
   ...........o    <---- price touches supply zone
                     __
                    /
              ____/       <---- Isagi fades DOWN, target 1.5R
            _/
          _/
        _/
```

## Evolution history

- v1.0 landed 2026-06-24 — E004 walk-forward gate cleared
  (+11.34 median pips / trade, 7/7 OOS).
- v1.1 (2026-07-14) — F20 provenance stamping added (per-bar ATR
  and swing range so dispersion measurements are real).
- v1.2 (2026-07-14) — F19 metavision variance shipped; conviction
  now moves with peer alignment.
