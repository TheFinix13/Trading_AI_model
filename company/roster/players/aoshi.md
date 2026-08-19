# Aoshi — Aoshi Tokimitsu

- **id:** `aoshi`
- **canon_player:** `aoshi_tokimitsu`
- **playstyle_tag:** Event-window specialist (disabled by default)
- **status:** standby
- **tier:** 1
- **weapon:** `event_release_impulse`
- **symbols:** EURUSD, GBPUSD, USDCAD
- **home_tf:** M5
- **signature_blurb:** Aoshi is the elite specialist who only fires in the minutes immediately after a scheduled economic release. He is deliberately disabled by default; the squad turns him on only when the research pre-registration for event-driven trading clears.

> **Renamed 2026-08-19.** This player shipped as `sae_itoshi` from
> 2026-07-20 until 2026-08-19. The M001 roster assigns the A9 slot to
> Aoshi Tokimitsu — canon brief "macro-event-only vol-breakout (FOMC /
> NFP / CPI)", which is verbatim this weapon — while "Sae Itoshi (foil)"
> is the frozen *adversarial* baseline the squad must beat. Running the
> striker under the opponent's name made every report ambiguous between
> a player and a benchmark. Sealed Phase AE artifacts keep the old id by
> design; the decision is recorded in the M001 evolution ledger.

## Playstyle prose

Aoshi is the roster's only calendar-aware striker, and the one the squad
has the least favourable evidence on — his weapon
(`event_release_impulse`) fires inside a narrow post-release window,
not the roster's usual H4 cadence.

His config carries `sae_enabled=False` by default (the config key keeps
its original name; only the player identity was renamed). The
`SquadRoster` still instantiates him so the engine can ping him for
diagnostics, and the live watchdog now passes `--enable-sae` so he is in
the lineup to be **observed**.

When he does trade, he trades fast. His target hold is six hours and his
conviction is front-loaded — he assumes the release moves the market and
either fades a failed impulse or rides a retained one. If the release
does not move the market, he does not trade. There is no "waiting to
see" version of him.

## Signature setup

```
     ------ NFP release moment ------
                    |
                    v
                    ##  release impulse bar
                    ##
                    ##
                   /
                  /   <-- fade a failed impulse, or ride a
                 /       retained one; 6h target hold.
                /
               /
```

## Evidence status — read this before trusting a trade

Phase AE (research repo, verdict sealed 2026-07-24) evaluated this
weapon over 349 high-impact USD events, 2015–2025, and returned
**FAIL**: 28.7 % win rate against a fixed 1.5R target (breakeven 40 %),
OOS mean TQS 0.097 against a 0.30 floor, mean −4.16 pips/trade across 87
trades. The two mechanics are not equally bad — fade is near breakeven
at −0.13 pips/trade over 26 trades, while ride is −5.88 over 61 and
makes up 78 % of the book.

He is on the pitch as **telemetry, not as a trusted trader**. Expect a
losing event book until a redesign clears its own pre-registration; the
defeat note and the registered improvement plan live at
`programs/M001_multi_agent_ensemble/reviews/sae_itoshi_v1_defeat.md` in
the research repo.

## Evolution history

- v1.0 authored 2026-07-20 (Phase AE pre-reg pending).
- Phase AE verdict **FAIL** sealed 2026-07-24; not armed for the
  2026-08-07 NFP.
- Enabled live-shadow 2026-08-13 as a deliberate observability decision;
  the FAIL verdict stands unrevised.
- Renamed `sae_itoshi` → `aoshi_tokimitsu` 2026-08-19. Tier 0
  v1-readiness plumbing (F19/F20/F21, conviction function, time stop)
  landed in the research sim the same day as `a09_aoshi_v2.py`; the
  production agent still runs the v1 mechanics.
- `sae_enabled=False` remains the default in
  `agent/squad/sae_config.py`; the VM watchdog opts in with
  `--enable-sae`.
