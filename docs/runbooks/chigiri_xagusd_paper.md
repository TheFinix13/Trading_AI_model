# Chigiri:XAGUSD paper loop (shadow)

Phase AN-3 sealed PASS (2026-08-05). This is **observe-only paper** on
the squad live runtime — no broker orders.

## Preconditions

1. Product branch pulled to the VM (`origin/product`).
2. MT5 feed can serve **XAGUSD** H4 (symbol visible in Market Watch).
3. `platform.toml` (or CLI) sets equity=500 + field assignment.

## `platform.toml` (preferred)

```toml
[squad_live]
feed = "mt5"
aggregator = "phi41"
poll_seconds = 45
symbols = ["EURUSD", "GBPUSD", "USDCAD", "XAGUSD"]
equity = 500

[squad_live.field_assignments]
chigiri_hyoma = ["XAGUSD"]
```

## Or CLI

```powershell
.venv\Scripts\python scripts\run_squad_live.py --feed mt5 `
  --symbols EURUSD GBPUSD USDCAD XAGUSD `
  --field-assign chigiri_hyoma:XAGUSD `
  --equity 500
```

## What to expect on boot

- Log line: `field assignment: chigiri_hyoma += ['XAGUSD']`
- Log line: `field assignments active: … (equity=$500)`
- Chigiri `prepare` for XAGUSD succeeds (ATR path; no zone grammar).
- Other agents do **not** silently widen to silver.

## Judging

- Fresh tape only. Sealed 2023–2026 is consumed.
- Watch for 2025-style softness (AN fade audit flag); do not promote
  on a short lucky streak.
- Dollar PnL on silver now uses $50/pip @ 1.0 lot; pip KPIs already
  symbol-aware post-I030.

## Still gated (not this runbook)

- Real-order path (`PositionSizer` / `Setup.stop_pips`) — still FX.
- Zone agents on Tier-2 — zone-grammar pip thresholds still major-calibrated.
