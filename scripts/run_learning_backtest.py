"""Learning backtest — exercise the reaction engine, risk-based sizing and the
online performance memory day-by-day over historical data.

Unlike ``scripts/run_backtest.py`` (which measures the legacy rule engine), this
script mirrors what the LIVE agent now does:

  * the :class:`ReactionEngine` evaluates committed price action every bar,
  * the :class:`PositionSizer` sizes each trade by risk % of the *current*
    equity, scaled by conviction (a leverage mindset, not fixed lots),
  * the :class:`PerformanceMemory` updates trade-by-trade so each day's results
    feed the next day's conviction (the learning loop is genuinely exercised),
  * a per-day archive of markdown + JSONL logs is written under
    ``data/journal/backtest/`` — distinct from the live daily logs.

Run:
    PYTHONPATH=. .venv/bin/python scripts/run_learning_backtest.py \
        --years 2 --start-balance 100 --leverage 1000 --reset

The equity curve, per-day learning summary and the final per-signature
expectancy table are printed so a quant can SEE the learning behaviour.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.config import PROJECT_ROOT, load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.journal.live_journal import LiveJournal
from agent.journal.performance_memory import PerformanceMemory, make_signature
from agent.live.position_sizer import PositionSizer, SymbolConstraints
from agent.reaction.engine import LevelOfInterest, ReactionEngine
from agent.rules.engine import precompute
from agent.types import Bar, Direction, Timeframe

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("run_learning_backtest")

PIP = 0.0001


def load_bars(cfg, symbol: str, timeframe: Timeframe, years: int) -> list[Bar]:
    loader = BarLoader(cache_root=cfg.data_dir)
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=years * 365)
    df = loader.get(symbol, timeframe, start, end, refresh=False)
    return df_to_bars(df, timeframe)


def build_levels(bars: list[Bar], i: int, ctx, swing_window: int = 60) -> list[LevelOfInterest]:
    """Causal level set for the reaction engine: daily/weekly anchors as-of the
    bar plus the most recent swing extremes. No look-ahead — only bars[:i]."""
    levels: list[LevelOfInterest] = []
    if ctx.daily_levels and i < len(ctx.daily_levels):
        dl = ctx.daily_levels[i]
        try:
            for label, price in dl.levels_dict().items():
                if price:
                    levels.append(LevelOfInterest(price, label, "daily"))
        except Exception:
            pass
    window = bars[max(0, i - swing_window):i]
    if window:
        levels.append(LevelOfInterest(max(b.high for b in window), "recent_high", "swing"))
        levels.append(LevelOfInterest(min(b.low for b in window), "recent_low", "swing"))
    return levels


def simulate_trade(
    bars: list[Bar],
    entry_index: int,
    direction: Direction,
    entry: float,
    stop: float,
    tp: float,
    *,
    spread_pips: float,
    slippage_pips: float,
    move_be_at_r: float,
    max_hold_bars: int,
) -> dict:
    """Walk the trade forward bar-by-bar (intrabar SL/TP, conservative: stop
    wins ties). Returns exit price, reason, pip P&L, R-multiple and MAE/MFE."""
    stop_pips = abs(entry - stop) / PIP
    is_long = direction == Direction.LONG
    cur_stop = stop
    mae_pips = 0.0
    mfe_pips = 0.0
    cost_pips = spread_pips + slippage_pips

    end = min(len(bars), entry_index + 1 + max_hold_bars)
    for j in range(entry_index + 1, end):
        b = bars[j]
        if is_long:
            fav = (b.high - entry) / PIP
            adv = (entry - b.low) / PIP
        else:
            fav = (entry - b.low) / PIP
            adv = (b.high - entry) / PIP
        mfe_pips = max(mfe_pips, fav)
        mae_pips = max(mae_pips, adv)

        # Move to break-even once price has run move_be_at_r in our favour.
        if move_be_at_r > 0 and stop_pips > 0 and fav >= move_be_at_r * stop_pips:
            cur_stop = entry

        hit_stop = (b.low <= cur_stop) if is_long else (b.high >= cur_stop)
        hit_tp = (b.high >= tp) if is_long else (b.low <= tp)
        if hit_stop:
            exit_price = cur_stop
            reason = "be" if cur_stop == entry else "sl"
            pnl_pips = ((exit_price - entry) if is_long else (entry - exit_price)) / PIP
            pnl_pips -= cost_pips
            return _exit(exit_price, reason, pnl_pips, stop_pips, mae_pips, mfe_pips, b.time)
        if hit_tp:
            exit_price = tp
            pnl_pips = ((exit_price - entry) if is_long else (entry - exit_price)) / PIP
            pnl_pips -= cost_pips
            return _exit(exit_price, "tp", pnl_pips, stop_pips, mae_pips, mfe_pips, b.time)

    # Time stop: close at the last bar's close.
    last = bars[min(end, len(bars)) - 1]
    exit_price = last.close
    pnl_pips = ((exit_price - entry) if is_long else (entry - exit_price)) / PIP - cost_pips
    return _exit(exit_price, "time", pnl_pips, stop_pips, mae_pips, mfe_pips, last.time)


def _exit(exit_price, reason, pnl_pips, stop_pips, mae, mfe, time) -> dict:
    r = (pnl_pips / stop_pips) if stop_pips > 0 else 0.0
    return {
        "exit_price": exit_price, "exit_reason": reason, "pnl_pips": pnl_pips,
        "r_multiple": r, "mae_pips": mae, "mfe_pips": mfe, "exit_time": time,
        "exit_index_time": time,
    }


def forward_outcome(bars, i, direction, atr, cfg, n_bars: int) -> dict | None:
    """What WOULD have happened to a declined setup over the next N bars, using a
    nominal ATR stop and the reaction config's fallback R:R target. Conservative:
    a same-bar stop+target tie counts as the stop. Returns verdict + excursions."""
    stop_dist = atr * cfg.reaction.stop_atr_mult
    if stop_dist <= 0:
        return None
    target_dist = stop_dist * cfg.reaction.fallback_rr
    entry = bars[i].close
    is_long = direction == Direction.LONG
    end = min(len(bars), i + 1 + n_bars)
    max_fav = 0.0
    max_adv = 0.0
    for j in range(i + 1, end):
        b = bars[j]
        if is_long:
            fav = b.high - entry
            adv = entry - b.low
        else:
            fav = entry - b.low
            adv = b.high - entry
        max_fav = max(max_fav, fav)
        max_adv = max(max_adv, adv)
        if adv >= stop_dist:
            return {"verdict": "loss", "won": False,
                    "max_fav_r": round(max_fav / stop_dist, 2),
                    "max_adv_r": round(max_adv / stop_dist, 2)}
        if fav >= target_dist:
            return {"verdict": "win", "won": True,
                    "max_fav_r": round(max_fav / stop_dist, 2),
                    "max_adv_r": round(max_adv / stop_dist, 2)}
    return {"verdict": "open", "won": False,
            "max_fav_r": round(max_fav / stop_dist, 2),
            "max_adv_r": round(max_adv / stop_dist, 2)}


def run(args) -> None:
    cfg = load_config(args.config)
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.timeframe)
    bars = load_bars(cfg, symbol, tf, args.years)
    if args.max_bars:
        bars = bars[-args.max_bars:]
    log.info("Loaded %d bars of %s %s", len(bars), symbol, tf.value)
    if len(bars) < 200:
        log.error("Not enough bars. Run scripts/download_data.py first.")
        return

    log.info("Precomputing detector context over %d bars...", len(bars))
    ctx = precompute(bars, cfg)

    engine = ReactionEngine(cfg.reaction)
    sizer = PositionSizer(min_risk_pct=args.risk_min, max_risk_pct=args.risk_max)
    journal_root = PROJECT_ROOT / "data" / "journal" / "backtest"
    journal = LiveJournal(root=journal_root, scope="backtest")
    perf_path = journal_root / "perf_memory.json"
    if args.reset:
        journal.archive_existing()
        if perf_path.exists():
            perf_path.unlink()
    perf = PerformanceMemory(perf_path, autosave=False)

    constraints = SymbolConstraints(
        min_lot=cfg.risk.lot_min, lot_step=cfg.risk.lot_step,
        max_lot=cfg.risk.lot_hard_cap, pip_value_per_lot=cfg.backtest.pip_value_per_lot,
    )
    pip_value = cfg.backtest.pip_value_per_lot

    equity = args.start_balance
    peak_equity = equity
    max_dd = 0.0
    trades: list[dict] = []
    open_until = 0  # index until which we're "in a trade" (no new entries)

    cur_day = ""
    day_start_equity = equity
    day_trades = 0
    day_pnl = 0.0

    warmup = max(args.warmup, 30)
    i = warmup
    while i < len(bars) - 1:
        bar = bars[i]
        day = bar.time.strftime("%Y-%m-%d")
        session = ctx.session_labels[i] if i < len(ctx.session_labels) else ""

        # Day rollover: flush a learning summary + calibration roll-up.
        if day != cur_day:
            if cur_day:
                _log_day_summary(journal, cur_day, day_trades, day_pnl,
                                 day_start_equity, equity, perf)
                journal.log_daily_rollup(cur_day)
            cur_day = day
            day_start_equity = equity
            day_trades = 0
            day_pnl = 0.0
            journal.start_day(
                day, htf_bias="n/a (reaction backtest)",
                anticipated_view="reaction engine drives entries in this backtest",
                reactive_view="committed displacement+momentum at causal levels",
                mode="reaction",
            )

        if i < open_until:
            i += 1
            continue

        atr = ctx.atr_by_index.get(i, 0.0)
        if atr <= 0:
            i += 1
            continue

        closed = bars[:i + 1]  # bars up to and including i (the bar we react to)
        levels = build_levels(bars, i, ctx)
        daily = ctx.daily_levels[i] if i < len(ctx.daily_levels) else None
        assess = engine.assess(
            closed, atr=atr, levels=levels, daily_levels=daily, swings=ctx.swings,
        )
        if not assess.fired or assess.signal is None:
            # Log directional near-misses (detected, not taken) with a would-have
            # outcome so an over-strict filter is visible day-by-day.
            if (assess.direction is not None and assess.level is not None
                    and assess.conviction >= 0.5 * assess.threshold):
                fo = forward_outcome(bars, i, assess.direction, atr, cfg,
                                     args.decline_lookahead)
                sigd = make_signature("Reaction", assess.direction.value, session,
                                      None, "reaction")
                note = (f"{fo['verdict']} next {args.decline_lookahead}b "
                        f"(+{fo['max_fav_r']}R/-{fo['max_adv_r']}R)" if fo else "")
                journal.log_declined(
                    day, signature=sigd,
                    reason=assess.rejection or "below threshold", source="reaction",
                    conviction=assess.conviction, direction=assess.direction.value,
                    would_have_won=(fo["won"] if fo else None), would_have_note=note,
                )
            i += 1
            continue

        sig = assess.signal
        # Online learning: nudge conviction by this signature's track record.
        signature = make_signature("Reaction", sig.direction.value, session, None, "reaction")
        adj = perf.conviction_adjustment(signature)
        conviction = max(0.0, min(1.0, sig.conviction + adj))

        sizing = sizer.calculate_lot(
            balance=equity, stop_distance_pips=sig.stop_pips, conviction=conviction,
            pip_value=pip_value, price=sig.entry, leverage=args.leverage,
            free_margin=equity, constraints=constraints,
        )
        if sizing.lot <= 0:
            # A fired signal we couldn't size (risk/margin) is also a decline.
            fo = forward_outcome(bars, i, sig.direction, atr, cfg,
                                 args.decline_lookahead)
            note = (f"{fo['verdict']} next {args.decline_lookahead}b "
                    f"(+{fo['max_fav_r']}R/-{fo['max_adv_r']}R)" if fo else "")
            journal.log_declined(
                day, signature=signature,
                reason=f"sizing produced 0 lots ({sizing.capped_by})",
                source="reaction", conviction=conviction,
                direction=sig.direction.value,
                would_have_won=(fo["won"] if fo else None), would_have_note=note,
            )
            i += 1
            continue

        result = simulate_trade(
            bars, i, sig.direction, sig.entry, sig.stop, sig.take_profit,
            spread_pips=cfg.backtest.spread_pips, slippage_pips=cfg.backtest.slippage_pips,
            move_be_at_r=cfg.backtest.move_be_at_r, max_hold_bars=args.max_hold,
        )

        pnl = sizing.lot * result["pnl_pips"] * pip_value - cfg.backtest.commission_per_lot * sizing.lot
        equity += pnl
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        max_dd = max(max_dd, dd)
        day_pnl += pnl
        day_trades += 1

        ticket = len(trades) + 1
        journal.log_trade_entry(
            ticket=ticket, time=bar.time, symbol=symbol, direction=sig.direction.value,
            source="reaction", strategy="Reaction", signature=signature, entry=sig.entry,
            stop=sig.stop, take_profit=sig.take_profit, lot=sizing.lot,
            conviction=conviction, sizing_summary=sizing.summary(), rationale=sig.rationale,
            reaction_components=sig.components.as_dict(),
        )
        journal.log_trade_exit(
            ticket=ticket, time=result["exit_time"], exit_price=result["exit_price"],
            exit_reason=result["exit_reason"], pnl=pnl, pnl_pips=result["pnl_pips"],
            r_multiple=result["r_multiple"], mae_pips=result["mae_pips"],
            mfe_pips=result["mfe_pips"], signature=signature,
            conviction=conviction, source="reaction",
        )
        perf.record(signature, result["r_multiple"])

        trades.append({
            "ticket": ticket, "time": bar.time, "direction": sig.direction.value,
            "conviction": conviction, "adj": adj, "lot": sizing.lot, "pnl": pnl,
            "r": result["r_multiple"], "reason": result["exit_reason"],
            "equity": equity, "signature": signature,
        })

        # Find the exit bar index to block re-entry until the trade is closed.
        open_until = i + 1
        for j in range(i + 1, min(len(bars), i + 1 + args.max_hold)):
            if bars[j].time >= result["exit_time"]:
                open_until = j + 1
                break
        i = open_until

    if cur_day:
        _log_day_summary(journal, cur_day, day_trades, day_pnl,
                         day_start_equity, equity, perf)
        journal.log_daily_rollup(cur_day)
    perf.save()

    _print_summary(trades, args.start_balance, equity, max_dd, perf, journal_root,
                   journal)


def _log_day_summary(journal, day, n, pnl, start_eq, end_eq, perf) -> None:
    if n == 0:
        journal.note(day, "No reaction trades today.", kind="note")
        return
    ret = (end_eq - start_eq) / start_eq * 100 if start_eq else 0.0
    journal.note(
        day,
        f"Day close: {n} trade(s), P&L {pnl:+.2f}, equity ${end_eq:,.2f} ({ret:+.2f}%).",
        kind="move",
    )


def _print_summary(trades, start_balance, equity, max_dd, perf, journal_root,
                   journal=None) -> None:
    n = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    total_r = sum(t["r"] for t in trades)
    gross_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    print(f"\n{'=' * 64}")
    print("LEARNING BACKTEST — REACTION ENGINE + RISK SIZING + ONLINE MEMORY")
    print(f"{'=' * 64}")
    print(f"  Trades            : {n}")
    print(f"  Win rate          : {(wins / n * 100) if n else 0:.1f}%")
    print(f"  Expectancy        : {(total_r / n) if n else 0:+.3f} R/trade")
    print(f"  Profit factor     : {pf:.2f}")
    print(f"  Start balance     : ${start_balance:,.2f}")
    print(f"  Final equity      : ${equity:,.2f}")
    print(f"  Total return      : {((equity - start_balance) / start_balance * 100) if start_balance else 0:+.1f}%")
    print(f"  Max drawdown      : {max_dd * 100:.1f}%")

    # Attribution breakdown (bad_setup vs good_setup_failed need opposite fixes).
    from agent.journal.live_journal import calibration_report, classify_outcome
    attr: dict[str, int] = {}
    cal_records = []
    for t in trades:
        a = classify_outcome(t.get("conviction"), t.get("r", 0.0))
        attr[a] = attr.get(a, 0) + 1
        cal_records.append({"conviction": t.get("conviction"), "r_multiple": t.get("r", 0.0)})
    if attr:
        print("  Attribution       : "
              + ", ".join(f"{k}={v}" for k, v in sorted(attr.items())))

    cal = calibration_report(cal_records)
    print("  Conviction calibration (by band):")
    for b in cal["buckets"]:
        if b["n"]:
            print(f"    {b['band']:<5} n={b['n']:>3} wr={b['win_rate'] * 100:>5.1f}% "
                  f"exp={b['expectancy_r']:+.2f}R")
    print(f"    verdict: {'MISCALIBRATED' if cal['miscalibrated'] else 'ok'} — {cal['message']}")

    # Declined-setup summary — the over-strict-filter signal.
    if journal is not None:
        all_decl = [d for day in journal._day_declines.values() for d in day]
        if all_decl:
            wh = sum(1 for d in all_decl if d.get("would_have_won") is True)
            print(f"  Declined setups   : {len(all_decl)} "
                  f"(would have won: {wh})")
    print(f"\n  Per-signature learning (final state):")
    rows = perf.summary_rows()
    if not rows:
        print("    (no signatures recorded)")
    for r in rows[:15]:
        print(f"    {r['signature']:<52} n={r['n']:>3} wr={r['win_rate'] * 100:>5.1f}% "
              f"exp={r['expectancy_r']:+.2f}R adj={r['adjustment']:+.3f}")
    print(f"\n  Per-day archive logs: {journal_root}")
    print(f"  Performance memory : {journal_root / 'perf_memory.json'}")
    print(f"{'=' * 64}\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reaction-engine learning backtest")
    p.add_argument("--symbol", default=None)
    p.add_argument("--timeframe", default="H1")
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--max-bars", type=int, default=None,
                   help="Limit to the most recent N bars (faster smoke runs)")
    p.add_argument("--start-balance", type=float, default=100.0)
    p.add_argument("--leverage", type=int, default=1000)
    p.add_argument("--risk-min", type=float, default=0.005)
    p.add_argument("--risk-max", type=float, default=0.02)
    p.add_argument("--max-hold", type=int, default=120,
                   help="Max bars to hold a trade before a time stop")
    p.add_argument("--decline-lookahead", type=int, default=24,
                   help="Bars to look ahead when scoring a declined setup's "
                        "would-have outcome")
    p.add_argument("--warmup", type=int, default=50)
    p.add_argument("--reset", action="store_true",
                   help="Archive existing backtest logs + reset perf memory first")
    p.add_argument("--config", default=None)
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
