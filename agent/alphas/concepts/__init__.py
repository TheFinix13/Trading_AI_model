"""Per-concept alpha implementations — v4 (zone-only).

Iteration history (kept here as the v2/v3/v4 grids are the only thing standing
between us and re-introducing dead concepts by accident):

v1 → v2 deleted ``bos``, ``orderblock``, ``fib`` (noise/thin across H1+H4).
v3 → v3.2 added ``zone`` improvements (kept), ``momentum`` BOS-context gate
            (kept), then ``liquidity_sweep`` wick-quality gate (broken — see
            module docstring) and ``fvg_retest`` killzone gate (still noise).
v3.3 deleted ``fvg_retest`` (no signal after two improvement passes) and
            reverted the broken ``liquidity_sweep`` v3 changes.
v4   deleted ``momentum`` and ``liquidity_sweep`` after the post-speedup
            grids confirmed they have no edge on any TF (H4 / H1 / M15) under
            any variant we tried (baseline / HTF-with / HTF-against / relaxed
            BOS-context). Evidence:

              * fair-shot grid (40 cells, momentum + sweep × H1 + H4-relaxed):
                **0 BH survivors at FDR 5%.**
              * M15 grid (30 cells, all three concepts): **0 BH survivors**
                from momentum or sweep. Sweep was actively negative
                (n=3416, exp -2.69 on M15/all). Momentum was thin (best n=8).
              * The definitive zone grid across {D1, H4, H1, M15, M5}
                produced **13 BH survivors at FDR 5%**, all in the zone
                family. See ``scripts/run_zone_all_tfs.py``.

The sole surviving concept:

* :class:`SupplyDemandAlpha` — fresh demand/supply zones with optional HTF
  alignment knob (``htf_align``, ``htf_align_mode``). The HTF gate has a
  proven inverse role: counter-trend mode (``htf_align="D1",
  htf_align_mode="against", htf_lookback=10, htf_min_move_pips=60``)
  sharpens H1 and H4-Asia cells; baseline (no HTF gate) is better on M15
  and H4-overlap. See ``agent/alphas/zone_routing.py`` for the
  by-(TF, session) deployment table.
"""
from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha

ALL_CONCEPT_ALPHAS = {
    "zone": SupplyDemandAlpha,
}

__all__ = [
    "ALL_CONCEPT_ALPHAS",
    "SupplyDemandAlpha",
]
