# AI Trading Agent

A personal trading agent that trades three currency pairs (EUR/USD, GBP/USD,
USD/CAD) using one carefully tested strategy. It runs on a demo account while
it proves itself.

Early versions of this project tried to combine many popular trading ideas at
once. They looked great on paper and fell apart in practice. So everything was
torn down and rebuilt around one rule: **an idea only gets used with real money
behavior if it survives serious testing first.** Out of seven trading ideas
tested, one made the cut — and that one idea, in one specific form, is what
trades today.

## What it actually does

- It watches for price to return to **important price zones** — areas where
  the market previously made a strong move.
- When price touches such a zone *and* the bigger daily picture points the
  right way, it trades the bounce.
- It checks the market every 30 seconds, but only makes decisions when a
  4-hour candle closes. Most of the time the right decision is to do nothing.
- Expect roughly **3–5 trades per week across all three pairs combined**. It
  is deliberately picky — that's a feature, not a flaw.
- Every trade has a fixed maximum loss: about 0.5–2% of the account, sized
  automatically. The two newer pairs trade at half size until they prove
  themselves live.

## Why trust it

The strategy was not chosen because it looks clever — it was chosen because it
kept making money in tests designed to kill it:

1. **Tested alone.** Each of the seven original ideas was tested by itself,
   over ten years of price history, with proper statistics. Six failed. Zones
   survived.
2. **Tested on data it had never seen.** The strategy was built using
   2015–2022 data, then checked on 2023–2025. Most variations collapsed; one
   held up.
3. **Tested year by year.** Rolled forward through every year from 2019 to
   2025 — it stayed profitable in every single test window on EUR/USD.
4. **Tested on other currency pairs it was never tuned for.** The exact same
   settings, applied cold to GBP/USD and USD/CAD with higher trading costs,
   were profitable in 11 of 11 and 10 of 11 years respectively. A fluke
   strategy cannot pass this test — there was nothing to tune.

Two other pairs (AUD/USD, NZD/USD) were tested the same way, did worse, and
were left out. Discipline cuts both ways.

The full story of how this project got here — including the wrong turns — is
in [docs/00-journey.md](docs/00-journey.md). The current state is always
summarized in [docs/CHECKPOINT.md](docs/CHECKPOINT.md).

## Running it

Requires Python 3.11.

```bash
pip install -r requirements.txt

# Practice mode (no broker account needed):
python scripts/run_live.py --broker paper

# Demo account (MT5/Exness on Windows) — one window per pair:
python scripts/run_live.py --broker exness --symbol EURUSD --verbose
python scripts/run_live.py --broker exness --symbol GBPUSD --verbose
python scripts/run_live.py --broker exness --symbol USDCAD --verbose
```

Step-by-step Windows setup lives in
[docs/runbooks/vmware-windows.md](docs/runbooks/vmware-windows.md).

## What you'll see while it runs

- **Daily log files** in `Documents/TradingAgentLogs/`, one folder per pair,
  one file per day (e.g. `EURUSD/EURUSD_2026-06-10.log`).
- A **heartbeat message every 15 minutes** with the account balance and the
  time of the next decision — so you always know it's alive.
- A note at every 4-hour close, even when it decides not to trade.
- **Chart snapshots** of trades it almost took and trades it lost, saved as
  images next to the logs — so its behavior can be reviewed visually, not
  just trusted.

## Current status

Running on a demo account since June 2026. Live results so far are positive
but the sample is still far too small to draw conclusions — that is expected,
and it is exactly why it's on a demo account. Nothing about the strategy
changes based on individual wins or losses; changes only happen through the
same testing pipeline that built it.

## License

MIT.
