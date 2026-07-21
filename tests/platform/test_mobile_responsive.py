"""F004 -- mobile-responsive smoke test.

Static structural coverage across every user-visible page constant
plus the two dynamic detail-page factories. Verifies:

* Every page ships the viewport meta tag (required for browsers to
  respect our media queries at 375 px).
* Every page contains at least one ``@media (max-width: ...)``
  block. The canonical Sprint 0 breakpoint is 700 px; a couple of
  pre-existing surfaces (HQ_PAGE, V1_PAGE) also carry finer
  480 / 600 breakpoints -- those are still valid mobile
  breakpoints per the F004 spec.
* No page shows a horizontal-scroll-forcing pattern
  (``overflow-x: scroll`` outside of an explicitly scrollable
  primitive).
* The nav row (`_NAV`) is wrap-friendly (flex-wrap).

This test is a smoke check -- it cannot substitute for the manual
375 px pass captured in ``company/qa/F004-verdict.md``, but it
prevents a regression that would silently drop mobile styling from
a page.
"""
from __future__ import annotations

import re

import pytest

from agent.platform import pages


def _static_pages() -> dict[str, str]:
    """Every static user-visible page constant on the platform."""
    return {
        "HUB_PAGE": pages.HUB_PAGE,
        "V1_PAGE": pages.V1_PAGE,
        "V2_PAGE": pages.V2_PAGE,
        "HQ_PAGE": pages.HQ_PAGE,
        "PERFORMANCE_PAGE": pages.PERFORMANCE_PAGE,
        "PLAYERS_INDEX_PAGE": pages.PLAYERS_INDEX_PAGE,
        "RESEARCH_PAGE": pages.RESEARCH_PAGE,
    }


def _dynamic_pages() -> dict[str, str]:
    """Sampled detail-page factory outputs (F002)."""
    return {
        "player_detail_page(isagi_yoichi)":
            pages.player_detail_page("isagi_yoichi", "Yoichi Isagi"),
        "players_not_found_page":
            pages.players_not_found_page(["isagi_yoichi", "bachira_meguru"]),
    }


ALL_PAGES: dict[str, str] = {**_static_pages(), **_dynamic_pages()}


# ---------------------------------------------------------------------------
# Every page carries the viewport meta tag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,html", list(ALL_PAGES.items()))
def test_viewport_meta_present(name: str, html: str):
    assert 'name="viewport"' in html, name
    assert "width=device-width" in html, name
    assert "initial-scale=1" in html, name


# ---------------------------------------------------------------------------
# Every page carries at least one mobile media query
# ---------------------------------------------------------------------------

MEDIA_QUERY_RE = re.compile(r"@media\s*\(\s*max-width:\s*(\d+)\s*px\s*\)")


@pytest.mark.parametrize("name,html", list(ALL_PAGES.items()))
def test_page_has_mobile_media_query(name: str, html: str):
    matches = MEDIA_QUERY_RE.findall(html)
    assert matches, f"{name} has no @media (max-width: Npx) block"


@pytest.mark.parametrize("name,html", list(ALL_PAGES.items()))
def test_media_query_breakpoint_within_range(name: str, html: str):
    """Breakpoint must be between 400 and 900 px to cover phones + small
    tablets. Sprint 0 canon is 700 px; existing pages ship 480 / 600."""
    matches = [int(m) for m in MEDIA_QUERY_RE.findall(html)]
    assert any(400 <= bp <= 900 for bp in matches), \
        f"{name} media queries out of mobile range: {matches}"


# ---------------------------------------------------------------------------
# Sprint 0 F001/F002/F003 pages use the canonical 700 px breakpoint
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page_const", [
    pages.PERFORMANCE_PAGE,
    pages.PLAYERS_INDEX_PAGE,
    pages.RESEARCH_PAGE,
    pages.HQ_PAGE,
])
def test_sprint_0_pages_use_canonical_breakpoint(page_const: str):
    matches = [int(m) for m in MEDIA_QUERY_RE.findall(page_const)]
    assert 700 in matches or 720 in matches, \
        f"page missing canonical 700 px breakpoint (found {matches})"


# ---------------------------------------------------------------------------
# Nav row wrap-friendliness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,html", list(ALL_PAGES.items()))
def test_nav_row_present(name: str, html: str):
    assert '<div class="nav">' in html, name


def test_base_css_nav_is_flex_wrap():
    """_BASE_CSS defines the .nav class; it must be flex-wrap so pills
    reflow instead of forcing horizontal scroll at 375 px."""
    css = pages._BASE_CSS
    assert ".nav{" in css
    assert "flex-wrap:wrap" in css.replace(" ", "")


# ---------------------------------------------------------------------------
# No page forces horizontal scroll on the body
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,html", list(ALL_PAGES.items()))
def test_no_body_level_horizontal_scroll(name: str, html: str):
    """We do allow overflow-x on named containers (tables, setup
    diagrams). We ban it on `body`, `html`, or the top-level .wrap."""
    banned = re.compile(
        r"(?:body|html|\.wrap)\s*\{[^}]*overflow-x\s*:\s*(?:scroll|visible)")
    assert not banned.search(html), \
        f"{name} forces horizontal scroll at the body level"


# ---------------------------------------------------------------------------
# Sprint 0 pages ship with the F005 skeleton CSS included
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page_const", [
    pages.PERFORMANCE_PAGE,
    pages.PLAYERS_INDEX_PAGE,
    pages.RESEARCH_PAGE,
])
def test_sprint_0_pages_include_skeleton_css(page_const: str):
    assert ".sk{" in page_const or ".sk-line" in page_const, \
        "F005 skeleton CSS missing"


# ---------------------------------------------------------------------------
# Legibility floor: no font-size <= 10 px in a rule that isn't for a pill
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,html", list(ALL_PAGES.items()))
def test_no_illegible_font_size(name: str, html: str):
    matches = re.findall(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", html)
    for size in matches:
        assert float(size) >= 10.0, \
            f"{name} has an illegibly small font-size: {size}px"
