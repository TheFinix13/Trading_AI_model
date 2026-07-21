# Karasu — Tabito Karasu

- **id:** `karasu`
- **canon_player:** `karasu_tabito`
- **playstyle_tag:** News-window defender (side channel)
- **status:** standby
- **tier:** 2
- **weapon:** `news_window_defender`
- **symbols:** EURUSD, GBPUSD, USDCAD (currency-scoped)
- **home_tf:** N/A (side-channel only)
- **signature_blurb:** Karasu never takes a trade. He watches the economic calendar and tells the aggregator to reject proposals whose stops sit inside a scheduled news window. The squad's cerebral defender.

## Playstyle prose

Karasu is a side-channel agent. He is a full member of the squad
but he never appears in the proposing roster — his job is
defensive. On every tick he consults the calendar of scheduled
economic releases (NFP, CPI, ECB, BoC and so on) and marks a
window around each one as "hot".

When another striker proposes a trade, the aggregator's R7 gate
asks Karasu two questions: is a scheduled release in the next N
hours for either currency in the pair, and would the stop sit
inside the resulting slippage envelope? If both answers are yes,
Karasu vetoes the proposal and it never makes it to the ledger.

He is standby-active-by-default: he is always present, but the
gate is fail-open when the calendar cache is missing (so he
cannot cause silent outages). His work only becomes visible
when he blocks a trade; healthy days look like "Karasu vetoed 0
proposals" — and that is the win condition.

## Signature setup

Karasu has no chart setup. His signature is a *time window*:

```
    ---time-->

    ...............|<-- scheduled NFP release -->|.......
                   |<--       hot window       -->|
                                                            <-- Karasu
                                                              vetoes any
                                                              proposal whose
                                                              stop lands in
                                                              this band.
```

## Evolution history

- v1.0 landed 2026-07-20 (Phase AD pre-reg pending).
- Auxiliary status locked from day one: never in `roster.proposers`.
