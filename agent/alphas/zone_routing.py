"""Zone-alpha (symbol, TF, session) deployment router — validated cells only.

Selection history:

1. ``scripts/run_zone_all_tfs.py`` surfaced 13 cells with BH-significant
   edge on the full 2015-2025 EURUSD window. Entire window was in-sample
   for the selection process, so q-values overstated the true edge.

2. ``scripts/run_holdout_validation.py`` split into IS=2015-2022 /
   OOS=2023-2025. Of 8 IS-survivors, only ``zone_d1_against/H4/asia``
   passed at OOS p<=0.05. We initially deployed only that cell.

3. ``scripts/run_walk_forward.py`` ran 7 rolling 4yr-IS / 1yr-OOS
   windows over 2015-2025 and showed the Asia restriction was selection
   bias: ``zone_d1_against`` on H4 across ALL sessions has the same
   per-trade edge (+11.34), 4x the trades, and positive OOS expectancy
   in 7/7 windows. That promoted ``EURUSD / H4 / all`` to primary.
   See ``docs/reviews/2026-06-09_walk_forward.md``.

4. ``scripts/run_cross_pair_frozen.py`` ran the deployed config
   byte-for-byte (zero re-tuning) on GBPUSD and USDCAD — pairs the
   research pipeline had never touched — with costs scaled UP (x1.5 /
   x1.8 vs EURUSD). Because nothing was fit to these pairs, their
   entire 2015-2025 history is out-of-sample. Both passed (GBPUSD
   11/11 positive years, USDCAD 10/11), so the router became
   multi-symbol with those two cells deployed at HALF risk until live
   results confirm the backtest.
   See ``docs/reviews/2026-06-10_cross_pair_frozen.md``.

Deployment policy:

* ``EURUSD / H4 / all``  — risk_scale 1.0 (full pipeline + walk-forward).
* ``GBPUSD / H4 / all``  — risk_scale 0.5 (frozen cross-pair evidence).
* ``USDCAD / H4 / all``  — risk_scale 0.5 (frozen cross-pair evidence).
* Everything else defaults to ``skip`` until evidence promotes it.

Modes:

* ``baseline``     — vanilla :class:`SupplyDemandAlpha`, no HTF gate.
* ``htf_against``  — :class:`SupplyDemandAlpha` with
  ``htf_align="D1", htf_align_mode="against", htf_lookback=10,
  htf_min_move_pips=60``.

Reach for :data:`CANDIDATE_CELLS` only when you want to widen the deployment
intentionally; the default :func:`route` and :func:`alpha_for` never return
candidate cells.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha
from agent.config import Config

Mode = Literal["baseline", "htf_against", "skip"]

EvidenceSource = Literal["walk_forward", "frozen_cross_pair"]


@dataclass(frozen=True)
class ZoneCellEvidence:
    """The validation record that justifies a router entry.

    Field semantics depend on ``source`` — do not compare metrics across
    sources without reading this:

    ``source == "walk_forward"`` (7 rolling 4yr-IS / 1yr-OOS windows,
    ``scripts/run_walk_forward.py``):

    * ``oos_n``           — average OOS sample size per window
    * ``oos_expectancy``  — median OOS expectancy (pips/trade) across windows
    * ``oos_sharpe``      — N/A under walk-forward; median IS Sharpe is
      stored as a rough proxy. Live monitoring should track rolling Sharpe.
    * ``oos_p``           — fraction of OOS windows that hit p<=0.05
      (an OOS-significance RATE, not a p-value)
    * ``is_n`` / ``is_expectancy`` / ``is_sharpe`` — IS stats from the
      most recent window (2021-2024)
    * ``is_q``            — best q-value across all 7 IS windows

    ``source == "frozen_cross_pair"`` (deployed config run byte-for-byte
    on a pair no parameter was ever fit to, ``scripts/run_cross_pair_frozen.py``):

    * ``oos_n``           — TOTAL trades over the full 2015-2025 history
      (the entire history is OOS: nothing was fit to the pair)
    * ``oos_expectancy``  — expectancy (pips/trade) at costs scaled UP to
      that pair's realistic retail spread
    * ``oos_sharpe``      — annualized Sharpe over the full history
    * ``oos_p``           — plain bootstrap p-value over the full history
      (a real p-value, unlike the walk-forward rate above)
    * ``is_*``            — ``None``. No in-sample exists for these pairs
      by construction.
    """
    source: EvidenceSource
    oos_n: int
    oos_expectancy: float
    oos_sharpe: float
    oos_p: float
    is_n: int | None = None
    is_expectancy: float | None = None
    is_sharpe: float | None = None
    is_q: float | None = None


@dataclass(frozen=True)
class RouteEntry:
    """One routing decision: how to trade a cell and at what size.

    ``risk_scale`` multiplies the caller's normal per-trade risk. 1.0 for
    fully-validated cells, 0.5 for frozen-cross-pair deployments awaiting
    live confirmation, 0.0 for ``skip`` (and for candidates, which are
    tracked but never routed)."""
    mode: Mode
    risk_scale: float
    evidence: ZoneCellEvidence | None


_SKIP = RouteEntry("skip", 0.0, None)


# (symbol, TF, session) → RouteEntry.
#
# EURUSD rows come from scripts/run_walk_forward.py (2026-06-09 run);
# GBPUSD / USDCAD rows from scripts/run_cross_pair_frozen.py (2026-06-10
# run). Every key not present here routes to ``skip`` via route()'s
# default, so the explicit skip rows below are documentation of cells we
# actually examined and rejected, not an exhaustive grid.
ROUTING_TABLE: dict[tuple[str, str, str], RouteEntry] = {
    # ================= EURUSD =================
    # ---- D1 ---- (positive OOS in 6/7 windows but borderline IS BH-pass;
    # tracked in CANDIDATE_CELLS, not deployed)
    ("EURUSD", "D1", "all"):                _SKIP,
    ("EURUSD", "D1", "asia"):               _SKIP,
    ("EURUSD", "D1", "london"):             _SKIP,
    ("EURUSD", "D1", "london_ny_overlap"):  _SKIP,
    ("EURUSD", "D1", "ny"):                 _SKIP,

    # ---- H4 ---- (deploy htf_against on ALL sessions; walk-forward
    # shows Asia-only is a redundant subset with smaller sample)
    ("EURUSD", "H4", "all"): RouteEntry("htf_against", 1.0, ZoneCellEvidence(
        source="walk_forward",
        oos_n=66, oos_expectancy=11.34, oos_sharpe=3.50, oos_p=0.43,
        is_n=68, is_expectancy=14.66, is_sharpe=3.50, is_q=0.002,
    )),
    ("EURUSD", "H4", "asia"):               _SKIP,  # subset of H4/all
    ("EURUSD", "H4", "london"):             _SKIP,
    ("EURUSD", "H4", "london_ny_overlap"):  _SKIP,
    ("EURUSD", "H4", "ny"):                 _SKIP,

    # ---- H1 ---- (positive OOS in 5/7 windows but median exp only
    # +0.61, costs likely eat the edge in live trading)
    ("EURUSD", "H1", "all"):                _SKIP,
    ("EURUSD", "H1", "london"):             _SKIP,
    ("EURUSD", "H1", "london_ny_overlap"):  _SKIP,
    ("EURUSD", "H1", "ny"):                 _SKIP,
    ("EURUSD", "H1", "asia"):               _SKIP,

    # ---- M15 / M5 ---- (no consistent edge after walk-forward)
    ("EURUSD", "M15", "all"):               _SKIP,
    ("EURUSD", "M15", "london"):            _SKIP,
    ("EURUSD", "M15", "london_ny_overlap"): _SKIP,
    ("EURUSD", "M15", "ny"):                _SKIP,
    ("EURUSD", "M15", "asia"):              _SKIP,
    ("EURUSD", "M5", "all"):                _SKIP,
    ("EURUSD", "M5", "london"):             _SKIP,
    ("EURUSD", "M5", "london_ny_overlap"):  _SKIP,
    ("EURUSD", "M5", "ny"):                 _SKIP,
    ("EURUSD", "M5", "asia"):               _SKIP,

    # ================= GBPUSD =================
    # Frozen cross-pair test: 11/11 positive years at x1.5 EURUSD costs.
    # Half risk until live results confirm the backtest.
    ("GBPUSD", "H4", "all"): RouteEntry("htf_against", 0.5, ZoneCellEvidence(
        source="frozen_cross_pair",
        oos_n=1161, oos_expectancy=10.24, oos_sharpe=2.42, oos_p=0.001,
    )),
    # D1 was weak cross-pair (6/11 positive years, p=0.170) — examined
    # and rejected, do not deploy.
    ("GBPUSD", "D1", "all"):                _SKIP,

    # ================= USDCAD =================
    # Frozen cross-pair test: 10/11 positive years at x1.8 EURUSD costs.
    # Half risk until live results confirm the backtest.
    ("USDCAD", "H4", "all"): RouteEntry("htf_against", 0.5, ZoneCellEvidence(
        source="frozen_cross_pair",
        oos_n=858, oos_expectancy=4.63, oos_sharpe=1.16, oos_p=0.028,
    )),
    # D1 was weak cross-pair (8/11 positive years, p=0.071) — examined
    # and rejected, do not deploy.
    ("USDCAD", "D1", "all"):                _SKIP,
}


# Cells that show consistently-positive OOS expectancy but didn't qualify
# as deployments. Do NOT route from this list without re-running the
# relevant validation script and verifying stability.
#
# The frozen cross-pair test (2026-06-10) WEAKENED the D1 promotion case:
# D1 cross-pair results were poor (GBPUSD 6/11, USDCAD 8/11 positive
# years, both p>0.05), so the honest next deployments were the same H4
# strategy on GBPUSD/USDCAD — now in ROUTING_TABLE — not D1 on EURUSD.
# EURUSD D1/all stays a candidate pending more OOS data (post-2025).
CANDIDATE_CELLS: dict[tuple[str, str, str], RouteEntry] = {
    # Same alpha as the primary (htf_against) but slower TF — confirms
    # the cross-TF edge exists on EURUSD. 71% positive OOS windows,
    # median exp +6.90, ~30 trades/window.
    ("EURUSD", "D1", "all"): RouteEntry("htf_against", 0.0, ZoneCellEvidence(
        source="walk_forward",
        oos_n=30, oos_expectancy=6.90, oos_sharpe=2.0, oos_p=0.29,
        is_n=46, is_expectancy=9.0, is_sharpe=2.0, is_q=0.02,
    )),
}


def route(symbol: str, tf: str, session: str) -> RouteEntry:
    """Return the :class:`RouteEntry` for a (symbol, TF, session) cell.
    Unknown cells default to ``skip`` (risk_scale 0.0, no evidence) so a
    typo can't accidentally promote a cell. Candidate cells are NOT
    routed; consult :data:`CANDIDATE_CELLS` directly if you want them."""
    return ROUTING_TABLE.get((symbol, tf, session), _SKIP)


def alpha_for(symbol: str, tf: str, session: str,
              cfg: Config | None = None) -> SupplyDemandAlpha | None:
    """Construct the right :class:`SupplyDemandAlpha` for a (symbol, TF,
    session) deployment, or ``None`` if the cell is ``skip``.

    Live-trading callers should consult this rather than hard-coding zone
    parameters — it keeps the alpha-on-the-wire in sync with the validated
    routing table. For position sizing, multiply normal risk by
    ``route(symbol, tf, session).risk_scale``.
    """
    entry = route(symbol, tf, session)
    if entry.mode == "skip":
        return None
    if entry.mode == "baseline":
        return SupplyDemandAlpha(cfg)
    if entry.mode == "htf_against":
        return SupplyDemandAlpha(
            cfg, htf_align="D1", htf_align_mode="against",
            htf_lookback=10, htf_min_move_pips=60.0,
        )
    raise ValueError(f"unknown routing mode: {entry.mode!r}")


def survivors() -> list[tuple[str, str, str, RouteEntry]]:
    """All (symbol, TF, session, entry) tuples the router will deploy.
    Useful for live-trading config validation and dashboards."""
    out = []
    for (symbol, tf, sess), entry in ROUTING_TABLE.items():
        if entry.mode != "skip" and entry.evidence is not None:
            out.append((symbol, tf, sess, entry))
    return out
