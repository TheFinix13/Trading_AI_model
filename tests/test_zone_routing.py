"""Contract tests for the multi-symbol zone routing table.

The routing table is the single source of truth for *where* the zone alpha
deploys. These tests enforce:

  * Unknown (symbol, TF, session) cells default to ``skip`` (fail-safe).
  * ``alpha_for`` returns a properly-configured :class:`SupplyDemandAlpha`
    for every non-skip cell, with the htf_against parameter set locked to
    the values the validation pipeline proved out (no silent drift).
  * Every deployed cell carries evidence appropriate to its ``source``:

      - ``walk_forward`` (EURUSD pipeline): is_q <= 0.05, oos_p >= 0.4
        (interpreted as the OOS-significance RATE across windows),
        positive median OOS expectancy, avg OOS n >= 20.
      - ``frozen_cross_pair`` (zero-retuning pairs): oos_p <= 0.05
        (a plain bootstrap p-value over the full history), positive
        expectancy, n >= 300, AND risk_scale <= 0.5 — frozen-test pairs
        must deploy at reduced risk until live results confirm.

  * EURUSD H4/all deploys at full risk (1.0); every non-EURUSD deployed
    cell at <= 0.5.
  * Candidate cells are tracked separately and are never deployed.
"""
from __future__ import annotations

import pytest

from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha
from agent.alphas.zone_routing import (
    CANDIDATE_CELLS,
    ROUTING_TABLE,
    RouteEntry,
    ZoneCellEvidence,
    alpha_for,
    route,
    survivors,
)
from agent.config import load_config

EXPECTED_DEPLOYED = {
    ("EURUSD", "H4", "all"),
    ("GBPUSD", "H4", "all"),
    ("USDCAD", "H4", "all"),
}


@pytest.mark.parametrize("symbol,tf,session", [
    ("EURUSD", "W1", "tokyo"),       # unknown TF/session
    ("USDJPY", "H4", "all"),         # unknown symbol
    ("GBPUSD", "H1", "all"),         # known symbol, untested cell
])
def test_unknown_cell_defaults_to_skip(symbol: str, tf: str, session: str):
    entry = route(symbol, tf, session)
    assert entry.mode == "skip"
    assert entry.risk_scale == 0.0
    assert entry.evidence is None
    assert alpha_for(symbol, tf, session, load_config()) is None


@pytest.mark.parametrize("symbol,tf,session", list(ROUTING_TABLE.keys()))
def test_alpha_for_returns_correctly_configured_instance(
    symbol: str, tf: str, session: str
):
    cfg = load_config()
    alpha = alpha_for(symbol, tf, session, cfg)
    entry = route(symbol, tf, session)
    if entry.mode == "skip":
        assert alpha is None
        return
    assert isinstance(alpha, SupplyDemandAlpha)
    if entry.mode == "baseline":
        assert alpha.htf_align is None
    elif entry.mode == "htf_against":
        # Lock the htf_against parameter set against the grid that proved it
        # out. Drifting any of these silently invalidates the OOS claim.
        assert alpha.htf_align == "D1"
        assert alpha.htf_align_mode == "against"
        assert alpha.htf_lookback == 10
        assert alpha.htf_min_move_pips == 60.0


def test_deployed_cells_are_exactly_the_validated_three():
    deployed = {key for key, entry in ROUTING_TABLE.items()
                if entry.mode != "skip"}
    assert deployed == EXPECTED_DEPLOYED


def test_survivors_match_routing_table_non_skip_entries():
    table_non_skip = {key for key, entry in ROUTING_TABLE.items()
                      if entry.mode != "skip"}
    surv_entries = {(sym, tf, s) for sym, tf, s, _ in survivors()}
    assert table_non_skip == surv_entries


