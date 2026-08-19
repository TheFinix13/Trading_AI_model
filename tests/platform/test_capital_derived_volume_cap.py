"""Gate #6's ceiling is a function of the account, not a constant.

The property under test is an asymmetry: capital sets the ceiling and
config may only tighten it. A guard that `platform.toml` can widen is
not a guard, so the "explicit cannot loosen" case below is the one that
actually carries the safety claim -- the rest is arithmetic around it.
"""
from __future__ import annotations

import pytest

from agent.platform import live_executor as lx


class TestCapitalDerivation:

    def test_five_hundred_reproduces_the_standing_ten_lot_setting(self):
        # Adopting capital-derivation must be a no-op at today's book
        # size, otherwise it is a live behaviour change wearing a
        # refactor's clothes.
        assert lx.capital_derived_max_lots(500.0) == pytest.approx(0.10)

    def test_ceiling_scales_with_the_book(self):
        assert lx.capital_derived_max_lots(1000.0) == pytest.approx(0.20)
        assert lx.capital_derived_max_lots(100.0) == pytest.approx(0.02)

    def test_rate_is_tunable(self):
        assert lx.capital_derived_max_lots(500.0, 0.1) == pytest.approx(0.05)

    @pytest.mark.parametrize("equity", [None, 0.0, -500.0, "lots", float("nan")])
    def test_unusable_capital_yields_no_ceiling_rather_than_a_guess(self, equity):
        # NaN is the subtle one: `not nan > 0` is True, so it lands in
        # the same refusal branch as zero rather than propagating into
        # a comparison that silently succeeds.
        assert lx.capital_derived_max_lots(equity) is None

    @pytest.mark.parametrize("rate", [0.0, -1.0, None, "wide"])
    def test_unusable_rate_yields_no_ceiling(self, rate):
        assert lx.capital_derived_max_lots(500.0, rate) is None


class TestEffectiveCeiling:

    def test_capital_alone_sets_the_ceiling(self):
        assert lx.effective_max_volume_lots(500.0) == pytest.approx(0.10)

    def test_explicit_may_tighten(self):
        assert lx.effective_max_volume_lots(500.0, 0.02) == pytest.approx(0.02)

    def test_explicit_may_not_loosen(self):
        # The claim: no config edit makes a $500 book able to send 5 lots.
        assert lx.effective_max_volume_lots(500.0, 5.0) == pytest.approx(0.10)

    def test_unknown_capital_honours_an_explicit_assertion(self):
        assert lx.effective_max_volume_lots(None, 0.05) == pytest.approx(0.05)

    def test_unknown_capital_and_no_config_falls_back_tiny(self):
        assert lx.effective_max_volume_lots(None) == \
            pytest.approx(lx.DEFAULT_MAX_VOLUME_LOTS)

    def test_fallback_is_small_enough_to_be_obviously_a_floor(self):
        assert lx.DEFAULT_MAX_VOLUME_LOTS <= 0.01


class TestB2Boundary:
    """F025 B2 was 'the executor refuses 100% of squad orders'.

    The squad fills at FIXED_LOT = 0.1 and a $500 book derives a ceiling
    of exactly 0.1, so the gate (`volume > max_volume_lots`) admits it --
    but only because 0.5 * 0.2 happens to be exactly 0.1 in IEEE754. That
    is a knife-edge, and B2 returning silently would refuse every order
    again, so it is locked here rather than left to luck.
    """

    FIXED_LOT = 0.1

    def test_five_hundred_admits_the_squad_fill_size(self):
        ceiling = lx.effective_max_volume_lots(500.0)
        assert not self.FIXED_LOT > ceiling, (
            "gate would refuse every squad-sized order -- F025 B2 is back"
        )

    def test_the_float_identity_this_relies_on(self):
        assert (500.0 / 1000.0) * 0.2 == 0.1

    def test_a_smaller_book_refuses_the_squad_fill_and_that_is_correct(self):
        # $400 derives 0.08, so a raw 0.1 fill refuses. This is the
        # ceiling doing its job, NOT a regression -- it is why
        # risk-derived sizing is mandatory before real money (B3).
        ceiling = lx.effective_max_volume_lots(400.0)
        assert self.FIXED_LOT > ceiling


class TestConfigWiring:

    def _cfg(self, *, equity=None, max_lots=None):
        block = {"enabled": True, "demo_only": True}
        if max_lots is not None:
            block["max_volume_lots"] = max_lots
        cfg = {"live_executor": block}
        if equity is not None:
            cfg["squad_live"] = {"equity": equity}
        return cfg

    def test_loader_derives_from_squad_live_equity(self):
        block = lx.load_executor_config(self._cfg(equity=500.0))
        assert block["max_volume_lots"] == pytest.approx(0.10)

    def test_loader_lets_config_tighten(self):
        block = lx.load_executor_config(self._cfg(equity=500.0, max_lots=0.03))
        assert block["max_volume_lots"] == pytest.approx(0.03)

    def test_loader_refuses_to_let_config_widen(self):
        block = lx.load_executor_config(self._cfg(equity=500.0, max_lots=2.0))
        assert block["max_volume_lots"] == pytest.approx(0.10)

    def test_loader_without_equity_stays_at_the_tiny_default(self):
        block = lx.load_executor_config(self._cfg())
        assert block["max_volume_lots"] == pytest.approx(
            lx.DEFAULT_MAX_VOLUME_LOTS)

    @pytest.mark.parametrize("junk", [0.0, -1.0, "big", None])
    def test_junk_config_reads_as_unset_not_as_zero(self, junk):
        # A zero ceiling would refuse every order and present as a gate
        # bug; a typo must degrade to the capital ceiling instead.
        block = lx.load_executor_config(self._cfg(equity=500.0, max_lots=junk))
        assert block["max_volume_lots"] == pytest.approx(0.10)
