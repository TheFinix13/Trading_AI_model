"""F020 -- /highlights page markup pins + the /v2 teaser card.

- F005 conventions: withStates() + skeleton CSS + canonical error copy.
- Provenance banner present with the NOT-profit-performance wording.
- Brand banned words absent from the whole rendered page.
- Mobile: viewport meta + 700px media query (375px devices covered).
- Nav: Highlights pill exists and is active on its own page.
- /v2 carries the latest-match-report teaser linking /highlights.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import (  # noqa: E402
    HIGHLIGHTS_PAGE, HUB_PAGE, V2_PAGE, nav,
)


class TestHighlightsPage:
    def test_uses_with_states_helper(self):
        assert "async function withStates(" in HIGHLIGHTS_PAGE
        assert "CANONICAL_ERROR_COPY" in HIGHLIGHTS_PAGE
        assert ".sk-error" in HIGHLIGHTS_PAGE  # skeleton CSS shipped

    def test_provenance_banner(self):
        assert "hl-provenance" in HIGHLIGHTS_PAGE
        assert "NOT profit performance" in HIGHLIGHTS_PAGE
        assert "no orders sent to any broker" in HIGHLIGHTS_PAGE

    def test_banned_words_absent(self):
        lowered = HIGHLIGHTS_PAGE.lower()
        assert "ensemble" not in lowered
        assert "aggregator" not in lowered

    def test_api_endpoints_referenced(self):
        assert "/api/highlights/reports?n=14" in HIGHLIGHTS_PAGE
        assert "/api/highlights/report/" in HIGHLIGHTS_PAGE

    def test_mobile_responsive(self):
        assert 'name="viewport"' in HIGHLIGHTS_PAGE
        assert "@media (max-width: 700px)" in HIGHLIGHTS_PAGE

    def test_nav_pill_active_here(self):
        assert 'href="/highlights"' in HIGHLIGHTS_PAGE
        rendered = nav("highlights")
        assert '<a href="/highlights" class="here">' in rendered

    def test_escapes_via_helper(self):
        # All dynamic strings go through hesc() before innerHTML.
        assert "function hesc(" in HIGHLIGHTS_PAGE


class TestNavEverywhere:
    def test_hub_nav_carries_highlights_pill(self):
        assert 'href="/highlights"' in HUB_PAGE

    def test_unknown_active_never_marks_highlights(self):
        rendered = nav("hub")
        assert '<a href="/highlights" class="">' in rendered


class TestV2Teaser:
    def test_teaser_card_present(self):
        assert 'id="highlights-teaser"' in V2_PAGE
        assert 'href="/highlights"' in V2_PAGE

    def test_teaser_fill_is_fail_quiet(self):
        assert "/api/highlights/reports?n=1" in V2_PAGE
        assert "teaser stays static" in V2_PAGE
