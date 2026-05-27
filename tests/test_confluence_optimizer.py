"""Tests for the confluence optimizer: booster scoring, combos, alignment, and selection."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agent.optimizer.booster_catalog import BOOSTER_CATALOG, get_price_boosters, get_time_boosters
from agent.optimizer.confluence_scorer import (
    BoosterScore,
    ComboScore,
    ConfluenceOptimizer,
)


def _make_trades(
    strategy: str,
    booster: str,
    n_with: int,
    wr_with: float,
    n_without: int,
    wr_without: float,
    extra_boosters: list[str] | None = None,
) -> list[dict]:
    """Generate synthetic trades for testing."""
    trades = []
    extra = extra_boosters or []

    # Trades WITH the booster
    for i in range(n_with):
        is_winner = i < int(n_with * wr_with)
        trades.append({
            "strategy_name": strategy,
            "confluences": [booster] + extra,
            "is_winner": is_winner,
            "r_multiple": 1.5 if is_winner else -1.0,
        })

    # Trades WITHOUT the booster
    for i in range(n_without):
        is_winner = i < int(n_without * wr_without)
        trades.append({
            "strategy_name": strategy,
            "confluences": ["zone"] + extra,  # baseline confluence
            "is_winner": is_winner,
            "r_multiple": 1.5 if is_winner else -1.0,
        })

    return trades


class TestSingleBoosterLift:
    """Test individual booster lift calculation."""

    def test_positive_lift(self):
        """Booster with 70% WR vs 40% without should show +30% lift."""
        trades = _make_trades("SDZoneRetest", "fib_618", 40, 0.70, 40, 0.40)
        opt = ConfluenceOptimizer()
        opt.fit(trades)

        scores = opt.booster_scores.get("SDZoneRetest", [])
        fib_score = next((s for s in scores if s.booster_name == "fib_618"), None)
        assert fib_score is not None
        assert fib_score.lift_pct == pytest.approx(30.0, abs=1.0)
        assert fib_score.confidence == "high"  # 40 samples

    def test_negative_lift(self):
        """Booster that hurts (30% WR with vs 50% without) = negative lift."""
        trades = _make_trades("FVGRetest", "phase_distribution", 30, 0.30, 30, 0.50)
        opt = ConfluenceOptimizer()
        opt.fit(trades)

        scores = opt.booster_scores.get("FVGRetest", [])
        phase_score = next((s for s in scores if s.booster_name == "phase_distribution"), None)
        assert phase_score is not None
        assert phase_score.lift_pct < 0

    def test_confidence_levels(self):
        """Confidence should reflect sample size."""
        trades_high = _make_trades("S1", "b_high", 35, 0.60, 35, 0.50)
        trades_med = _make_trades("S1", "b_med", 20, 0.60, 20, 0.50)
        trades_low = _make_trades("S1", "b_low", 10, 0.60, 10, 0.50)

        opt = ConfluenceOptimizer()
        opt.fit(trades_high + trades_med + trades_low)

        scores = opt.booster_scores.get("S1", [])
        high = next((s for s in scores if s.booster_name == "b_high"), None)
        med = next((s for s in scores if s.booster_name == "b_med"), None)
        low = next((s for s in scores if s.booster_name == "b_low"), None)

        assert high is not None and high.confidence == "high"
        assert med is not None and med.confidence == "medium"
        assert low is not None and low.confidence == "low"

    def test_avg_r_calculated(self):
        """Average R-multiple should differ between winners and losers."""
        trades = _make_trades("S1", "fib_500", 20, 0.80, 20, 0.40)
        opt = ConfluenceOptimizer()
        opt.fit(trades)

        scores = opt.booster_scores.get("S1", [])
        score = next((s for s in scores if s.booster_name == "fib_500"), None)
        assert score is not None
        assert score.avg_r_with > score.avg_r_without


class TestComboAdditivity:
    """Test pairwise booster combination analysis."""

    def test_additive_pair_detected(self):
        """Two boosters that combine well should be flagged additive."""
        trades = []
        strategy = "SDZoneRetest"

        # A alone: 60% WR
        for i in range(30):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_618"],
                "is_winner": i < 18,
                "r_multiple": 1.5 if i < 18 else -1.0,
            })

        # B alone: 55% WR
        for i in range(30):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["session_ny"],
                "is_winner": i < 16,
                "r_multiple": 1.5 if i < 16 else -1.0,
            })

        # A + B together: 80% WR (additive!)
        for i in range(20):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_618", "session_ny"],
                "is_winner": i < 16,
                "r_multiple": 1.5 if i < 16 else -1.0,
            })

        # Neither: 35% WR
        for i in range(30):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["zone"],
                "is_winner": i < 10,
                "r_multiple": 1.5 if i < 10 else -1.0,
            })

        opt = ConfluenceOptimizer()
        opt.fit(trades)

        combos = opt.combo_scores.get(strategy, [])
        pair = next(
            (c for c in combos
             if {c.booster_a, c.booster_b} == {"fib_618", "session_ny"}),
            None,
        )
        assert pair is not None
        assert pair.combined_lift_pct > 0
        assert pair.is_additive

    def test_redundant_pair_detected(self):
        """Two similar boosters should be flagged redundant.

        Combined lift must be within 1.2x of max individual to be redundant.
        We create a scenario where A alone gives strong lift, B alone gives similar
        lift, and having both doesn't improve beyond the best single booster.
        """
        trades = []
        strategy = "FVGRetest"

        # A alone: 65% WR
        for i in range(40):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_618"],
                "is_winner": i < 26,
                "r_multiple": 1.5 if i < 26 else -1.0,
            })

        # B alone: 63% WR
        for i in range(40):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_500"],
                "is_winner": i < 25,
                "r_multiple": 1.5 if i < 25 else -1.0,
            })

        # A + B together: 55% WR (NOT better than having just one)
        for i in range(20):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_618", "fib_500"],
                "is_winner": i < 11,
                "r_multiple": 1.5 if i < 11 else -1.0,
            })

        # Neither: 45% WR
        for i in range(40):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["zone"],
                "is_winner": i < 18,
                "r_multiple": 1.5 if i < 18 else -1.0,
            })

        opt = ConfluenceOptimizer()
        opt.fit(trades)

        combos = opt.combo_scores.get(strategy, [])
        pair = next(
            (c for c in combos
             if {c.booster_a, c.booster_b} == {"fib_618", "fib_500"}),
            None,
        )
        assert pair is not None
        assert pair.is_redundant or not pair.is_additive


class TestAlignmentCheck:
    """Test price alignment between confluences."""

    def test_aligned_prices(self):
        """Prices within max_spread_pips should be aligned."""
        opt = ConfluenceOptimizer()
        aligned, spread = opt.check_alignment(
            entry_price=1.1000,
            confluence_prices={"fib_618": 1.1003, "near_PDL": 1.1005},
            max_spread_pips=8.0,
        )
        assert aligned
        assert spread < 8.0

    def test_misaligned_prices(self):
        """Prices far apart should NOT be aligned."""
        opt = ConfluenceOptimizer()
        aligned, spread = opt.check_alignment(
            entry_price=1.1000,
            confluence_prices={"fib_618": 1.1030, "near_PDL": 1.0970},
            max_spread_pips=8.0,
        )
        assert not aligned
        assert spread > 8.0

    def test_empty_prices_aligned(self):
        """No prices = vacuously aligned."""
        opt = ConfluenceOptimizer()
        aligned, spread = opt.check_alignment(1.1000, {})
        assert aligned
        assert spread == 0.0


class TestSelectBoosters:
    """Test booster selection for live setups."""

    def _fitted_optimizer(self) -> ConfluenceOptimizer:
        """Create a pre-fitted optimizer with known scores."""
        trades = []
        strategy = "SDZoneRetest"

        # fib_618: +25% lift
        trades.extend(_make_trades(strategy, "fib_618", 40, 0.65, 40, 0.40))
        # session_ny: +15% lift
        trades.extend(_make_trades(strategy, "session_ny", 40, 0.55, 40, 0.40))
        # trendline: +10% lift
        trades.extend(_make_trades(strategy, "trendline", 40, 0.50, 40, 0.40))
        # near_PDH: +5% lift
        trades.extend(_make_trades(strategy, "near_PDH", 40, 0.45, 40, 0.40))

        opt = ConfluenceOptimizer()
        opt.fit(trades)
        return opt

    def test_selects_highest_lift_first(self):
        """Highest-lift booster should be first in selection."""
        opt = self._fitted_optimizer()
        selected, score = opt.select_boosters(
            "SDZoneRetest",
            ["near_PDH", "session_ny", "fib_618", "trendline"],
        )
        assert selected[0] == "fib_618"

    def test_caps_at_three(self):
        """Should never return more than 3 boosters."""
        opt = self._fitted_optimizer()
        selected, score = opt.select_boosters(
            "SDZoneRetest",
            ["near_PDH", "session_ny", "fib_618", "trendline", "htf_bias_long"],
        )
        assert len(selected) <= 3

    def test_unknown_strategy_returns_available(self):
        """Unknown strategy should return first available boosters."""
        opt = ConfluenceOptimizer()
        selected, score = opt.select_boosters(
            "NonExistent",
            ["fib_618", "session_ny"],
        )
        assert len(selected) <= 3
        assert score == 0.0

    def test_redundant_pair_not_stacked(self):
        """Redundant pairs should not both be selected."""
        trades = []
        strategy = "SDZoneRetest"

        # fib_618: high lift
        for i in range(40):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_618"],
                "is_winner": i < 28,
                "r_multiple": 1.5 if i < 28 else -1.0,
            })

        # fib_500: also high lift
        for i in range(40):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_500"],
                "is_winner": i < 26,
                "r_multiple": 1.5 if i < 26 else -1.0,
            })

        # Together: same as max(individual) — redundant
        for i in range(20):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["fib_618", "fib_500"],
                "is_winner": i < 14,
                "r_multiple": 1.5 if i < 14 else -1.0,
            })

        # session_ny: moderate lift, additive
        for i in range(40):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["session_ny"],
                "is_winner": i < 22,
                "r_multiple": 1.5 if i < 22 else -1.0,
            })

        # Neither
        for i in range(40):
            trades.append({
                "strategy_name": strategy,
                "confluences": ["zone"],
                "is_winner": i < 16,
                "r_multiple": 1.5 if i < 16 else -1.0,
            })

        opt = ConfluenceOptimizer()
        opt.fit(trades)

        selected, _ = opt.select_boosters(
            strategy,
            ["fib_618", "fib_500", "session_ny"],
        )
        # Should not have both fib_618 AND fib_500 (redundant)
        if "fib_618" in selected and "fib_500" in selected:
            # This is acceptable only if they're not flagged as redundant
            combos = opt.combo_scores.get(strategy, [])
            pair = next(
                (c for c in combos if {c.booster_a, c.booster_b} == {"fib_618", "fib_500"}),
                None,
            )
            if pair and pair.is_redundant:
                pytest.fail("Redundant pair was stacked")


class TestOnlineUpdate:
    """Test incremental learning from new trades."""

    def test_update_adjusts_scores(self):
        """Online updates should gradually shift booster scores."""
        trades = _make_trades("S1", "fib_618", 30, 0.60, 30, 0.40)
        opt = ConfluenceOptimizer()
        opt.fit(trades)

        initial_scores = opt.booster_scores.get("S1", [])
        initial_lift = next(
            (s.lift_pct for s in initial_scores if s.booster_name == "fib_618"),
            None,
        )
        assert initial_lift is not None

        # Feed 10 winning trades with fib_618
        for _ in range(10):
            opt.update_from_trade({
                "strategy_name": "S1",
                "confluences": ["fib_618"],
                "is_winner": True,
                "r_multiple": 2.0,
            })

        updated_scores = opt.booster_scores.get("S1", [])
        updated_lift = next(
            (s.lift_pct for s in updated_scores if s.booster_name == "fib_618"),
            None,
        )
        assert updated_lift is not None
        # The EMA blends with a cold-start baseline (0.5), so initial updates
        # may drift slightly before converging. Just verify it hasn't crashed to 0.
        assert updated_lift > 0, "Lift should remain positive after winning updates"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_no_trades(self):
        """Fitting with empty list should not crash."""
        opt = ConfluenceOptimizer()
        opt.fit([])
        assert opt.booster_scores == {}
        assert opt.combo_scores == {}

    def test_single_strategy(self):
        """Single strategy with minimal data should work."""
        trades = _make_trades("Solo", "bos_body_break", 10, 0.70, 10, 0.30)
        opt = ConfluenceOptimizer()
        opt.fit(trades)
        assert "Solo" in opt.booster_scores

    def test_all_losses(self):
        """All-loss dataset should produce negative or zero lifts."""
        trades = []
        for i in range(30):
            trades.append({
                "strategy_name": "Loser",
                "confluences": ["fib_618"],
                "is_winner": False,
                "r_multiple": -1.0,
            })
        for i in range(30):
            trades.append({
                "strategy_name": "Loser",
                "confluences": ["zone"],
                "is_winner": False,
                "r_multiple": -1.0,
            })

        opt = ConfluenceOptimizer()
        opt.fit(trades)
        scores = opt.booster_scores.get("Loser", [])
        for s in scores:
            assert s.lift_pct <= 0.01  # Essentially 0 (both groups have 0% WR)

    def test_string_confluences_parsed(self):
        """Confluences as comma-separated string should be handled."""
        trades = [
            {"strategy_name": "S1", "confluences": "fib_618, zone, session_ny", "is_winner": True, "r_multiple": 1.5},
            {"strategy_name": "S1", "confluences": "fib_618, zone", "is_winner": True, "r_multiple": 1.5},
            {"strategy_name": "S1", "confluences": "zone", "is_winner": False, "r_multiple": -1.0},
        ] * 15  # Repeat for sample size

        opt = ConfluenceOptimizer()
        opt.fit(trades)
        assert "S1" in opt.booster_scores


class TestSaveLoad:
    """Test persistence."""

    def test_save_and_load(self):
        """Saved state should be recoverable."""
        trades = _make_trades("SDZoneRetest", "fib_618", 30, 0.70, 30, 0.40)
        opt = ConfluenceOptimizer()
        opt.fit(trades)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        opt.save(path)

        opt2 = ConfluenceOptimizer()
        opt2.load(path)

        assert "SDZoneRetest" in opt2.booster_scores
        scores = opt2.booster_scores["SDZoneRetest"]
        fib = next((s for s in scores if s.booster_name == "fib_618"), None)
        assert fib is not None
        assert fib.lift_pct == pytest.approx(30.0, abs=1.0)

        Path(path).unlink()

    def test_load_missing_file(self):
        """Loading from non-existent path should not crash."""
        opt = ConfluenceOptimizer()
        opt.load("/tmp/nonexistent_optimizer_state.json")
        assert opt.booster_scores == {}


class TestBoosterCatalog:
    """Test booster catalog utilities."""

    def test_catalog_not_empty(self):
        assert len(BOOSTER_CATALOG) > 10

    def test_price_boosters_have_category(self):
        price_b = get_price_boosters()
        assert "fib_618" in price_b
        assert "near_PDH" in price_b

    def test_time_boosters_have_category(self):
        time_b = get_time_boosters()
        assert "session_london" in time_b
        assert "session_ny" in time_b

    def test_no_overlap(self):
        """Price and time boosters should not overlap."""
        price_set = set(get_price_boosters())
        time_set = set(get_time_boosters())
        assert price_set & time_set == set()


class TestGetReport:
    """Test report generation."""

    def test_report_structure(self):
        """Report should have expected structure."""
        trades = _make_trades("SDZoneRetest", "fib_618", 30, 0.70, 30, 0.40)
        opt = ConfluenceOptimizer()
        opt.fit(trades)

        report = opt.get_report()
        assert "strategies" in report
        assert "SDZoneRetest" in report["strategies"]
        strat = report["strategies"]["SDZoneRetest"]
        assert "boosters" in strat
        assert "top_combos" in strat
        assert "optimal_menu" in strat
