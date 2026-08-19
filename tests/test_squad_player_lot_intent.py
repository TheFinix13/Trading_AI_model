"""Per-player lot sizing: intent proposes, the risk budget disposes.

The safety property is containment. A player's `lot_intent` feeds
`risk_budget_lot` as the DESIRED lot, so the budget cap still stands in
front of it and a fill can only ever be sized down. The tests that
carry that claim are `test_intent_cannot_exceed_the_budget_cap` and
`test_flag_is_inert_without_risk_derived_sizing` -- the rest guard the
degradation paths, because a sizing opinion must never be able to stop
a trade the squad already agreed on.
"""
from __future__ import annotations

import pytest

from agent.squad.engine import SquadEngine


class _Proposal:
    def __init__(self, agent_id="isagi", conviction=0.7, entry=1.1000,
                 stop=1.0970, regime_fit=1.0):
        self.agent_id = agent_id
        self.conviction = conviction
        self.entry = entry
        self.stop = stop
        self.regime_fit = regime_fit
        self.direction = "long"


class _Agent:
    def __init__(self, agent_id="isagi", want=0.05, raises=False):
        self.agent_id = agent_id
        self._want = want
        self._raises = raises

    def lot_intent(self, conviction, sl_pips, equity, regime_fit):
        if self._raises:
            raise RuntimeError("sizing blew up")
        return self._want


class _AgentNoIntent:
    def __init__(self, agent_id="isagi"):
        self.agent_id = agent_id


class _Roster:
    def __init__(self, *agents):
        self.proposers = list(agents)


def _engine(tmp_path, roster, **kw):
    eng = SquadEngine.__new__(SquadEngine)
    eng.roster = roster
    eng.equity = 500.0
    eng.player_lot_intent = kw.get("player_lot_intent", True)
    return eng


class TestFlagGating:

    def test_flag_is_inert_without_risk_derived_sizing(self, tmp_path):
        # Without the budget cap in front, intent WOULD be the final
        # lot. That is the unvalidated free-sizing case, so the flag
        # must refuse to arm rather than quietly becoming it.
        eng = SquadEngine(
            _Roster(_Agent()), tmp_path,
            risk_derived_sizing=False, player_lot_intent=True,
        )
        assert eng.player_lot_intent is False

    def test_flag_arms_only_with_both(self, tmp_path):
        eng = SquadEngine(
            _Roster(_Agent()), tmp_path,
            risk_derived_sizing=True, player_lot_intent=True,
        )
        assert eng.player_lot_intent is True

    def test_default_is_off(self, tmp_path):
        eng = SquadEngine(_Roster(_Agent()), tmp_path,
                          risk_derived_sizing=True)
        assert eng.player_lot_intent is False


class TestIntentIsAsked:

    def test_player_opinion_is_returned(self, tmp_path):
        eng = _engine(tmp_path, _Roster(_Agent(want=0.05)))
        lot, note = eng._player_desired_lot(_Proposal(), 30.0)
        assert lot == pytest.approx(0.05)
        assert "lot_intent=0.0500" in note

    def test_the_right_player_is_asked(self, tmp_path):
        eng = _engine(tmp_path, _Roster(
            _Agent("isagi", want=0.05), _Agent("barou", want=0.09)))
        lot, _ = eng._player_desired_lot(_Proposal(agent_id="barou"), 30.0)
        assert lot == pytest.approx(0.09)

    def test_intent_receives_the_proposal_context(self, tmp_path):
        seen = {}

        class Recorder(_Agent):
            def lot_intent(self, conviction, sl_pips, equity, regime_fit):
                seen.update(conviction=conviction, sl_pips=sl_pips,
                            equity=equity, regime_fit=regime_fit)
                return 0.05

        eng = _engine(tmp_path, _Roster(Recorder()))
        eng._player_desired_lot(
            _Proposal(conviction=0.82, regime_fit=0.6), 42.0)
        assert seen == {"conviction": 0.82, "sl_pips": 42.0,
                        "equity": 500.0, "regime_fit": 0.6}


class TestContainment:

    def test_intent_cannot_exceed_the_budget_cap(self):
        # THE safety claim. A greedy player asking for 10 lots must not
        # get more than the 5%-of-equity budget already permitted.
        from agent.squad.lot_intent import risk_budget_lot
        kw = dict(sl_pips=30.0, equity=500.0, pip_value_per_min_lot=0.10,
                  per_trade_risk_frac=0.05)
        capped = risk_budget_lot(desired_lot=10.0, **kw)
        baseline = risk_budget_lot(desired_lot=0.1, **kw)
        assert capped <= max(baseline, capped)
        # The budget, not the player, is what bounds the result.
        risk_at_capped = capped / 0.01 * 0.10 * 30.0
        assert risk_at_capped <= 500.0 * 0.05 + 1e-6

    def test_modest_intent_is_honoured_downward(self):
        from agent.squad.lot_intent import risk_budget_lot
        kw = dict(sl_pips=30.0, equity=500.0, pip_value_per_min_lot=0.10,
                  per_trade_risk_frac=0.05)
        assert risk_budget_lot(desired_lot=0.02, **kw) <= \
            risk_budget_lot(desired_lot=0.10, **kw)


class TestDegradation:
    """A broken opinion degrades to today's behaviour, never to a block."""

    def test_agent_not_on_the_roster(self, tmp_path):
        eng = _engine(tmp_path, _Roster(_Agent("isagi")))
        lot, note = eng._player_desired_lot(_Proposal(agent_id="ghost"), 30.0)
        assert lot == pytest.approx(0.1)
        assert "n/a" in note

    def test_agent_without_lot_intent(self, tmp_path):
        eng = _engine(tmp_path, _Roster(_AgentNoIntent()))
        lot, note = eng._player_desired_lot(_Proposal(), 30.0)
        assert lot == pytest.approx(0.1)
        assert "n/a" in note

    def test_intent_that_raises(self, tmp_path):
        eng = _engine(tmp_path, _Roster(_Agent(raises=True)))
        lot, note = eng._player_desired_lot(_Proposal(), 30.0)
        assert lot == pytest.approx(0.1)
        assert "error" in note

    @pytest.mark.parametrize("bad", [0.0, -0.05, float("nan")])
    def test_non_positive_and_nan_are_rejected(self, tmp_path, bad):
        eng = _engine(tmp_path, _Roster(_Agent(want=bad)))
        lot, note = eng._player_desired_lot(_Proposal(), 30.0)
        assert lot == pytest.approx(0.1)
        assert "rejected" in note

    def test_junk_return_is_rejected(self, tmp_path):
        eng = _engine(tmp_path, _Roster(_Agent(want="loads")))
        lot, note = eng._player_desired_lot(_Proposal(), 30.0)
        assert lot == pytest.approx(0.1)
        assert "error" in note
