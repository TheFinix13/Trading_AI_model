"""Static structure tests for `PERFORMANCE_PAGE` (F001).

The static string is a stable, framework-free HTML page. A rename of
any structural marker (KPI grid id, equity SVG viewport, disclaimer
text) breaks the UI silently, so we pin them here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import PERFORMANCE_PAGE  # noqa: E402


class TestPerformancePageStructure:

    def test_title_and_heading(self):
        assert "<title>Performance -- Blue Lock Trading Co.</title>" \
            in PERFORMANCE_PAGE
        assert "How we&#39;re doing" in PERFORMANCE_PAGE or \
               "How we're doing" in PERFORMANCE_PAGE

    def test_preamble_brand_copy(self):
        # Brand copy library authors the preamble; regression-lock the
        # exact phrasing.
        assert ("demo-account P&amp;L for our live" in PERFORMANCE_PAGE
                or "demo-account P&L for our live" in PERFORMANCE_PAGE)

    def test_kpi_tile_labels_present(self):
        for label in ("Days live", "Net pips", "Worst drawdown",
                      "Win rate", "Sharpe"):
            assert label in PERFORMANCE_PAGE, (
                f"missing KPI label: {label!r}")

    def test_source_hint_container(self):
        assert 'id="source-hint-text"' in PERFORMANCE_PAGE
        assert 'id="source-hint"' in PERFORMANCE_PAGE

    def test_equity_svg_container(self):
        # The renderEquityCurve function writes an inline SVG; the
        # container wrapper carries the ARIA label.
        assert "Equity curve" in PERFORMANCE_PAGE
        assert "renderEquityCurve" in PERFORMANCE_PAGE

    def test_per_pair_table_headers(self):
        for header in ("Pair", "Trades", "Wins", "Net pips",
                       "Avg pips", "Best trade", "Worst trade"):
            assert header in PERFORMANCE_PAGE, (
                f"missing table header: {header!r}")

    def test_disclaimer_footer_present(self):
        # Page renders the disclaimer wrapped across lines; assert its
        # anchor phrases rather than a joined string. This is the
        # Legal-authored `performance` disclaimer library entry.
        assert "Past performance is not indicative" in PERFORMANCE_PAGE
        assert "demo (paper-money)" in PERFORMANCE_PAGE
        assert "No real capital is at risk." in PERFORMANCE_PAGE
        assert "investment advice" in PERFORMANCE_PAGE
        assert "solicitation" in PERFORMANCE_PAGE

    def test_no_ensemble_or_aggregator_leak(self):
        # Charter's banned words in user-visible copy. Regression-lock.
        assert "ensemble" not in PERFORMANCE_PAGE.lower()
        assert "aggregator" not in PERFORMANCE_PAGE.lower()

    def test_no_cursor_attribution_leak(self):
        for banned in ("Made-with: Cursor", "Made with Cursor",
                       "cursor.com", "cursoragent"):
            assert banned.lower() not in PERFORMANCE_PAGE.lower(), (
                f"attribution leak: {banned!r}")

    def test_fetches_api_state_endpoint(self):
        assert "/api/performance/state" in PERFORMANCE_PAGE

    def test_polls_every_60s(self):
        assert "setInterval(refresh, 60000)" in PERFORMANCE_PAGE

    def test_nav_active_class(self):
        assert 'href="/performance" class="here"' in PERFORMANCE_PAGE

    def test_mobile_media_queries_present(self):
        # F004 baked in: the KPI grid collapses at 700 px.
        assert "@media (max-width: 700px)" in PERFORMANCE_PAGE

    def test_dark_theme_tokens_referenced(self):
        for tok in ("var(--bg)", "var(--panel)", "var(--fg)",
                    "var(--dim)"):
            assert tok in PERFORMANCE_PAGE, f"missing token: {tok!r}"

    def test_withstates_helper_present(self):
        # F005 consumer: the shared helper is embedded in the page's
        # <script> block.
        assert "withStates" in PERFORMANCE_PAGE
        assert "CANONICAL_ERROR_COPY" in PERFORMANCE_PAGE

    def test_retry_label_is_try_again(self):
        assert '"Try again"' in PERFORMANCE_PAGE

    def test_sharpe_days_needed_treated_as_dynamic(self):
        # Below the 30-day floor the tile shows "n/a -- need N more days"
        # -- the JS reads sharpe_days_needed at render time.
        assert "sharpe_days_needed" in PERFORMANCE_PAGE

    def test_nav_present_with_other_tabs(self):
        for href in ('href="/"', 'href="/v1"', 'href="/v2"',
                     'href="/hq"', 'href="/performance"',
                     'href="/players"', 'href="/research"'):
            assert href in PERFORMANCE_PAGE, (
                f"missing nav link: {href!r}")
