# Chigiri — Hyoma Chigiri

- **id:** `chigiri`
- **canon_player:** `chigiri_hyoma`
- **playstyle_tag:** Speed continuation striker
- **status:** active
- **tier:** 2
- **weapon:** `speed_atr_breakout_continuation`
- **symbols:** EURUSD, GBPUSD
- **home_tf:** H4
- **signature_blurb:** Chigiri hunts the moment a market wakes up. When a bar closes wider than usual in the direction of the daily trend, he takes it — no wait, no fade, just the run.

## Playstyle prose

Chigiri is the pure momentum player of the squad. His entire
signal is one question: "did the last H4 bar just break out
faster than the recent average, in the direction the daily bias
already agrees with?" If yes, he takes the continuation. If no,
he does nothing.

Fast in, fast out. His target hold is roughly a trading day —
long enough to catch the follow-through, short enough that he
does not marry a trade that stalls. When markets are quiet, he
sits on the bench. When volatility picks up, he is the striker
with the most proposals.

Unlike the zone traders (Isagi, Bachira, Rin), Chigiri does not
fade zones or ask "is this exhausted?" — that is a different
question and a different striker. Chigiri asks "is this moving?"
On a monotone-up week he might be the top scorer; on a chop week
he might not trade at all, and that is by design.

## Signature setup

```
   D1 bias UP                     Wide bullish H4 close
       ^                                |
       |                                v
       |          _______              ##  <-- Chigiri enters LONG
       |        _/                     ##
       |     __/          (ATR breakout above prior high)
       |   _/
       | _/     target = 1.5R continuation
   ____/
```

## Evolution history

- v1.0 landed 2026-06-24.
- v1.1 (2026-07-10) — ATR-normalised breakout threshold added so
  the signal scales with volatility instead of firing on quiet
  chop.
- v1.2 (2026-07-14) — F20 provenance stamping added.
