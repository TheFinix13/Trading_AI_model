# Nagi — Seishiro Nagi

- **id:** `nagi`
- **canon_player:** `nagi_seishiro`
- **playstyle_tag:** Confluence-only perfect trap
- **status:** active
- **tier:** 2
- **weapon:** `perfect_trap_chemical_reaction_v1`
- **symbols:** EURUSD, GBPUSD, USDCAD
- **home_tf:** H4
- **signature_blurb:** Nagi does not trade unless three other strikers agree on the same coordinate. He is the confluence detector — the striker who only leaves the bench when the setup is unanimous.

## Playstyle prose

Nagi is the laziest striker on paper and the most efficient in
practice. He does not look at charts. He looks at his teammates'
Coordinate boxes — the price-time-regime envelopes each striker
publishes on every H4 close.

If three or more of those boxes overlap in price band, time
window, and regime predicate at the same moment, Nagi calls it a
"chemical reaction" and fires a trade at that overlap. The stop
is the tightest of the participating peers' stops; the target is
the median of the participating peers' targets. If overlap does
not occur, he does not trade.

Nagi's proposal frequency is the lowest in the roster, but his
average conviction is the highest. When he speaks, the aggregator
listens — a Nagi proposal is the closest thing the squad has to a
"this setup is real" veto.

## Signature setup

```
        Isagi box:   [====================]
        Rin box:            [========]
        Chigiri box: [==========]
                            ^^^^^^
                            overlap = 3 strikers agree
                                |
                                v
                             Nagi fires here.
```

## Evolution history

- v1.0 landed 2026-06-24.
- v1.1 (2026-07-08) — chemical-reaction overlap detector wired to
  the F13 workspace so peer coordinates are read live.
- v1.2 (2026-07-14) — F20 provenance + F19 variance inherited via
  the confluence peers.
