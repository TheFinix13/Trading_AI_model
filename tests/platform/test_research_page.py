"""F003 -- static structure tests for the /research page.

Verifies:

* RESEARCH_PAGE is a self-contained document (no CDN, no external
  CSS / JS).
* Nav pill count is 7 with `/research` marked active.
* Legal disclaimer text is embedded verbatim from
  ``company/legal/disclaimers.md``'s `research-verdict` key.
* F005 helper is embedded (skeleton CSS + withStates + error copy).
* Mobile media query at 700 px is present.
* FDR explainer is a `<details>` block (native HTML,
  keyboard-toggleable) and mentions BH-FDR.
* Preamble carries the anti-marketing marketing framing.
"""
from __future__ import annotations

from agent.platform import pages


def test_page_title():
    assert "<title>Research verdicts -- Blue Lock Trading Co.</title>" in pages.RESEARCH_PAGE


def test_page_preamble_present():
    p = pages.RESEARCH_PAGE
    assert "We publish the experiments that failed" in p
    assert "pre-registered" in p
    assert "cherry-picks" in p


def test_page_disclaimer_verbatim():
    p = pages.RESEARCH_PAGE
    # anchors from company/legal/disclaimers.md::research-verdict
    assert "Every verdict below" in p
    assert "pre-registered" in p
    assert "False-discovery-rate" in p or "false-discovery-rate" in p
    assert "portfolio-level claim" in p


def test_page_uses_withstates_helper():
    p = pages.RESEARCH_PAGE
    assert "withStates" in p
    assert "researchSkeleton" in p


def test_page_polls_verdicts_endpoint():
    assert "/api/research/verdicts" in pages.RESEARCH_PAGE


def test_page_60s_poll_interval():
    assert "setInterval(refresh, 60000)" in pages.RESEARCH_PAGE


def test_page_fdr_explainer_is_native_details():
    p = pages.RESEARCH_PAGE
    assert "<details" in p
    assert "BH-FDR" in p
    assert "How pre-registration and BH-FDR keep us honest" in p
    assert "Benjamini-Hochberg" in p or "false-discovery-rate" in p


def test_page_verdict_pills_span_five_state_families():
    p = pages.RESEARCH_PAGE
    assert ".verdict-pill.alive_survivor" in p
    assert ".verdict-pill.dead" in p
    assert ".verdict-pill.fail" in p
    assert ".verdict-pill.stopped" in p
    assert ".verdict-pill.complete" in p


def test_page_nav_pills_count():
    # 8 pills since F020 added Highlights (Sprint 3).
    p = pages.RESEARCH_PAGE
    nav_start = p.find('<div class="nav">')
    nav_end = p.find("</div>", nav_start)
    nav_block = p[nav_start:nav_end]
    assert nav_block.count("<a ") == 8


def test_page_research_pill_active():
    assert 'href="/research" class="here"' in pages.RESEARCH_PAGE


def test_page_mobile_media_query():
    assert "@media (max-width: 700px)" in pages.RESEARCH_PAGE


def test_page_viewport_meta():
    assert 'name="viewport"' in pages.RESEARCH_PAGE
    assert "width=device-width" in pages.RESEARCH_PAGE


def test_page_no_cdn_or_external_asset():
    p = pages.RESEARCH_PAGE
    assert "cdn." not in p
    assert "<script src=" not in p
    assert "<link rel=\"stylesheet\"" not in p


def test_page_no_cursor_attribution():
    p = pages.RESEARCH_PAGE
    assert "cursor.com" not in p.lower()
    assert "cursoragent" not in p.lower()
    assert "made with cursor" not in p.lower()


def test_page_date_header_sticky():
    p = pages.RESEARCH_PAGE
    assert ".date-header" in p
    assert "position:sticky" in p


def test_page_no_ensemble_or_aggregator_jargon_in_visible_copy():
    """The user-visible preamble + disclaimer + FDR block should be
    stranger-friendly. Grep the top-of-body copy for the two banned
    tokens. (Backend field names / manifest keys still use them; the
    ban is only on user-visible copy.)"""
    p = pages.RESEARCH_PAGE
    visible_start = p.find('<div class="research-header">')
    visible_end = p.find("</details>")
    assert visible_start != -1 and visible_end != -1
    body = p[visible_start:visible_end].lower()
    assert "ensemble" not in body
    assert "aggregator" not in body
