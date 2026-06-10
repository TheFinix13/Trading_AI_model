"""Single-strategy ablation grid (Stage 1 of the v2 roadmap).

A *cell* is one isolated (alpha, timeframe, session) triple. The grid runs each
cell in its own context so 224 cells (7 alphas × 8 TFs × 4 sessions) can't
silently corrupt each other through shared mutable detector state.

Why "fresh context per cell": several detectors mutate the objects they emit
(``zone.mitigated`` flips when a zone is consumed, ``fvg.fill_pct`` accumulates
penetration, ``fvg.revisit_count`` increments). The v2 reset already burned the
worst offender (Phase-2 ``check_retest_entries``), but parallel cells reading the
same ``ctx.fvgs`` / ``ctx.zones`` lists from a shared ``PrecomputedContext`` would
still leak state across cells. Each cell here gets a freshly-built context.

Session bucketing happens **after** the alpha runs, not as a pre-filter. The
alpha sees every bar (so its detectors have continuous history); we then keep
only the trades whose **entry bar** falls in the target session. ``"all"``
means no filter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from agent.alphas.backtest import run_alpha
from agent.alphas.base import Alpha
from agent.backtest.metrics import (
    Scorecard,
    benjamini_hochberg,
    bootstrap_p_value,
    make_scorecard,
)
from agent.config import Config
from agent.detectors.sessions import label_session
from agent.rules.engine import precompute
from agent.types import Bar, Trade

SessionFilter = str  # one of: "all", "london", "london_ny_overlap", "ny", "asia", "off"

ALL_SESSIONS: tuple[SessionFilter, ...] = (
    "all", "london", "london_ny_overlap", "ny", "asia",
)


@dataclass(frozen=True)
class AblationCell:
    """One (alpha, timeframe, session) triple.

    ``alpha_factory`` builds a *fresh* alpha instance per run; passing a single
    instance between cells would share any internal caches (`set_htf_draws`,
    `_engine` state, etc.) and corrupt the isolation contract.
    """
    alpha_name: str
    timeframe: str
    session: SessionFilter
    alpha_factory: Callable[[Config], Alpha]

    @property
    def label(self) -> str:
        return f"{self.alpha_name}/{self.timeframe}/{self.session}"


@dataclass
class CellResult:
    cell: AblationCell
    trades: list[Trade]
    scorecard: Scorecard
    p_value: float
    q_value: float = float("nan")  # filled in by ``run_grid`` after BH
    rejected: bool = False          # ditto


@dataclass
class GridResult:
    fdr: float
    cells: list[CellResult] = field(default_factory=list)

    @property
    def survivors(self) -> list[CellResult]:
        """Cells that beat the FDR floor — the only ones to consider further."""
        return [c for c in self.cells if c.rejected]


def _filter_by_session(trades: Sequence[Trade], session: SessionFilter) -> list[Trade]:
    if session == "all":
        return [t for t in trades if t.exit_time is not None]
    return [
        t for t in trades
        if t.exit_time is not None and label_session(t.entry_time) == session
    ]


def run_cell(
    cell: AblationCell,
    bars: list[Bar],
    cfg: Config,
    *,
    start_index: int = 200,
    n_resamples: int = 1000,
    ci_level: float = 0.95,
) -> CellResult:
    """Run a single ablation cell on a fresh context. Used by tests; the
    grid runner :func:`run_grid` skips re-running the alpha across session
    siblings since session is a post-filter."""
    ctx = precompute(bars, cfg)  # fresh per cell — no shared mutable state
    alpha = cell.alpha_factory(cfg)
    all_trades = run_alpha(alpha, bars, cfg, ctx=ctx, start_index=start_index)
    return _score_cell(cell, all_trades, cfg,
                       n_resamples=n_resamples, ci_level=ci_level)


def _score_cell(
    cell: AblationCell,
    all_trades: list[Trade],
    cfg: Config,
    *,
    n_resamples: int,
    ci_level: float,
) -> CellResult:
    trades = _filter_by_session(all_trades, cell.session)
    card = make_scorecard(cell.label, trades, cfg.backtest.initial_balance,
                          n_resamples=n_resamples, ci_level=ci_level)
    pnls = [t.pnl for t in trades]
    p = bootstrap_p_value(pnls, n_resamples=n_resamples)
    return CellResult(cell=cell, trades=trades, scorecard=card, p_value=p)


def run_grid(
    cells: Iterable[AblationCell],
    bars_by_tf: dict[str, list[Bar]],
    cfg: Config,
    *,
    fdr: float = 0.05,
    start_index: int = 200,
    n_resamples: int = 1000,
    ci_level: float = 0.95,
    progress: Callable[[int, int, AblationCell], None] | None = None,
) -> GridResult:
    """Run every cell, then apply Benjamini-Hochberg across all p-values.

    ``bars_by_tf`` is a ``{tf: [Bar, ...]}`` map so callers can load each
    timeframe's parquet exactly once and reuse it across every cell on that TF.
    Cells whose timeframe is missing from the map are skipped with an empty
    scorecard so the grid call is still rectangular.

    Performance contract — two levels of work-sharing:
      * Cells differing only in ``session`` share the underlying alpha-on-TF
        run. Session is a post-filter on the trade list, so running it 5× per
        (alpha, TF) would be 5× wasted detector + bootstrap work.
      * Cells differing only in ``alpha`` (same TF) share the precomputed
        detector context. ``precompute`` is the bottleneck (~5 minutes per
        H1 call) and is purely read-only — none of the active alphas mutate
        ctx. A second TF gets a separately-cached context.

    Isolation contract: a fresh ``Alpha`` instance per ``(alpha, TF)`` pair,
    so any alpha-internal state (e.g. the BOS-index cache attached to ctx)
    stays scoped to that pair's lifetime. If a future alpha needs to mutate
    the context, give it its own group and a deep-copied ctx.
    """
    cells = list(cells)
    results: list[CellResult] = []

    # Group cells by (alpha, TF). Each group shares one alpha run.
    groups: dict[tuple[str, str], list[AblationCell]] = {}
    for c in cells:
        groups.setdefault((c.alpha_name, c.timeframe), []).append(c)

    # One ctx per TF, computed lazily on first request.
    ctx_by_tf: dict[str, object] = {}

    cell_to_result: dict[int, CellResult] = {}
    done = 0
    total = len(cells)
    for (alpha_name, tf), group_cells in groups.items():
        bars = bars_by_tf.get(tf)
        if not bars:
            for c in group_cells:
                done += 1
                if progress is not None:
                    progress(done, total, c)
                cell_to_result[id(c)] = CellResult(
                    cell=c, trades=[],
                    scorecard=make_scorecard(c.label, [], cfg.backtest.initial_balance,
                                             n_resamples=n_resamples, ci_level=ci_level),
                    p_value=1.0,
                )
            continue
        ctx = ctx_by_tf.get(tf)
        if ctx is None:
            ctx = precompute(bars, cfg)
            ctx_by_tf[tf] = ctx
        alpha = group_cells[0].alpha_factory(cfg)
        all_trades = run_alpha(alpha, bars, cfg, ctx=ctx, start_index=start_index)
        for c in group_cells:
            done += 1
            if progress is not None:
                progress(done, total, c)
            cell_to_result[id(c)] = _score_cell(
                c, all_trades, cfg,
                n_resamples=n_resamples, ci_level=ci_level,
            )

    # Preserve the original cell order in the result list.
    results = [cell_to_result[id(c)] for c in cells]

    rejects, q = benjamini_hochberg([r.p_value for r in results], fdr=fdr)
    for r, rej, qv in zip(results, rejects, q):
        r.rejected = rej
        r.q_value = qv
    return GridResult(fdr=fdr, cells=results)


def format_grid(grid: GridResult) -> str:
    """ASCII table for the ablation grid suitable for terminal + log files."""
    if not grid.cells:
        return "(empty grid)"
    rows = []
    rows.append(
        f"{'cell':<48} {'n':>5} {'exp':>9} {'PF':>6} {'WR':>6} "
        f"{'Sharpe':>7} {'p':>7} {'q':>7} {'BH':>4}  verdict"
    )
    rows.append("-" * len(rows[0]))
    for r in grid.cells:
        s = r.scorecard
        pf = s.profit_factor.value if s.profit_factor.value != float("inf") else 999.0
        flag = "✓" if r.rejected else " "
        rows.append(
            f"{r.cell.label:<48} {s.n_trades:>5d} "
            f"{s.expectancy.value:>+9.4f} {pf:>6.2f} {s.win_rate.value:>6.1%} "
            f"{s.base.sharpe:>7.2f} {r.p_value:>7.4f} {r.q_value:>7.4f} {flag:>4}  "
            f"{s.verdict}"
        )
    rows.append("-" * len(rows[0]))
    rows.append(
        f"FDR={grid.fdr:.2%}   survivors: {len(grid.survivors)} / {len(grid.cells)}"
    )
    return "\n".join(rows)
