# Data sources

You have three ways to get historical bars into the parquet cache. They can be mixed —
all paths converge on the same `data/parquet/<SYMBOL>_<TF>.parquet` files that the
backtester reads.

## Quick comparison

| Source | Free | Setup | History | Quality | When to use |
|---|---|---|---|---|---|
| **Dukascopy** | yes | one pip install (already in deps) | 2003+ | broker-grade | Default for backtesting on Mac |
| **MT5 export (Exness)** | yes | install MT5, manual export | as deep as Exness server | broker-exact | Closest to live; do this once you have an Exness account |
| **yfinance** | yes | nothing | 5y D1, 730d intraday | retail-grade, occasional gaps | Quick smoke test only |

## 1. Dukascopy (default)

Pulls broker-grade historical bars from Dukascopy's free public datafeed. No account,
no API key. Already wired in.

```bash
python scripts/download_data.py --symbol EURUSD --years 5 --source dukascopy
```

This downloads bid candles for EURUSD across `D1`, `H4`, `H1`, `M15` and caches them.
The first run takes a couple of minutes per timeframe (Dukascopy serves data hour-by-hour
internally); subsequent runs use the cache.

If you omit `--source`, the loader tries MT5 (if Windows + Exness logged in), then
Dukascopy, then falls back to yfinance.

## 2. MT5 export from Exness — the closest match to live

The data the bot will actually trade on is Exness's MT5 feed. To make your backtest a
bit-for-bit mirror of live:

1. Install **MT5 from your Exness Personal Area** (works on Mac as well as Windows).
2. Log into your demo or live account.
3. In MT5: `View -> History Center` (or `Ctrl+U`).
4. Pick `EURUSD` and the timeframe (e.g., H1).
5. Click **Download** to pull as much history as Exness's server provides (usually 5–10 years).
6. Click **Export** -> save as CSV. Export each timeframe (D1, H4, H1, M15) separately.
7. Drop the CSVs anywhere on disk, then import:

    ```bash
    python scripts/import_csv.py path/to/EURUSD_H1.csv --symbol EURUSD --timeframe H1
    python scripts/import_csv.py path/to/EURUSD_H4.csv --symbol EURUSD --timeframe H4
    python scripts/import_csv.py path/to/EURUSD_D1.csv --symbol EURUSD --timeframe D1
    python scripts/import_csv.py path/to/EURUSD_M15.csv --symbol EURUSD --timeframe M15
    ```

The importer auto-detects MT5's CSV format (Date,Time,Open,High,Low,Close,Volume) and
HistData's (semicolon-delimited).

If you want to be belt-and-braces: import MT5 CSVs and then run `download_data.py
--source dukascopy` afterwards. The importer merges; later upserts will overlay any
missing periods.

## 3. yfinance (fallback)

```bash
python scripts/download_data.py --symbol EURUSD --years 5 --source yfinance
```

Use only when nothing else is available. Yahoo caps intraday history at 730 days, and
forex data has occasional gaps around holidays.

## Verifying what's in the cache

```bash
python -c "
from agent.data.source import ParquetCache
from agent.types import Timeframe
from agent.config import load_config
cfg = load_config()
cache = ParquetCache(cfg.data_dir)
for tf in [Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15]:
    df = cache.load('EURUSD', tf)
    if df.empty:
        print(f'{tf.value}: empty')
    else:
        print(f'{tf.value}: {len(df)} bars from {df.index.min().date()} to {df.index.max().date()}')
"
```

## Source quality vs Exness live spreads

Dukascopy and Exness pull from different liquidity providers. For EURUSD specifically the
mid-prices are within ~0.1 pip during liquid hours and 1–2 pips around session opens and
news. **For our daily/4H confluence strategy this is well within tolerance** because:

- Our stops are 30+ pips structural, not 1–2 pip scalps.
- The structural levels (zones, FVGs, BOSes) sit in the same places regardless of source.
- The backtester models its own spread + slippage on top, so the data source's spread
  doesn't matter for entry/exit simulation.

If you ever build an M15-or-tighter strategy, switch to MT5-exported Exness data so the
spread distribution matches reality.
