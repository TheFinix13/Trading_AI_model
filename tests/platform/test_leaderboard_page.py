"""F022 -- LEADERBOARD_PAGE rendering pins (page-local, no server)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import LEADERBOARD_PAGE, nav  # noqa: E402


class TestStructure:
    def test_provenance_banner_present(self):
        assert 'class="lb-provenance"' in LEADERBOARD_PAGE
        assert "NOT investment performance" in LEADERBOARD_PAGE
        assert "shadow-paper" in LEADERBOARD_PAGE

    def test_grouping_and_window_toggles_present(self):
        for marker in ('data-by="agent"', 'data-by="pair"',
                       'data-window="all"', 'data-window="30"',
                       'data-window="7"'):
            assert marker in LEADERBOARD_PAGE

    def test_fetches_leaderboard_api(self):
        assert "/api/leaderboard" in LEADERBOARD_PAGE

    def test_nrule_cell_rendering_wired(self):
        # Insufficient-sample rows render the note, never a percentage.
        assert "insufficient_sample" in LEADERBOARD_PAGE
        assert '"nrule"' in LEADERBOARD_PAGE


class TestSharedPrimitives:
    def test_uses_withstates(self):
        assert "withStates(" in LEADERBOARD_PAGE

    def test_nav_marks_leaderboard_active(self):
        assert nav("leaderboard").count('class="here"') == 1
        assert '<a href="/leaderboard" class="here">' in LEADERBOARD_PAGE


class TestMobile:
    def test_viewport_and_media_query(self):
        assert 'name="viewport"' in LEADERBOARD_PAGE
        assert "@media (max-width: 700px)" in LEADERBOARD_PAGE

    def test_table_scrolls_on_mobile(self):
        idx = LEADERBOARD_PAGE.rfind("@media (max-width: 700px)")
        assert "overflow-x:auto" in LEADERBOARD_PAGE[idx:idx + 400]


class TestBrand:
    def test_banned_words_absent(self):
        lowered = LEADERBOARD_PAGE.lower()
        for banned in ("ensemble", "aggregator"):
            assert banned not in lowered

    def test_no_external_comparison_language(self):
        # "internal squad standings" framing is load-bearing (Legal).
        assert "Internal squad standings" in LEADERBOARD_PAGE
