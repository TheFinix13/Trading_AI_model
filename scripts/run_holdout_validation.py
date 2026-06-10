"""Out-of-sample validation for the zone-alpha routing table.

The definitive zone grid (``scripts/run_zone_all_tfs.py``) selected its
13 BH-significant cells on 2015-01-01 → 2025-12-01. That entire window was
*in-sample* for the selection process, so the q-values overstate the true
edge: re-using the same data for selection and reporting is the classic
backtest-overfit failure mode.

This script does an honest split:

  1. **IS re-grid** on 2015-01-01 → 2022-12-31. Re-runs the same 50 cells on
     the shrunk window. Survivors here are the cells that produce a
     BH-significant edge *without ever having seen 2023+ data*.
  2. **OOS replay** on 2023-01-01 → 2025-12-01. Each IS-survivor's alpha is
     run on the **full** bar series so detectors get realistic warmup, then
     trades are filtered to OOS entry times and the target session. The
     bootstrap p-value is computed on the OOS trades alone — no peeking back
     to IS.
  3. **IS vs OOS comparison.** A cell is "validated" when:
       * OOS expectancy is positive, AND
       * OOS bootstrap p < 0.05 (raw, not BH — we already paid that penalty
         in the IS step; BH on a single OOS test is the test itself).
     Plus a sanity contract: OOS expectancy should be at least 30% of IS
     expectancy. Sharper degradation than that means the cell was riding
     2015-2022 regime that has since broken.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass

from agent.alphas.backtest import run_alpha
from agent.alphas.concepts import SupplyDemandAlpha
from agent.alphas.grid import (
    ALL_SESSIONS, AblationCell, run_grid,
)
from agent.backtest.metrics import bootstrap_p_value, make_scorecard
from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.detectors.sessions import label_session
from agent.rules.engine import precompute
from agent.types import Bar, Timeframe

logging.basicConfig(level=logging.WARNING)

IS_START = datetime(2015, 1, 1, tzinfo=timezone.utc)
IS_END   = datetime(2022, 12, 31, tzinfo=timezone.utc)
OOS_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
OOS_END   = datetime(2025, 12, 1, tzinfo=timezone.utc)

TFS = (Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15, Timeframe.M5)


@dataclass
class OOSResult:
    label: str
    is_n: int
    is_exp: float
    is_sharpe: float
    is_q: float
    oos_n: int
    oos_exp: float
    oos_sharpe: float
    oos_p: float
    validated: bool
    reason: str


def _make_factories():
    """The same two zone configurations used in the definitive grid."""
    return {
        "zone":            lambda c: SupplyDemandAlpha(c),
        "zone_d1_against": lambda c: SupplyDemandAlpha(
            c, htf_align="D1", htf_align_mode="against",
            htf_lookback=10, htf_min_move_pips=60.0,
        ),
    }


def _slice_by_time(bars: list[Bar], lo: datetime, hi: datetime) -> list[Bar]:
    return [b for b in bars if lo <= b.time <= hi]


def main() -> None:
    cfg = load_config()
    loader = BarLoader(cache_root=cfg.data_dir)
    # Load full window once per TF — the OOS replay needs the entire bar
    # series so detectors get warmup before the OOS window starts.
    bars_full: dict[str, list[Bar]] = {}
    for tf in TFS:
        df = loader.get(cfg.symbol, tf, IS_START, OOS_END, refresh=False)
        bars_full[tf.value] = df_to_bars(df, tf)
        print(f"  loaded {tf.value}: {len(bars_full[tf.value]):,} bars")

    bars_is = {tf: _slice_by_time(bs, IS_START, IS_END) for tf, bs in bars_full.items()}

    factories = _make_factories()
    cells = [
        AblationCell(alpha_name=name, timeframe=tf.value, session=sess,
                     alpha_factory=fac)
        for name, fac in factories.items()
        for tf in TFS
        for sess in ALL_SESSIONS
    ]

    # ---- Step 1: IS re-grid on 2015-2022 only ------------------------------
    print(f"\n{'=' * 100}\nIN-SAMPLE GRID   2015-2022   "
          f"{sum(len(b) for b in bars_is.values()):,} bars total\n{'=' * 100}\n")
    def _prog(k, n, c):
        if k == 1 or k == n or k % 10 == 0:
            print(f"  IS [{k:>3}/{n}] {c.label}", flush=True)
    is_grid = run_grid(cells, bars_is, cfg, n_resamples=1000, progress=_prog)

    is_survivors = is_grid.survivors
    print(f"\n  IS BH-significant cells (FDR 5%): {len(is_survivors)} / {len(cells)}")
    for r in sorted(is_survivors, key=lambda x: x.q_value):
        print(f"    {r.cell.label:<48} n={r.scorecard.n_trades:>4}  "
              f"exp={r.scorecard.expectancy.value:+.4f}  "
              f"sharpe={r.scorecard.base.sharpe:+.2f}  q={r.q_value:.4f}")

    if not is_survivors:
        print("\nIS grid produced no BH survivors — nothing to validate. "
              "The 2015-2025 grid's edges were entirely 2023-2025 effects.")
        return

    # ---- Step 2: OOS replay of each IS survivor ----------------------------
    print(f"\n{'=' * 100}\nOUT-OF-SAMPLE REPLAY   2023-01-01 → 2025-12-01\n"
          f"{'=' * 100}\n")

    # Precompute per-TF contexts on the FULL series. The alpha walks the
    # whole series; we filter trades to the OOS window afterwards.
    ctx_full = {tf.value: precompute(bars_full[tf.value], cfg) for tf in TFS}

    oos_results: list[OOSResult] = []
    for r in is_survivors:
        cell = r.cell
        bars = bars_full[cell.timeframe]
        ctx = ctx_full[cell.timeframe]
        alpha = cell.alpha_factory(cfg)
        all_trades = run_alpha(alpha, bars, cfg, ctx=ctx, start_index=200)
        # Filter to OOS entry time AND target session.
        target_session = cell.session
        oos_trades = [
            t for t in all_trades
            if t.exit_time is not None
            and OOS_START <= t.entry_time <= OOS_END
            and (target_session == "all" or label_session(t.entry_time) == target_session)
        ]
        oos_card = make_scorecard(cell.label + "/OOS", oos_trades,
                                  cfg.backtest.initial_balance, n_resamples=1000)
        oos_p = bootstrap_p_value([t.pnl for t in oos_trades], n_resamples=1000)

        is_exp = r.scorecard.expectancy.value
        oos_exp = oos_card.expectancy.value
        oos_n = oos_card.n_trades
        # Validation rule: positive OOS exp, raw p < 0.05, and at least 30%
        # of IS exp retained. Thin OOS (n<20) is auto-fail to avoid noise.
        if oos_n < 20:
            validated, reason = False, f"thin (n={oos_n})"
        elif oos_exp <= 0:
            validated, reason = False, f"negative OOS exp ({oos_exp:+.2f})"
        elif oos_p > 0.05:
            validated, reason = False, f"OOS p={oos_p:.4f}"
        elif oos_exp < 0.30 * is_exp:
            validated, reason = False, f"degraded ({oos_exp / is_exp:.0%} of IS)"
        else:
            validated, reason = True, "ok"

        oos_results.append(OOSResult(
            label=cell.label,
            is_n=r.scorecard.n_trades, is_exp=is_exp,
            is_sharpe=r.scorecard.base.sharpe, is_q=r.q_value,
            oos_n=oos_n, oos_exp=oos_exp,
            oos_sharpe=oos_card.base.sharpe, oos_p=oos_p,
            validated=validated, reason=reason,
        ))

    # ---- Report ------------------------------------------------------------
    print(f"\n{'cell':<48} {'is_n':>5} {'is_exp':>8} {'is_q':>6} "
          f"| {'oos_n':>5} {'oos_exp':>8} {'oos_p':>6} {'oos_S':>6} "
          f"| valid? reason")
    print("-" * 130)
    for r in oos_results:
        v = "PASS" if r.validated else "FAIL"
        print(f"{r.label:<48} {r.is_n:>5} {r.is_exp:>+8.2f} {r.is_q:>6.3f} "
              f"| {r.oos_n:>5} {r.oos_exp:>+8.2f} {r.oos_p:>6.3f} {r.oos_sharpe:>+6.2f} "
              f"|  {v}  {r.reason}")

    n_pass = sum(1 for r in oos_results if r.validated)
    print("-" * 130)
    print(f"\nOOS-validated cells: {n_pass} / {len(oos_results)}  "
          f"({n_pass / len(oos_results):.0%} retention)\n")


if __name__ == "__main__":
    main()
