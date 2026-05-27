"""Confluence optimizer: learns which boosters help each strategy and which hurt.

Uses historical trade data to:
1. Score each booster independently (marginal lift per strategy)
2. Test pairwise combos (additive vs redundant)
3. Build an optimal booster menu per strategy
4. At inference time: select best boosters for a given setup
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path

from agent.optimizer.booster_catalog import BOOSTER_CATALOG

log = logging.getLogger(__name__)


@dataclass
class BoosterScore:
    """Performance score for a single confluence booster with a specific strategy."""

    booster_name: str
    strategy_name: str
    lift_pct: float  # WR improvement when this booster is present vs absent
    sample_with: int
    sample_without: int
    confidence: str  # "high" (30+), "medium" (15-29), "low" (<15)
    avg_r_with: float
    avg_r_without: float


@dataclass
class ComboScore:
    """Performance of a booster PAIR — tests if they're additive or redundant."""

    booster_a: str
    booster_b: str
    strategy_name: str
    combined_lift_pct: float  # WR with BOTH vs neither
    is_additive: bool  # Combined > max(individual_a, individual_b)
    is_redundant: bool  # Combined ≈ max(individual_a, individual_b)
    sample_n: int


class ConfluenceOptimizer:
    """Learns which confluence boosters help each strategy and which hurt.

    Uses historical trade data to:
    1. Score each booster independently (marginal lift per strategy)
    2. Test pairwise combos (additive vs redundant)
    3. Build an optimal booster menu per strategy
    4. At inference time: select best boosters for a given setup
    """

    def __init__(self):
        self.booster_scores: dict[str, list[BoosterScore]] = {}
        self.combo_scores: dict[str, list[ComboScore]] = {}
        self.optimal_boosters: dict[str, list[str]] = {}
        self._ema_wins: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._ema_counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def fit(self, trades: list[dict]) -> None:
        """Learn booster scores from historical trade outcomes.

        Each trade dict should have:
          - strategy_name: str
          - confluences: list[str] (booster tags present in the setup)
          - is_winner: bool
          - r_multiple: float (optional, defaults to 1.0/-1.0)
        """
        if not trades:
            return

        # Group trades by strategy
        by_strategy: dict[str, list[dict]] = defaultdict(list)
        for t in trades:
            strat = t.get("strategy_name") or "unknown"
            by_strategy[strat].append(t)

        for strategy, strat_trades in by_strategy.items():
            self._fit_strategy(strategy, strat_trades)

    def _fit_strategy(self, strategy: str, trades: list[dict]) -> None:
        """Compute booster scores for a single strategy."""
        all_boosters = set()
        for t in trades:
            confs = t.get("confluences") or []
            if isinstance(confs, str):
                confs = [c.strip() for c in confs.split(",")]
            all_boosters.update(confs)

        scores: list[BoosterScore] = []

        for booster in all_boosters:
            with_booster = [t for t in trades if booster in (t.get("confluences") or [])]
            without_booster = [t for t in trades if booster not in (t.get("confluences") or [])]

            n_with = len(with_booster)
            n_without = len(without_booster)

            if n_with < 3 or n_without < 3:
                continue

            wr_with = sum(1 for t in with_booster if t.get("is_winner")) / n_with
            wr_without = sum(1 for t in without_booster if t.get("is_winner")) / n_without

            avg_r_with = _avg_r(with_booster)
            avg_r_without = _avg_r(without_booster)

            lift = (wr_with - wr_without) * 100.0

            if n_with >= 30:
                confidence = "high"
            elif n_with >= 15:
                confidence = "medium"
            else:
                confidence = "low"

            scores.append(BoosterScore(
                booster_name=booster,
                strategy_name=strategy,
                lift_pct=lift,
                sample_with=n_with,
                sample_without=n_without,
                confidence=confidence,
                avg_r_with=avg_r_with,
                avg_r_without=avg_r_without,
            ))

        scores.sort(key=lambda s: s.lift_pct, reverse=True)
        self.booster_scores[strategy] = scores

        # Compute pairwise combos for top boosters
        self._fit_combos(strategy, trades, scores)

        # Build optimal booster list
        self.optimal_boosters[strategy] = [
            s.booster_name for s in scores if s.lift_pct > 0
        ]

    def _fit_combos(self, strategy: str, trades: list[dict], scores: list[BoosterScore]) -> None:
        """Test pairwise combinations of top boosters for additivity.

        Compares WR(both) vs max(WR(A_only), WR(B_only)) to detect whether
        combining adds value beyond the best single booster.
        """
        top_boosters = [s.booster_name for s in scores[:10] if s.lift_pct > 0]
        if len(top_boosters) < 2:
            self.combo_scores[strategy] = []
            return

        combos: list[ComboScore] = []

        for a, b in combinations(top_boosters, 2):
            both = [
                t for t in trades
                if a in (t.get("confluences") or []) and b in (t.get("confluences") or [])
            ]
            neither = [
                t for t in trades
                if a not in (t.get("confluences") or []) and b not in (t.get("confluences") or [])
            ]
            a_only = [
                t for t in trades
                if a in (t.get("confluences") or []) and b not in (t.get("confluences") or [])
            ]
            b_only = [
                t for t in trades
                if b in (t.get("confluences") or []) and a not in (t.get("confluences") or [])
            ]

            if len(both) < 5 or len(neither) < 5:
                continue

            wr_both = sum(1 for t in both if t.get("is_winner")) / len(both)
            wr_neither = sum(1 for t in neither if t.get("is_winner")) / len(neither)
            combined_lift = (wr_both - wr_neither) * 100.0

            # Compute WR of each alone (without the other)
            wr_a_only = (sum(1 for t in a_only if t.get("is_winner")) / len(a_only)) if a_only else 0
            wr_b_only = (sum(1 for t in b_only if t.get("is_winner")) / len(b_only)) if b_only else 0
            best_single_wr = max(wr_a_only, wr_b_only)

            # Additive: having both gives higher WR than having just the best single
            is_additive = wr_both > best_single_wr * 1.05 and combined_lift > 0
            # Redundant: having both is similar or worse than best single
            is_redundant = wr_both <= best_single_wr * 1.05 and combined_lift > 0

            combos.append(ComboScore(
                booster_a=a,
                booster_b=b,
                strategy_name=strategy,
                combined_lift_pct=combined_lift,
                is_additive=is_additive,
                is_redundant=is_redundant,
                sample_n=len(both),
            ))

        combos.sort(key=lambda c: c.combined_lift_pct, reverse=True)
        self.combo_scores[strategy] = combos

    def select_boosters(
        self,
        strategy: str,
        available_confluences: list[str],
        entry_price: float | None = None,
        confluence_prices: dict[str, float] | None = None,
    ) -> tuple[list[str], float]:
        """Select optimal boosters for a live setup.

        Returns (selected_boosters, confidence_score).

        Logic:
        1. Filter to boosters with positive lift for this strategy
        2. If entry_price and confluence_prices provided, check alignment
        3. Start with the highest-lift booster
        4. Add second booster ONLY if it's additive (not redundant)
        5. Cap at 3 boosters max (diminishing returns beyond that)
        """
        scores = self.booster_scores.get(strategy, [])
        if not scores:
            return available_confluences[:3], 0.0

        score_map = {s.booster_name: s for s in scores}

        # Filter to available boosters with positive lift
        positive = [
            c for c in available_confluences
            if c in score_map and score_map[c].lift_pct > 0
        ]

        if not positive:
            return available_confluences[:3], 0.0

        # Sort by lift
        positive.sort(key=lambda c: score_map[c].lift_pct, reverse=True)

        # Check alignment if prices provided
        if entry_price is not None and confluence_prices:
            aligned, spread = self.check_alignment(entry_price, confluence_prices)
            if not aligned:
                # Still return boosters but with reduced confidence
                selected = positive[:3]
                avg_lift = sum(score_map[c].lift_pct for c in selected) / len(selected)
                return selected, max(0.0, avg_lift * 0.5)

        # Select boosters avoiding redundant pairs
        selected: list[str] = [positive[0]]
        combos = self.combo_scores.get(strategy, [])
        redundant_pairs = {
            (min(c.booster_a, c.booster_b), max(c.booster_a, c.booster_b))
            for c in combos if c.is_redundant
        }

        for candidate in positive[1:]:
            if len(selected) >= 3:
                break
            # Check if redundant with any already-selected
            is_redundant = any(
                (min(candidate, s), max(candidate, s)) in redundant_pairs
                for s in selected
            )
            if not is_redundant:
                selected.append(candidate)

        avg_lift = sum(score_map[c].lift_pct for c in selected) / len(selected)
        return selected, avg_lift

    def check_alignment(
        self,
        entry_price: float,
        confluence_prices: dict[str, float],
        max_spread_pips: float = 8.0,
    ) -> tuple[bool, float]:
        """Check if multiple confluences point at the same price area.

        Returns (is_aligned, spread_pips).
        """
        if not confluence_prices:
            return True, 0.0

        all_prices = list(confluence_prices.values()) + [entry_price]
        spread = (max(all_prices) - min(all_prices)) * 10000  # Convert to pips
        return spread <= max_spread_pips, spread

    def update_from_trade(self, trade: dict) -> None:
        """Online update after a trade completes.

        Incrementally adjusts booster scores using EMA with alpha=0.05.
        """
        alpha = 0.05
        strategy = trade.get("strategy_name") or "unknown"
        confluences = trade.get("confluences") or []
        if isinstance(confluences, str):
            confluences = [c.strip() for c in confluences.split(",")]
        is_winner = trade.get("is_winner", False)
        win_val = 1.0 if is_winner else 0.0

        for booster in confluences:
            key = f"{strategy}:{booster}"
            old_wr = self._ema_wins[strategy].get(booster, 0.5)
            new_wr = old_wr * (1 - alpha) + win_val * alpha
            self._ema_wins[strategy][booster] = new_wr
            self._ema_counts[strategy][booster] = (
                self._ema_counts[strategy].get(booster, 0) + 1
            )

        # Update scores if we have enough data
        if strategy in self.booster_scores:
            for score in self.booster_scores[strategy]:
                if score.booster_name in confluences:
                    ema_wr = self._ema_wins[strategy].get(score.booster_name, 0.5)
                    # Blend: adjust lift slightly toward EMA-observed win rate
                    baseline_wr = 0.5  # Approximate
                    new_lift = (ema_wr - baseline_wr) * 100.0
                    score.lift_pct = score.lift_pct * (1 - alpha) + new_lift * alpha

    def get_report(self) -> dict:
        """Generate a human-readable report of booster rankings."""
        report: dict = {"strategies": {}}

        for strategy, scores in self.booster_scores.items():
            strat_report: dict = {
                "boosters": [],
                "top_combos": [],
                "optimal_menu": self.optimal_boosters.get(strategy, []),
            }

            for s in scores[:15]:
                strat_report["boosters"].append({
                    "name": s.booster_name,
                    "lift_pct": round(s.lift_pct, 2),
                    "confidence": s.confidence,
                    "sample_with": s.sample_with,
                    "avg_r_with": round(s.avg_r_with, 3),
                    "avg_r_without": round(s.avg_r_without, 3),
                })

            combos = self.combo_scores.get(strategy, [])
            for c in combos[:5]:
                strat_report["top_combos"].append({
                    "pair": f"{c.booster_a} + {c.booster_b}",
                    "combined_lift": round(c.combined_lift_pct, 2),
                    "is_additive": c.is_additive,
                    "sample_n": c.sample_n,
                })

            report["strategies"][strategy] = strat_report

        return report

    def save(self, path: str) -> None:
        """Persist optimizer state to JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "booster_scores": {
                strat: [asdict(s) for s in scores]
                for strat, scores in self.booster_scores.items()
            },
            "combo_scores": {
                strat: [asdict(c) for c in combos]
                for strat, combos in self.combo_scores.items()
            },
            "optimal_boosters": self.optimal_boosters,
        }

        p.write_text(json.dumps(data, indent=2))

    def load(self, path: str) -> None:
        """Load optimizer state from JSON."""
        p = Path(path)
        if not p.exists():
            log.warning("Optimizer state not found at %s", path)
            return

        data = json.loads(p.read_text())

        self.booster_scores = {}
        for strat, scores_data in data.get("booster_scores", {}).items():
            self.booster_scores[strat] = [
                BoosterScore(**s) for s in scores_data
            ]

        self.combo_scores = {}
        for strat, combos_data in data.get("combo_scores", {}).items():
            self.combo_scores[strat] = [
                ComboScore(**c) for c in combos_data
            ]

        self.optimal_boosters = data.get("optimal_boosters", {})


def _avg_r(trades: list[dict]) -> float:
    """Average R-multiple across trades."""
    r_values = [t.get("r_multiple", 1.0 if t.get("is_winner") else -1.0) for t in trades]
    return sum(r_values) / len(r_values) if r_values else 0.0
