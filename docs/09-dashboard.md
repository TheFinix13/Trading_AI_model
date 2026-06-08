# 09 — Dashboard

> Part of the numbered docs — start at [00 — Overview](00-overview.md).

A FastAPI + Jinja2 web dashboard for inspecting the agent: equity curve, trades with
full plain-English reasoning, and the kill switch.

**Code:** `agent/dashboard/app.py` (routes) and `agent/dashboard/chart_data.py`
(loads parquet, runs detectors, returns JSON for the chart). Charting uses
Lightweight Charts v4.

```bash
uvicorn agent.dashboard.app:app --reload          # local
# or bind for a VM/VPS:
python -m uvicorn agent.dashboard.app:app --host 0.0.0.0 --port 8000
# → http://localhost:8000  (or http://<host-ip>:8000)
```

## Routes

| Route | Purpose |
|-------|---------|
| `/` | Overview — balance, equity curve, recent trades (clickable rows), kill switch |
| `/trade/{id}` | Full reasoning narrative for a trade: confluences, market state at entry, top features, MAE/MFE, outcome |
| `/api/equity`, `/api/trades`, `/api/health` | JSON API |
| `POST /api/kill`, `POST /api/resume` | Kill-switch toggle |

Each trade row is clickable through to its narrative, so any trade the agent took can
be opened up and explained — the exact confluences, the market state at entry, the
scoring rationale, and the outcome.

## Related CLIs

When you don't need the browser, the same data is queryable from the terminal:

```bash
python scripts/journal_query.py --last 20          # recent trades
python scripts/journal_query.py --losers --by hour # group losses by hour
python scripts/explain.py --trade-id 14            # plain-English narrative
```

For the live-agent's per-day learning logs (markdown + JSONL), see
[06 — Learning Journal](06-learning-journal.md).
