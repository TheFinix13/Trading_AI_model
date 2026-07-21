# Kunigami — Rensuke Kunigami

- **id:** `kunigami`
- **canon_player:** `kunigami_rensuke`
- **playstyle_tag:** Anti-tilt discipline (retired from proposing)
- **status:** retired
- **tier:** 2
- **weapon:** `anti_tilt_recovery_discipline`
- **symbols:** EURUSD, GBPUSD, USDCAD
- **home_tf:** N/A (side-channel only)
- **signature_blurb:** Kunigami used to propose trades. He does not any more. He is retained as the squad's anti-tilt sentinel — the striker whose job is to dampen the room after a losing streak, so nobody else takes revenge trades.

## Playstyle prose

Kunigami is the squad's retired veteran. He proposed trades in
the early Phase G walk-forwards but did not meet the promotion
gate (G7 §11.12) — his signal was correlated enough with the rest
of the metavision family that keeping him added variance without
adding edge.

Rather than delete him, the doctrine retired him with a job.
Kunigami now watches every closed trade. When the recent loss
streak exceeds a defined threshold, he raises a Sentinel R5
"warning active" flag, and the aggregator dampens the whole
squad's proposal weight until the streak resets. It is a soft
circuit-breaker, not a hard stop.

That is why Kunigami stays on the roster page: the retired card
is part of the platform's honesty about which agents earned a
spot and which did not. Every squad has a bench, and every bench
has a story. His is the discipline story.

## Signature setup

Kunigami has no live entry setup. His signature is a state
transition:

```
    loss   loss   loss   loss                            (streak accumulates)
      \      \      \      \
       \______\______\______\_____
                                    \-> Kunigami warning ACTIVE
                                        - aggregator dampens weights
                                        - resets when a winner lands
```

## Evolution history

- v1.0 landed 2026-06-24 (proposing).
- v1.0 retired from proposing 2026-07-06 (G7 §11.12: did not clear
  walk-forward promotion criteria).
- v1.1 (2026-07-14) — Sentinel R5 side-channel wiring finalised;
  Kunigami permanently outside `roster.proposers` but permanently
  inside `roster.kunigami`.
