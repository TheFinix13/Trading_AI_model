"""Quick validation: FVG quality distribution on training data (2020-2023).

Reports:
  - Total FVGs detected vs quality-filtered
  - Confirmed reaction entries with the two-phase approach
  - Quality breakdown by session
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars, filter_bars_by_date
from agent.detectors.fvg import detect_fvgs, compute_fvg_quality
from agent.detectors.fvg_retest import check_fvg_retest_entries
from agent.types import Direction, FVG, Timeframe


def main():
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)

    window_start = datetime(2020, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2023, 12, 31, tzinfo=timezone.utc)

    for tf in (Timeframe.H1, Timeframe.M15):
        df = loader.cache.load(cfg.symbol, tf)
        if df.empty:
            print(f"[SKIP] No cached data for {cfg.symbol} {tf.value}")
            continue

        bars = df_to_bars(df, tf)
        bars = filter_bars_by_date(bars, start=window_start, end=window_end)
        if not bars:
            print(f"[SKIP] No bars in window for {tf.value}")
            continue

        print(f"\n{'='*60}")
        print(f"  FVG QUALITY ANALYSIS: {cfg.symbol} {tf.value}")
        print(f"  Period: {window_start.date()} to {window_end.date()}")
        print(f"  Total bars: {len(bars)}")
        print(f"{'='*60}\n")

        # Detect all FVGs (quality fields populated, but fill tracking is full-history)
        all_fvgs = detect_fvgs(bars, min_size_pips=cfg.detectors.fvg_min_size_pips)

        # Quality tiers (based on creation quality BEFORE fill tracking)
        # Recompute without fill to see creation-time quality
        creation_scores = []
        for fvg in all_fvgs:
            saved_fill = fvg.fill_pct
            saved_revisit = fvg.revisit_count
            fvg.fill_pct = 0.0
            fvg.revisit_count = 0
            creation_score = compute_fvg_quality(fvg)
            creation_scores.append(creation_score)
            fvg.fill_pct = saved_fill
            fvg.revisit_count = saved_revisit

        q40_creation = sum(1 for s in creation_scores if s >= 40)
        q60_creation = sum(1 for s in creation_scores if s >= 60)
        q80_creation = sum(1 for s in creation_scores if s >= 80)

        print(f"  Total FVGs detected:               {len(all_fvgs)}")
        print(f"  Creation quality >= 40:            {q40_creation} ({100*q40_creation/max(1,len(all_fvgs)):.1f}%)")
        print(f"  Creation quality >= 60:            {q60_creation} ({100*q60_creation/max(1,len(all_fvgs)):.1f}%)")
        print(f"  Creation quality >= 80:            {q80_creation} ({100*q80_creation/max(1,len(all_fvgs)):.1f}%)")
        print(f"  Filtered out by quality < 40:      {len(all_fvgs) - q40_creation} ({100*(len(all_fvgs)-q40_creation)/max(1,len(all_fvgs)):.1f}%)")
        print()

        # Session distribution of quality FVGs
        session_counts: dict[str, int] = {}
        for i, fvg in enumerate(all_fvgs):
            if creation_scores[i] >= 40:
                s = fvg.formation_session
                session_counts[s] = session_counts.get(s, 0) + 1
        print("  Quality FVG (creation score >= 40) by session:")
        for session, count in sorted(session_counts.items(), key=lambda x: -x[1]):
            print(f"    {session:<16s}: {count:4d} ({100*count/max(1,q40_creation):.1f}%)")
        print()

        # Incremental reaction detection (simulates backtest behavior)
        # Use a sliding window: for each bar, check recent FVGs (last 100 bars)
        # without relying on full-history fill state
        reactions_found = 0
        bars_with_fvg_touch = 0
        reaction_types: dict[str, int] = {}
        quality_at_entry: list[float] = []

        # Build FVG index by creation bar for efficient lookup
        # Simulate incremental: only consider FVGs created before current bar
        # and not yet "fully passed through"
        window_size = 100  # Max bars to look back for active FVGs
        check_step = 3  # Check every 3rd bar for speed

        for idx in range(50, len(bars), check_step):
            # Get FVGs created in the lookback window
            recent_fvgs = [
                f for f in all_fvgs
                if f.created_bar_index < idx
                and (idx - f.created_bar_index) <= window_size
                and creation_scores[all_fvgs.index(f)] >= 40
            ]
            if not recent_fvgs:
                continue

            # Check if current bar touches any FVG
            cur = bars[idx]
            touching = [
                f for f in recent_fvgs
                if cur.low <= f.top and cur.high >= f.bottom
            ]
            if not touching:
                continue

            bars_with_fvg_touch += 1

            # Check reactions (use relaxed fill filter since we're simulating incremental)
            entries = check_fvg_retest_entries(
                bars, touching, idx,
                min_quality_score=0,  # Already filtered above
                require_reaction=True,
                max_fill_pct=1.0,  # Ignore full-history fill (wrong for incremental)
                max_revisits=99,   # Ignore full-history revisits
            )
            if entries:
                reactions_found += 1
                rt = entries[0].reaction_type
                reaction_types[rt] = reaction_types.get(rt, 0) + 1
                quality_at_entry.append(creation_scores[all_fvgs.index(entries[0].fvg)])

        print(f"  Incremental reaction check (every {check_step} bars, {window_size}-bar window):")
        print(f"    Bars where price touches quality FVG: {bars_with_fvg_touch}")
        print(f"    Confirmed reaction entries:           {reactions_found}")
        if bars_with_fvg_touch > 0:
            print(f"    Reaction rate on touch:               {100*reactions_found/bars_with_fvg_touch:.1f}%")
        # Extrapolate to full bar coverage
        estimated_full = reactions_found * check_step
        print(f"    Estimated entries (full coverage):     ~{estimated_full}")
        years = (window_end - window_start).days / 365.25
        print(f"    Estimated entries/year:                ~{estimated_full/years:.0f}")
        print()
        print(f"    Reaction type breakdown:")
        for rt, count in sorted(reaction_types.items(), key=lambda x: -x[1]):
            print(f"      {rt:<20s}: {count:4d}")
        if quality_at_entry:
            print(f"    Avg quality at entry: {sum(quality_at_entry)/len(quality_at_entry):.1f}")
        print()

        # Quality score histogram
        print(f"  Creation quality score distribution:")
        print(f"    Mean:   {sum(creation_scores)/len(creation_scores):.1f}")
        bins = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]
        for lo, hi in bins:
            n = sum(1 for s in creation_scores if lo <= s < hi)
            bar_str = "#" * max(1, n * 40 // max(1, len(creation_scores)))
            print(f"    [{lo:2d}-{hi:2d}): {n:5d} ({100*n/max(1,len(creation_scores)):5.1f}%) {bar_str}")
        print()

        # Comparison: old vs new approach
        print("  OLD vs NEW approach comparison:")
        print(f"    OLD (any FVG touch = entry):       ~{bars_with_fvg_touch} potential signals")
        print(f"    NEW (quality >= 40 + reaction):    ~{estimated_full} signals")
        reduction = 100 * (1 - estimated_full / max(1, bars_with_fvg_touch * check_step))
        print(f"    Signal reduction:                  {reduction:.1f}%")
        print(f"    → Fewer but higher-conviction trades")
        print()

    print("\n[DONE] FVG quality validation complete.")


if __name__ == "__main__":
    main()
