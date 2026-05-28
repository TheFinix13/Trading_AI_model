"""Diagnostic script: simulate what the live agent sees RIGHT NOW.

Runs all detectors and strategies on the latest cached data, showing
exactly what passes each gate and what gets blocked.  Use this to
debug "why did the agent produce zero trades?" without needing a
live MT5 connection.

Usage:
    PYTHONPATH=. python scripts/diagnose_live.py
    PYTHONPATH=. python scripts/diagnose_live.py --timeframe H1 --lookback 300
    PYTHONPATH=. python scripts/diagnose_live.py --bar-index -1   # check a specific bar
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from agent.config import (
    GATE_PROFILE_DEFAULT,
    GATE_PROFILES,
    PROJECT_ROOT,
    GateProfile,
    load_config,
)
from agent.context.htf_context import HTFAnalyzer, HTFContext, MarketBias
from agent.detectors.liquidity_zones import LiquidityZone, check_retest_entries
from agent.detectors.sessions import label_session
from agent.features.extractor import extract_features
from agent.model.scorer import SetupScorer
from agent.rules.engine import RuleEngine, precompute
from agent.strategy.registry import StrategyRouter, default_registry
from agent.types import Bar, Direction, Timeframe


def _load_bars(data_dir: Path, symbol: str, timeframe: str, lookback: int) -> list[Bar]:
    parquet = data_dir / f"{symbol}_{timeframe}.parquet"
    if not parquet.exists():
        print(f"  [!] No data file: {parquet}")
        return []
    df = pd.read_parquet(parquet)
    if df.empty:
        print(f"  [!] Data file is empty: {parquet}")
        return []
    df = df.tail(lookback)
    tf = Timeframe(timeframe)
    bars: list[Bar] = []
    for ts, row in df.iterrows():
        bars.append(Bar(
            time=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            timeframe=tf,
        ))
    return bars


def _load_scorer(path_str: str) -> SetupScorer | None:
    p = Path(path_str)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.exists():
        return None
    try:
        return SetupScorer.load(p)
    except Exception:
        return None


def _fmt_price(p: float) -> str:
    return f"{p:.5f}"


def _direction_symbol(d: Direction) -> str:
    return "LONG" if d == Direction.LONG else "SHORT"


def main():
    parser = argparse.ArgumentParser(description="Live agent diagnostic")
    parser.add_argument("--timeframe", "-t", default="H1")
    parser.add_argument("--lookback", "-n", type=int, default=300)
    parser.add_argument("--bar-index", type=int, default=-1,
                        help="Which bar to evaluate (-1 = last closed bar)")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    symbol = cfg.symbol
    tf = args.timeframe
    lookback = args.lookback

    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    use_unicode = "utf" in enc
    SEP = "\u2550" * 60 if use_unicode else "=" * 60
    OK = "\u2713" if use_unicode else "OK"
    FAIL = "\u2717" if use_unicode else "X"
    WARN = "!" 
    ARROW = "\u2192" if use_unicode else "->"

    print()
    print(SEP)
    print("  LIVE DIAGNOSTIC")
    print(SEP)

    # ── Load data ──
    bars = _load_bars(cfg.data_dir, symbol, tf, lookback)
    if not bars:
        print(f"  [{FAIL}] No {tf} data for {symbol}")
        return
    print(f"  Data: {symbol} {tf}, {len(bars)} bars")
    print(f"  First bar: {bars[0].time.isoformat()}")
    print(f"  Last bar:  {bars[-1].time.isoformat()} (close={bars[-1].close:.5f})")

    # Compute how many calendar days the lookback covers
    span_days = (bars[-1].time - bars[0].time).days
    print(f"  Lookback span: ~{span_days} calendar days")

    bar_index = args.bar_index if args.bar_index >= 0 else len(bars) - 1
    eval_bar = bars[bar_index]
    session = label_session(eval_bar.time)
    print(f"  Evaluation bar: index={bar_index}, time={eval_bar.time.isoformat()}, session={session}")
    print()

    # ── Precompute ──
    print("  Precomputing detector context...")
    ctx = precompute(bars, cfg)
    print(f"    SD Zones:          {len(ctx.zones)}")
    print(f"    Qualified Zones:   {len(ctx.qualified_zones)}")
    print(f"    FVGs:              {len(ctx.fvgs)}")
    print(f"    BOS events:        {len(ctx.bos_list)}")
    print(f"    Trendlines:        {len(ctx.trendlines)}")
    print(f"    Liquidity wicks:   {len(ctx.wicks)}")
    print(f"    Liquidity sweeps:  {len(ctx.liquidity_sweeps)}")
    print(f"    Liquidity zones:   {len(ctx.liquidity_zones)}")
    print(f"    Swings:            {len(ctx.swings)}")
    print()

    # ── LZI zones detail ──
    lzi_zones = ctx.liquidity_zones
    if lzi_zones:
        print("  LIQUIDITY ZONES OF INTEREST (LZI):")
        for i, z in enumerate(lzi_zones):
            age = bar_index - z.formation_bar_index
            print(
                f"    Zone {i+1}: {z.side} sweep of {z.swept_label} "
                f"@ {_fmt_price(z.swept_price)} | "
                f"zone [{_fmt_price(z.zone_bottom)}-{_fmt_price(z.zone_top)}] | "
                f"wick={z.wick_size_pips:.1f}p | "
                f"status={z.status} | age={age} bars | "
                f"trade_dir={_direction_symbol(z.trade_direction)} | "
                f"formed={z.formation_time.isoformat()}"
            )
        print()
    else:
        print(f"  [{WARN}] No LZI zones detected in {len(bars)} bars")
        print(f"      min_wick_size_pips_h1={cfg.liquidity.min_wick_size_pips_h1}")
        print(f"      swing_lookback={cfg.detectors.swing_lookback}")
        print()

    # ── HTF Context Layer ──
    if cfg.htf.enabled:
        print(f"  {'HTF CONTEXT':=^56}")
        h4_bars_list = _load_bars(cfg.data_dir, symbol, "H4", cfg.htf.h4_lookback_bars)
        d1_bars_list = _load_bars(cfg.data_dir, symbol, "D1", cfg.htf.d1_lookback_bars)

        if h4_bars_list and d1_bars_list:
            h4_df = pd.DataFrame([
                {"time": b.time, "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume}
                for b in h4_bars_list
            ])
            d1_df = pd.DataFrame([
                {"time": b.time, "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "volume": b.volume}
                for b in d1_bars_list
            ])

            htf_analyzer = HTFAnalyzer(lookback_days=cfg.htf.lookback_days)
            htf_ctx = htf_analyzer.analyze(h4_df, d1_df)

            print(f"    H4 Bias:    {htf_ctx.h4_bias.value.upper()}")
            print(f"    D1 Bias:    {htf_ctx.d1_bias.value.upper()}")
            print(f"    Combined:   {htf_ctx.combined_bias.value.upper()} (confidence: {htf_ctx.bias_confidence:.2f})")
            print(f"    Buy aligned:  {htf_ctx.buy_aligned}")
            print(f"    Sell aligned: {htf_ctx.sell_aligned}")
            print()

            if htf_ctx.active_patterns:
                print("    Pattern Mechanics:")
                for p in htf_ctx.active_patterns:
                    dir_str = "BUY" if p.implied_direction == MarketBias.BULLISH else (
                        "SELL" if p.implied_direction == MarketBias.BEARISH else "NEUTRAL"
                    )
                    print(f"      [{p.pattern_type.value}] at {p.key_level:.5f} ({p.timeframe})")
                    print(f"        \"{p.description}\"")
                    print(f"        Confidence: {p.confidence:.2f} | Direction: {dir_str}")
                print()

            if htf_ctx.weekly:
                w = htf_ctx.weekly
                print("    Weekly Narrative:")
                print(f"      Week range: {w.week_low:.5f} — {w.week_high:.5f} "
                      f"({(w.week_high - w.week_low) / 0.0001:.0f} pips)")
                if w.unswept_high_liquidity:
                    print(f"      Unswept highs: {', '.join(f'{h:.5f}' for h in w.unswept_high_liquidity)}")
                else:
                    print(f"      Unswept highs: [none]")
                if w.unswept_low_liquidity:
                    print(f"      Unswept lows:  {', '.join(f'{l:.5f}' for l in w.unswept_low_liquidity)}")
                else:
                    print(f"      Unswept lows:  [none]")
                exp_str = w.expansion_direction.value.upper() if w.expansion_direction else "N/A"
                print(f"      Expansion: {exp_str}")
                print()

            if htf_ctx.htf_fib_levels:
                print("    HTF Fib Levels (H4 swing):")
                for price, label in htf_ctx.htf_fib_levels:
                    print(f"      {label}: {price:.5f}")
                print()

            if htf_ctx.structural_levels:
                print(f"    Structural Levels (top {min(8, len(htf_ctx.structural_levels))} nearest):")
                for lvl in htf_ctx.structural_levels[:8]:
                    swept_str = " [SWEPT]" if lvl.swept else ""
                    print(f"      {lvl.level_type:10s} {lvl.price:.5f} ({lvl.timeframe}) "
                          f"strength={lvl.strength}{swept_str}")
                print()
        else:
            print(f"    [{WARN}] Missing H4/D1 data for HTF context")
            if not h4_bars_list:
                print(f"        No H4 data at {cfg.data_dir / f'{symbol}_H4.parquet'}")
            if not d1_bars_list:
                print(f"        No D1 data at {cfg.data_dir / f'{symbol}_D1.parquet'}")
            print()

    # ── Run rule engine (generic) ──
    print("  GENERIC RULE ENGINE:")
    engine = RuleEngine(cfg)
    engine_setup = engine.evaluate_precomputed(ctx, bar_index)
    if engine_setup:
        print(f"    [{OK}] Setup found: {_direction_symbol(engine_setup.direction)} "
              f"entry={_fmt_price(engine_setup.entry)} "
              f"stop={_fmt_price(engine_setup.stop)} "
              f"tp={_fmt_price(engine_setup.take_profit)} "
              f"confluences={engine_setup.confluences}")
    else:
        print(f"    [{FAIL}] No setup from generic engine")
        print(f"      required_factors: {cfg.rules.required_factors}")
        print(f"      require_precision_partner: {cfg.rules.require_precision_partner}")
        print(f"      require_structural_anchor: {cfg.rules.require_structural_anchor}")
        print(f"      min_confluences H1: {cfg.rules.min_confluences_per_tf.get('H1', cfg.rules.min_confluences)}")
        print(f"      blocked_session_tags: {cfg.rules.blocked_session_tags}")
        print(f"      blocked_hours_ny: {cfg.rules.blocked_hours_ny}")
    print()

    # Scan multiple bars for generic engine hits
    print("  GENERIC ENGINE SCAN (last 50 bars):")
    scan_hits = 0
    for si in range(max(50, bar_index - 50), bar_index + 1):
        s = engine.evaluate_precomputed(ctx, si)
        if s:
            scan_hits += 1
            sb = bars[si]
            sess = label_session(sb.time)
            print(f"    bar {si} ({sb.time:%Y-%m-%d %H:%M} {sess}): "
                  f"{_direction_symbol(s.direction)} confluences={s.confluences}")
    if scan_hits == 0:
        print(f"    (none found in last 50 bars)")
    print()

    # ── Run strategy router ──
    print("  STRATEGY ROUTER:")
    router = StrategyRouter(default_registry())
    strategy_setups = router.route(ctx, bar_index, regime=None)
    if strategy_setups:
        for ss in strategy_setups:
            print(f"    [{OK}] {ss.strategy_name}: {_direction_symbol(ss.direction)} "
                  f"entry={_fmt_price(ss.entry)} stop={_fmt_price(ss.stop)} "
                  f"tp={_fmt_price(ss.take_profit)} rr={ss.rr:.1f} "
                  f"confluences={ss.confluences}")

            profile = GATE_PROFILES.get(ss.strategy_name or "", GATE_PROFILE_DEFAULT)
            passed, reason = engine.validate_setup_gates(ss, bars, bar_index, profile)
            if passed:
                print(f"         Gates: [{OK}] PASSED (profile={profile.name})")
            else:
                print(f"         Gates: [{FAIL}] BLOCKED by '{reason}' (profile={profile.name})")
    else:
        print(f"    [{FAIL}] No strategy produced a setup at bar {bar_index}")
    print()

    # Scan multiple bars for strategy router hits
    print("  STRATEGY ROUTER SCAN (last 50 bars):")
    strat_scan_hits = 0
    for si in range(max(50, bar_index - 50), bar_index + 1):
        ss_list = router.route(ctx, si, regime=None)
        for ss in ss_list:
            strat_scan_hits += 1
            sb = bars[si]
            sess = label_session(sb.time)
            profile = GATE_PROFILES.get(ss.strategy_name or "", GATE_PROFILE_DEFAULT)
            passed, reason = engine.validate_setup_gates(ss, bars, si, profile)
            gate_str = f"[{OK}] passed" if passed else f"[{FAIL}] blocked:{reason}"
            print(f"    bar {si} ({sb.time:%Y-%m-%d %H:%M} {sess}): "
                  f"{ss.strategy_name} {_direction_symbol(ss.direction)} "
                  f"rr={ss.rr:.1f} gates={gate_str}")
    if strat_scan_hits == 0:
        print(f"    (none found in last 50 bars)")
    print()

    # ── ML scoring on best candidate ──
    best = strategy_setups[0] if strategy_setups else engine_setup
    if best is not None:
        print("  ML SCORING:")
        best.features = extract_features(best, bars, bar_index)
        profile = GATE_PROFILES.get(best.strategy_name or "", GATE_PROFILE_DEFAULT)

        # Generic scorer
        generic_scorer = _load_scorer(cfg.ml.scorer_paths.get(tf, ""))
        if generic_scorer:
            gscore = generic_scorer(best.features)
            gthresh = cfg.ml.prob_threshold
            status = OK if gscore >= gthresh else FAIL
            print(f"    Generic scorer: {gscore:.3f} (threshold={gthresh:.2f}) [{status}]")

        # LZI scorer
        lzi_scorer = _load_scorer(cfg.ml.lzi_scorer_path)
        if lzi_scorer and best.strategy_name == "LiquidityGrabReversal":
            try:
                from agent.features.lzi_extractor import extract_lzi_features
                lzi_zone = None
                for z in lzi_zones:
                    if z.status == "triggered" and z.trade_direction == best.direction:
                        lzi_zone = z
                        break
                if lzi_zone:
                    lzi_feats = extract_lzi_features(bars, lzi_zone, bar_index, best.take_profit)
                    lscore = lzi_scorer(lzi_feats.to_dict())
                    lthresh = profile.ml_score_override or 0.40
                    status = OK if lscore >= lthresh else FAIL
                    print(f"    LZI scorer:     {lscore:.3f} (threshold={lthresh:.2f}) [{status}]")
            except Exception as e:
                print(f"    LZI scorer: error - {e}")

        # Profile-aware threshold
        ml_thresh = profile.ml_score_override if profile.ml_score_override is not None else cfg.ml.prob_threshold
        print(f"    Profile threshold ({profile.name}): {ml_thresh:.2f}")

        # Caution day check
        from agent.rules.filters import DAY_NAME_TO_INDEX
        try:
            from zoneinfo import ZoneInfo
            eval_day = eval_bar.time.astimezone(ZoneInfo(cfg.session.timezone)).strftime("%a")
        except Exception:
            eval_day = eval_bar.time.strftime("%a")
        is_caution = eval_day in cfg.session.caution_days
        print(f"    Day: {eval_day} {'(CAUTION DAY)' if is_caution else ''}")
        if is_caution and profile.apply_caution_days_boost:
            boosted = ml_thresh + cfg.ml.caution_score_boost
            print(f"    Caution boost: +{cfg.ml.caution_score_boost:.2f} {ARROW} effective threshold={boosted:.2f}")
        print()

    # ── Session/time analysis ──
    print("  SESSION/TIME ANALYSIS:")
    try:
        from zoneinfo import ZoneInfo
        ny_time = eval_bar.time.astimezone(ZoneInfo("America/New_York"))
        ny_hour = ny_time.hour
        print(f"    NY time: {ny_time:%Y-%m-%d %H:%M} (hour={ny_hour})")
        blocked = ny_hour in cfg.rules.blocked_hours_ny
        print(f"    Blocked by generic engine hours? {'YES' if blocked else 'No'} "
              f"(blocked_hours_ny={cfg.rules.blocked_hours_ny})")
        lzi_profile = GATE_PROFILES.get("LiquidityGrabReversal", GATE_PROFILE_DEFAULT)
        lzi_blocked_hours = lzi_profile.blocked_hours_override or cfg.rules.blocked_hours_ny
        lzi_blocked = ny_hour in lzi_blocked_hours
        print(f"    Blocked by LZI profile hours?    {'YES' if lzi_blocked else 'No'} "
              f"(hours={lzi_blocked_hours})")
    except Exception as e:
        print(f"    Could not determine NY time: {e}")
    print(f"    Session label: {session}")
    session_blocked = f"session_{session}" in cfg.rules.blocked_session_tags
    print(f"    Session blocked by generic engine? {'YES' if session_blocked else 'No'} "
          f"(blocked_session_tags={cfg.rules.blocked_session_tags})")
    lzi_profile = GATE_PROFILES.get("LiquidityGrabReversal", GATE_PROFILE_DEFAULT)
    print(f"    LZI profile check_blocked_sessions={lzi_profile.check_blocked_sessions}")
    print()

    # ── Config summary ──
    print("  LIVE CONFIG (score_threshold as seen by signal_loop):")
    print(f"    LiveConfig.score_threshold default:   0.55")
    print(f"    config.ml.prob_threshold:             {cfg.ml.prob_threshold:.2f}")
    print(f"    LZI profile ml_score_override:        {GATE_PROFILES.get('LiquidityGrabReversal', GATE_PROFILE_DEFAULT).ml_score_override}")
    print(f"    FVG profile ml_score_override:        {GATE_PROFILES.get('FVGRetest', GATE_PROFILE_DEFAULT).ml_score_override}")
    print(f"    SD  profile ml_score_override:        {GATE_PROFILES.get('SDZoneRetest', GATE_PROFILE_DEFAULT).ml_score_override}")
    print()

    # ── Diagnosis ──
    print(SEP)
    print("  DIAGNOSIS:")
    issues = []

    if not strategy_setups and not engine_setup:
        if not lzi_zones:
            issues.append("No LZI zones detected — check min_wick_size_pips and data lookback")
        else:
            active = [z for z in lzi_zones if z.status not in ("triggered", "expired")]
            if not active:
                issues.append(f"All {len(lzi_zones)} LZI zones are triggered/expired — no active zones to retest")
            else:
                issues.append(f"{len(active)} active LZI zones exist but none completed the "
                              f"retest->consumption->displacement sequence at bar {bar_index}")
    elif best is not None:
        if generic_scorer:
            gscore_val = generic_scorer(best.features)
            if gscore_val < cfg.ml.prob_threshold:
                issues.append(f"Generic ML score ({gscore_val:.3f}) below threshold ({cfg.ml.prob_threshold})")
        if session_blocked:
            issues.append(f"Session '{session}' is blocked by the generic engine")

    if not issues:
        issues.append("No obvious blocking issue found for the evaluated bar — "
                       "check if the overnight hours had different conditions")

    for issue in issues:
        print(f"    {ARROW} {issue}")
    print(SEP)
    print()


if __name__ == "__main__":
    main()
