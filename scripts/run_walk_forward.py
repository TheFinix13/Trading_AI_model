"""Walk-forward validation for the zone routing table.

The single IS/OOS split (``scripts/run_holdout_validation.py``) revealed
that 7 of 8 IS-survivors didn't hold up on 2023-2025. But one split is one
data point — what if 2023-2025 happens to be unusually hard (post-COVID
range, US election volatility) and the cells *do* generalize on a kinder
window?

Walk-forward gives us multiple OOS estimates. Rolling 4-year IS windows
each followed by a 1-year OOS window, sliding annually:

  IS 2015-2018  →  OOS 2019
  IS 2016-2019  →  OOS 2020
  ...
  IS 2021-2024  →  OOS 2025

For each window, we run the alpha on the **full bar series** (detectors
get warmup) and filter trades to the IS or OOS sub-window plus the target
session.  Selection (IS BH-significance, also raw p<=0.05) and
confirmation (OOS p<=0.05) are evaluated on each window independently.

A cell is "walk-forward robust" when:

  1. It survives BH at FDR 5% on the IS portion of EVERY window
     (i.e. the edge is detectable across all training periods); AND
  2. OOS p<=0.05 with positive expectancy on **at least half** of the
     OOS windows; AND
  3. Median OOS expectancy is positive.

If a cell fails (1) it was never an edge to begin with — it just happened
to win on the original 2015-2022 window.  If it fails (2) the edge isn't
stable enough to deploy.  If it fails (3) we've been trading a streak.

The summary also prints "soft" cells that pass raw IS p<=0.05 (without
BH) in >=50% windows, in case the 4-yr IS BH gate is too strict on cells
that don't have enough trades per window.  These are diagnostic only,
not deployment candidates.
"""
from __future__ import annotations

import json
import logging
import pickle
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.alphas.concepts import SupplyDemandAlpha
from agent.alphas.grid import ALL_SESSIONS, AblationCell
from agent.backtest.metrics import benjamini_hochberg, bootstrap_p_value, make_scorecard
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.detectors.sessions import label_session
from agent.rules.engine import precompute
from agent.types import Bar, Timeframe

logging.basicConfig(level=logging.WARNING)

FULL_START = datetime(2015, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2025, 12, 1, tzinfo=timezone.utc)
IS_YEARS = 4
OOS_YEARS = 1
# Anchor each window at Jan-1; cycles 2015-2018+2019, 2016-2019+2020, ...
WINDOW_STARTS = [datetime(y, 1, 1, tzinfo=timezone.utc)
                 for y in range(2015, 2025 - IS_YEARS - OOS_YEARS + 2)]

TFS = (Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15, Timeframe.M5)


@dataclass
class WindowResult:
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime
    is_n: int
    is_exp: float
    is_p: float
    is_q: float
    is_survives_bh: bool
    oos_n: int
    oos_exp: float
    oos_p: float


@dataclass
class CellSummary:
    label: str
    tf: str
    session: str
    mode: str
    windows: list[WindowResult]

    @property
    def is_bh_pass_rate(self) -> float:
        return sum(1 for w in self.windows if w.is_survives_bh) / max(len(self.windows), 1)

    @property
    def is_raw_pass_rate(self) -> float:
        """Raw p<=0.05 with positive expectancy (no FDR correction)."""
        n = sum(1 for w in self.windows
                if w.is_p <= 0.05 and w.is_exp > 0)
        return n / max(len(self.windows), 1)

    @property
    def oos_pass_rate(self) -> float:
        n = sum(1 for w in self.windows
                if w.oos_p <= 0.05 and w.oos_exp > 0 and w.oos_n >= 20)
        return n / max(len(self.windows), 1)

    @property
    def median_oos_exp(self) -> float:
        vals = [w.oos_exp for w in self.windows]
        return statistics.median(vals) if vals else 0.0

    @property
    def walk_forward_robust(self) -> bool:
        """The three gates from the module docstring."""
        return (
            self.is_bh_pass_rate >= 1.0
            and self.oos_pass_rate >= 0.5
            and self.median_oos_exp > 0
        )


def _make_factories() -> dict:
    return {
        "zone":            lambda c: SupplyDemandAlpha(c),
        "zone_d1_against": lambda c: SupplyDemandAlpha(
            c, htf_align="D1", htf_align_mode="against",
            htf_lookback=10, htf_min_move_pips=60.0,
        ),
    }


def _slice(bars: list[Bar], lo: datetime, hi: datetime) -> list[Bar]:
    return [b for b in bars if lo <= b.time <= hi]


CACHE_PATH = Path(".cache/walk_forward_trades.pkl")


