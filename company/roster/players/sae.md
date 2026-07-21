# Sae — Sae Itoshi

- **id:** `sae`
- **canon_player:** `sae_itoshi`
- **playstyle_tag:** Event-window specialist (disabled by default)
- **status:** standby
- **tier:** 1
- **weapon:** `event_release_impulse`
- **symbols:** EURUSD, GBPUSD, USDCAD
- **home_tf:** M5
- **signature_blurb:** Sae is the elite specialist who only fires in the minutes immediately after a scheduled economic release. He is deliberately disabled by default; the squad turns him on only when the research pre-registration for event-driven trading clears.

## Playstyle prose

Sae is Rin's older brother in the canon, and doctrinally he is the
striker with the highest ego on the roster. In code terms he is
also the one the squad has the least evidence on — his weapon
(`event_release_impulse`) fires inside a narrow post-release
window on M5, not the roster's usual H4 cadence.

His config carries `sae_enabled=False` by default. The
`SquadRoster` still instantiates him so the engine can ping him
for diagnostics, but he does not appear in `roster.proposers`
until Phase AE pre-registration finalises the promotion criteria.

When he does trade, he trades fast. His target hold is six hours,
his stops are event-slippage-aware, and his conviction is
front-loaded — Sae assumes the release moves the market and rides
the first impulse. If the release does not move the market, he
does not trade. There is no "waiting to see" version of Sae.

## Signature setup

```
     ------ NFP release moment ------
                    |
                    v
                    ##  M5 bar 1: release impulse
                    ##
                    ##
                   /
                  /   <-- Sae LONGS or SHORTS with the impulse
                 /       direction; 6h target hold.
                /
               /
```

## Evolution history

- v1.0 authored 2026-07-20 (Phase AE pre-reg pending).
- `sae_enabled=False` is the default in `agent/squad/sae_config.py`
  and remains so until the pre-registered evaluation ships an
  "alive" verdict.