def test_every_deployed_cell_passes_its_source_gates():
    """Each deployed cell must carry evidence whose metrics clear the gate
    appropriate to how that evidence was produced. Silent drift below any
    threshold means we're shipping a cell the validation didn't support."""
    for symbol, tf, sess, entry in survivors():
        ev = entry.evidence
        cell = f"{symbol}/{tf}/{sess} ({entry.mode})"
        assert isinstance(ev, ZoneCellEvidence)

        if ev.source == "walk_forward":
            assert ev.is_q is not None and ev.is_q <= 0.05, (
                f"{cell}: best-IS-q={ev.is_q} > 0.05; "
                f"no walk-forward IS window passed BH"
            )
            assert ev.oos_p >= 0.4, (
                f"{cell}: OOS-significance-rate={ev.oos_p} < 0.4; fewer "
                f"than 40% of walk-forward OOS windows hit p<=0.05"
            )
            assert ev.oos_expectancy > 0, (
                f"{cell}: median OOS expectancy {ev.oos_expectancy} "
                f"not positive"
            )
            assert ev.oos_n >= 20, (
                f"{cell}: avg OOS n={ev.oos_n} < 20; cell is too thin "
                f"per window for stable inference"
            )
        elif ev.source == "frozen_cross_pair":
            # Entire history is OOS by construction (nothing was fit to
            # the pair), so oos_p here is a plain bootstrap p-value and
            # there are no in-sample fields.
            assert ev.oos_p <= 0.05, (
                f"{cell}: bootstrap p={ev.oos_p} > 0.05 over the full "
                f"frozen history"
            )
            assert ev.oos_expectancy > 0, (
                f"{cell}: frozen-test expectancy {ev.oos_expectancy} "
                f"not positive"
            )
            assert ev.oos_n >= 300, (
                f"{cell}: frozen-test n={ev.oos_n} < 300; sample too "
                f"thin to deploy on"
            )
            assert entry.risk_scale <= 0.5, (
                f"{cell}: risk_scale={entry.risk_scale} > 0.5; frozen-"
                f"test pairs must run reduced risk until live confirmation"
            )
            assert ev.is_n is None and ev.is_q is None, (
                f"{cell}: frozen_cross_pair evidence must not carry IS "
                f"fields — no in-sample exists for unfitted pairs"
            )
        else:
            pytest.fail(f"{cell}: unknown evidence source {ev.source!r}")


def test_risk_scales_by_symbol():
    """EURUSD H4/all earned full risk through the complete research
    pipeline + walk-forward. Cross-pair cells run half risk until live
    results confirm the frozen backtest."""
    eurusd = route("EURUSD", "H4", "all")
    assert eurusd.mode == "htf_against"
    assert eurusd.risk_scale == 1.0

    for symbol, tf, sess, entry in survivors():
        if symbol != "EURUSD":
            assert entry.risk_scale <= 0.5, (
                f"{symbol}/{tf}/{sess}: non-EURUSD deployed cell has "
                f"risk_scale={entry.risk_scale} > 0.5"
            )
        assert entry.risk_scale > 0.0, (
            f"{symbol}/{tf}/{sess}: deployed cell with zero risk_scale "
            f"should be a skip or candidate instead"
        )


def test_candidate_cells_are_separate_from_deployed():
    """Candidates exist for tracking only — they must not appear as
    deployed cells, otherwise we'd be live-trading on borderline
    evidence."""
    deployed = {key for key, entry in ROUTING_TABLE.items()
                if entry.mode != "skip"}
    for key, entry in CANDIDATE_CELLS.items():
        assert key not in deployed, (
            f"candidate cell {key} also appears as a deployed router entry"
        )
        assert entry.risk_scale == 0.0, (
            f"candidate cell {key} has non-zero risk_scale "
            f"{entry.risk_scale} — candidates are never sized"
        )


def test_candidate_cells_have_positive_oos_signal():
    """Candidates exist because they show positive median OOS expectancy
    under walk-forward but couldn't clear the deployment gate. If a
    candidate ever drops below positive median OOS expectancy it should
    be removed (it's no longer a candidate — it's noise)."""
    for (symbol, tf, sess), entry in CANDIDATE_CELLS.items():
        ev = entry.evidence
        assert ev is not None
        assert ev.source == "walk_forward", (
            f"{symbol}/{tf}/{sess}: candidates currently come from the "
            f"walk-forward pipeline only"
        )
        assert ev.oos_expectancy > 0, (
            f"{symbol}/{tf}/{sess} candidate has non-positive median OOS exp"
        )
        # Candidates have OOS-significance-rate below the deployment gate
        # (0.4) but typically still positive; allow [0, 0.4).
        assert 0.0 <= ev.oos_p < 0.4, (
            f"{symbol}/{tf}/{sess} candidate OOS-significance-rate="
            f"{ev.oos_p} outside [0, 0.4) — either promote to "
            f"ROUTING_TABLE or drop"
        )


def test_routing_table_only_uses_known_modes_and_skip_invariants():
    valid = {"baseline", "htf_against", "skip"}
    for key, entry in ROUTING_TABLE.items():
        assert isinstance(entry, RouteEntry)
        assert entry.mode in valid, f"unknown mode {entry.mode!r} for {key}"
        if entry.mode == "skip":
            assert entry.evidence is None and entry.risk_scale == 0.0, (
                f"{key}: skip entries must carry no evidence and zero risk"
            )
        else:
            assert entry.evidence is not None, (
                f"{key}: deployed entries must carry evidence"
            )