def main() -> None:
    cfg = load_config()

    factories = _make_factories()
    grid_cells = [
        AblationCell(alpha_name=name, timeframe=tf.value, session=sess,
                     alpha_factory=fac)
        for name, fac in factories.items()
        for tf in TFS
        for sess in ALL_SESSIONS
    ]

    full_trades: dict[tuple[str, str], list] | None = None
    if CACHE_PATH.exists():
        print(f"Loading cached alpha walks from {CACHE_PATH} …")
        try:
            with CACHE_PATH.open("rb") as f:
                full_trades = pickle.load(f)
            for k, v in full_trades.items():
                print(f"  {k[0]}/{k[1]}: {len(v):,} trades")
        except Exception as exc:
            print(f"  cache load failed ({exc}); recomputing")
            full_trades = None

    if full_trades is None:
        loader = BarLoader(cache_root=cfg.data_dir)
        bars_full: dict[str, list[Bar]] = {}
        print("Loading bars …")
        for tf in TFS:
            df = loader.get(cfg.symbol, tf, FULL_START, FULL_END, refresh=False)
            bars_full[tf.value] = df_to_bars(df, tf)
            print(f"  {tf.value}: {len(bars_full[tf.value]):,} bars")

        print("\nPrecomputing per-TF contexts …")
        ctx_full = {}
        for tf in TFS:
            ctx_full[tf.value] = precompute(bars_full[tf.value], cfg)
            print(f"  {tf.value}: zones={len(ctx_full[tf.value].zones)} "
                  f"sweeps={len(ctx_full[tf.value].liquidity_sweeps)}")

        from agent.alphas.backtest import run_alpha
        print("\nPre-running alpha walks on full series …")
        full_trades = {}
        for name, fac in factories.items():
            for tf in TFS:
                alpha = fac(cfg)
                full_trades[(name, tf.value)] = run_alpha(
                    alpha, bars_full[tf.value], cfg,
                    ctx=ctx_full[tf.value], start_index=200,
                )
                print(f"  {name}/{tf.value}: "
                      f"{len(full_trades[(name, tf.value)]):,} trades")

        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_PATH.open("wb") as f:
            pickle.dump(full_trades, f)
        print(f"Cached alpha walks to {CACHE_PATH}")

    n_windows = len(WINDOW_STARTS)
    print(f"\nRunning walk-forward over {n_windows} windows "
          f"({IS_YEARS}yr IS / {OOS_YEARS}yr OOS each)\n")

    by_cell: dict[str, list[WindowResult]] = {c.label: [] for c in grid_cells}

    def _filter(all_trades, lo, hi, target_session):
        return [
            t for t in all_trades
            if t.exit_time is not None
            and lo <= t.entry_time < hi
            and (target_session == "all"
                 or label_session(t.entry_time) == target_session)
        ]

    for w_idx, is_start in enumerate(WINDOW_STARTS):
        is_end = datetime(is_start.year + IS_YEARS, 1, 1, tzinfo=timezone.utc)
        oos_start = is_end
        oos_end = datetime(oos_start.year + OOS_YEARS, 1, 1, tzinfo=timezone.utc)
        if oos_end > FULL_END:
            oos_end = FULL_END
        print(f"  WINDOW {w_idx + 1}/{n_windows}: "
              f"IS {is_start.year}-{is_end.year - 1}  →  OOS {oos_start.year}")

        is_results: dict[str, dict] = {}
        oos_results: dict[str, dict] = {}
        is_p_for_bh: list[tuple[str, float]] = []

        for cell in grid_cells:
            key = (cell.alpha_name, cell.timeframe)
            all_trades = full_trades[key]

            is_trades = _filter(all_trades, is_start, is_end, cell.session)
            is_card = make_scorecard(cell.label, is_trades,
                                     cfg.backtest.initial_balance,
                                     n_resamples=500)
            is_p = bootstrap_p_value([t.pnl for t in is_trades],
                                     n_resamples=500)
            is_results[cell.label] = {
                "n": is_card.n_trades,
                "exp": is_card.expectancy.value,
                "p": is_p,
            }
            is_p_for_bh.append((cell.label, is_p))

            oos_trades = _filter(all_trades, oos_start, oos_end, cell.session)
            oos_card = make_scorecard(cell.label, oos_trades,
                                      cfg.backtest.initial_balance,
                                      n_resamples=500)
            oos_p = bootstrap_p_value([t.pnl for t in oos_trades],
                                      n_resamples=500)
            oos_results[cell.label] = {
                "n": oos_card.n_trades,
                "exp": oos_card.expectancy.value,
                "p": oos_p,
            }

        bh_rejected, bh_q = benjamini_hochberg(
            [p for _, p in is_p_for_bh], fdr=0.05,
        )
        bh_by_label = {
            lbl: (bh_rejected[i], bh_q[i])
            for i, (lbl, _) in enumerate(is_p_for_bh)
        }

        for cell in grid_cells:
            is_r = is_results[cell.label]
            oos_r = oos_results[cell.label]
            rej, q = bh_by_label[cell.label]
            by_cell[cell.label].append(WindowResult(
                is_start=is_start, is_end=is_end,
                oos_start=oos_start, oos_end=oos_end,
                is_n=is_r["n"], is_exp=is_r["exp"], is_p=is_r["p"],
                is_q=q,
                is_survives_bh=rej and is_r["exp"] > 0,
                oos_n=oos_r["n"], oos_exp=oos_r["exp"], oos_p=oos_r["p"],
            ))

    all_summaries = [
        CellSummary(label=c.label, tf=c.timeframe, session=c.session,
                    mode=c.alpha_name, windows=by_cell[c.label])
        for c in grid_cells
    ]

    out_path = Path("docs/reviews/walk_forward_raw.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = []
    for s in all_summaries:
        payload.append({
            "label": s.label, "tf": s.tf, "session": s.session,
            "mode": s.mode,
            "is_bh_pass_rate": s.is_bh_pass_rate,
            "is_raw_pass_rate": s.is_raw_pass_rate,
            "oos_pass_rate": s.oos_pass_rate,
            "median_oos_exp": s.median_oos_exp,
            "walk_forward_robust": s.walk_forward_robust,
            "windows": [
                {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                 for k, v in asdict(w).items()}
                for w in s.windows
            ],
        })
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nRaw walk-forward results saved to: {out_path}")

    def _print_window_detail(s: CellSummary, indent: str = "    ") -> None:
        for w in s.windows:
            is_g = "•" if (w.is_p <= 0.05 and w.is_exp > 0) else " "
            bh_g = "✓" if w.is_survives_bh else " "
            oos_g = ("✓" if (w.oos_p <= 0.05 and w.oos_exp > 0 and w.oos_n >= 20)
                     else " ")
            print(f"{indent}IS {w.is_start.year}-{w.is_end.year - 1} → "
                  f"OOS {w.oos_start.year}: "
                  f"is(n={w.is_n:>3} exp={w.is_exp:>+6.2f} p={w.is_p:.3f}) {is_g}{bh_g}  "
                  f"oos(n={w.oos_n:>3} exp={w.oos_exp:>+6.2f} p={w.oos_p:.3f}) {oos_g}")

    # ============================================================
    # 1) ROBUST cells (passes all three gates)
    # ============================================================
    robust = [s for s in all_summaries if s.walk_forward_robust]
    print(f"\n{'=' * 110}")
    print(f"ROBUST CELLS  (IS-BH 100% AND OOS p≤.05 in ≥50% windows AND median OOS exp > 0)")
    print(f"{'=' * 110}")
    if robust:
        for s in robust:
            print(f"\n  {s.label}")
            _print_window_detail(s)
    else:
        print("  (none)")

    # ============================================================
    # 2) Soft IS pass (raw p<=.05) — diagnostic, the BH-FDR gate
    #    over 50 cells on a 4-yr window is very strict
    # ============================================================
    soft = [s for s in all_summaries
            if s.is_raw_pass_rate >= 0.5 and not s.walk_forward_robust]
    soft.sort(key=lambda s: (-s.oos_pass_rate, -s.median_oos_exp,
                              -s.is_raw_pass_rate))
    print(f"\n{'=' * 110}")
    print(f"SOFT-IS CELLS  (raw IS p≤.05 in ≥50% windows; BH-FDR may have been too strict)")
    print(f"{'=' * 110}")
    print(f"{'cell':<48} {'is_raw':>7} {'is_bh':>7} {'oos_pass':>9} "
          f"{'med_oos':>10}")
    print("-" * 110)
    for s in soft[:25]:
        print(f"{s.label:<48} {s.is_raw_pass_rate:>7.0%} "
              f"{s.is_bh_pass_rate:>7.0%} {s.oos_pass_rate:>9.0%} "
              f"{s.median_oos_exp:>+10.2f}")

    # ============================================================
    # 3) Prior survivor + candidates per zone_routing.py
    # ============================================================
    watch_labels = [
        "zone_d1_against/H4/asia",
        "zone/M15/overlap",
        "zone_d1_against/H1/all",
        "zone_d1_against/H1/ny",
    ]
    by_label = {s.label: s for s in all_summaries}
    print(f"\n{'=' * 110}")
    print(f"PRIOR SURVIVOR + CANDIDATE CELLS  (per-window detail)")
    print(f"{'=' * 110}")
    for lbl in watch_labels:
        s = by_label.get(lbl)
        if s is None:
            print(f"\n  {lbl}: (not in grid)")
            continue
        flag = "ROBUST" if s.walk_forward_robust else "NOT robust"
        print(f"\n  {lbl}  [{flag}]")
        print(f"    summary: is_bh_pass={s.is_bh_pass_rate:.0%}  "
              f"is_raw_pass={s.is_raw_pass_rate:.0%}  "
              f"oos_pass={s.oos_pass_rate:.0%}  "
              f"med_oos_exp={s.median_oos_exp:+.2f}")
        _print_window_detail(s)

    print(f"\n{'-' * 110}")
    print(f"Walk-forward robust cells: {len(robust)} / {len(grid_cells)} total")


if __name__ == "__main__":
    main()
