"""Read docs/reviews/walk_forward_raw.json and surface the cells whose
**positive expectancy** is stable across walk-forward windows.

With annual OOS samples in the 10-200 trade range, hitting p<=0.05 every
window is statistically very hard. A consistently positive median + a
high "positive OOS expectancy rate" is often a more honest signal for
a small-but-real edge than chasing per-window significance.
"""
from __future__ import annotations

import json
from pathlib import Path

import statistics


def main() -> None:
    raw = json.loads(Path("docs/reviews/walk_forward_raw.json").read_text())

    rows = []
    for cell in raw:
        windows = cell["windows"]
        n_win = len(windows)
        oos_exps = [w["oos_exp"] for w in windows]
        oos_pos = sum(1 for x in oos_exps if x > 0)
        oos_p_pos = sum(1 for w in windows
                        if w["oos_p"] <= 0.05 and w["oos_exp"] > 0
                        and w["oos_n"] >= 20)
        is_raw = sum(1 for w in windows
                     if w["is_p"] <= 0.05 and w["is_exp"] > 0)
        is_bh = sum(1 for w in windows if w["is_survives_bh"])
        median = statistics.median(oos_exps) if oos_exps else 0.0
        avg_n_per_window = (statistics.mean([w["oos_n"] for w in windows])
                            if windows else 0.0)
        rows.append({
            "label": cell["label"],
            "tf": cell["tf"],
            "session": cell["session"],
            "mode": cell["mode"],
            "n_win": n_win,
            "is_raw_pct": is_raw / n_win,
            "is_bh_pct": is_bh / n_win,
            "oos_pos_pct": oos_pos / n_win,
            "oos_sig_pct": oos_p_pos / n_win,
            "median_oos_exp": median,
            "avg_oos_n": avg_n_per_window,
        })

    # Sort by the most informative joint signal: high positive-OOS rate
    # AND positive median expectancy AND IS pre-screen.
    rows.sort(key=lambda r: (-r["oos_pos_pct"],
                             -r["median_oos_exp"],
                             -r["is_raw_pct"]))

    print("=" * 120)
    print("TOP CELLS BY OOS POSITIVE-EXPECTANCY RATE")
    print("(strong candidates: oos_pos>=85%, med_oos_exp>0, is_raw>=50%, avg_n>=15)")
    print("=" * 120)
    print(f"{'cell':<48} {'is_raw':>7} {'is_bh':>7} "
          f"{'oos_pos':>8} {'oos_sig':>8} {'med_exp':>9} {'avg_n':>7}  STRONG")
    print("-" * 120)
    for r in rows[:30]:
        strong = (r["oos_pos_pct"] >= 0.85
                  and r["median_oos_exp"] > 0
                  and r["is_raw_pct"] >= 0.5
                  and r["avg_oos_n"] >= 15)
        mark = "✓" if strong else " "
        print(f"{r['label']:<48} {r['is_raw_pct']:>7.0%} "
              f"{r['is_bh_pct']:>7.0%} {r['oos_pos_pct']:>8.0%} "
              f"{r['oos_sig_pct']:>8.0%} {r['median_oos_exp']:>+9.2f} "
              f"{r['avg_oos_n']:>7.0f}     {mark}")

    print()
    print("=" * 120)
    print("STRONG CELLS (proposed deployment candidates)")
    print("=" * 120)
    strong = [r for r in rows
              if r["oos_pos_pct"] >= 0.85
              and r["median_oos_exp"] > 0
              and r["is_raw_pct"] >= 0.5
              and r["avg_oos_n"] >= 15]
    for r in strong:
        print(f"  {r['label']}: "
              f"OOS+ in {r['oos_pos_pct']:.0%} windows, "
              f"med exp {r['median_oos_exp']:+.2f}, "
              f"~{r['avg_oos_n']:.0f} trades/window")
    if not strong:
        print("  (none)")


if __name__ == "__main__":
    main()
