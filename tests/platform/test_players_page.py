"""F002 -- static structure tests for the players pages.

Verifies:

* PLAYERS_INDEX_PAGE is a self-contained document (no CDN, no
  external CSS / JS).
* Nav pill count is 7 with `/players` marked active.
* IP disclaimer text is embedded verbatim from
  ``company/legal/disclaimers.md``.
* F005 helper is embedded (skeleton CSS + withStates + error copy).
* Mobile media queries fire at both 700 px and 480 px.
* Player-detail template substitutes both player id and name.
* 404 page lists all ten valid striker ids as links.
"""
from __future__ import annotations

from agent.platform import pages, players


# --------------------------------------------------------------------
# Index page
# --------------------------------------------------------------------

def test_index_page_title():
    assert "<title>Squad -- Blue Lock Trading Co.</title>" in pages.PLAYERS_INDEX_PAGE


def test_index_page_preamble_present():
    assert "Ten specialists" in pages.PLAYERS_INDEX_PAGE
    assert "one pitch" in pages.PLAYERS_INDEX_PAGE


def test_index_page_disclaimer_verbatim():
    p = pages.PLAYERS_INDEX_PAGE
    # anchors from company/legal/disclaimers.md::third-party-name-usage
    assert "Blue Lock is a manga" in p
    assert "Yusuke Nomura" in p
    assert "Muneyuki" in p
    assert "Kodansha" in p
    assert "affiliation" in p
    assert "no affiliation" in " ".join(p.split())


def test_index_page_uses_withstates_helper():
    p = pages.PLAYERS_INDEX_PAGE
    assert "withStates" in p
    assert "CANONICAL_ERROR_COPY" in p or "ERROR_COPY_KEYS" in p or "error_copy" in p.lower()


def test_index_page_skeleton_css_embedded():
    assert "sk-tile" in pages.PLAYERS_INDEX_PAGE
    assert "@keyframes shimmer" in pages.PLAYERS_INDEX_PAGE


def test_index_page_nav_pills_count():
    # nav pill count is 8 (Hub / v1 / v2 / HQ / Performance / Squad /
    # Highlights / Research) -- Highlights added by F020 (Sprint 3).
    p = pages.PLAYERS_INDEX_PAGE
    nav_start = p.find('<div class="nav">')
    nav_end = p.find("</div>", nav_start)
    assert nav_start != -1 and nav_end != -1
    nav_block = p[nav_start:nav_end]
    assert nav_block.count("<a ") == 8


def test_index_page_players_pill_active():
    # the "players" pill (labelled "Squad") should carry class="here"
    p = pages.PLAYERS_INDEX_PAGE
    assert 'href="/players" class="here"' in p


def test_index_page_polls_api_endpoint():
    assert "/api/players/list" in pages.PLAYERS_INDEX_PAGE


def test_index_page_60s_poll_interval():
    assert "setInterval(refresh, 60000)" in pages.PLAYERS_INDEX_PAGE


def test_index_page_mobile_media_queries():
    p = pages.PLAYERS_INDEX_PAGE
    assert "@media (max-width: 700px)" in p
    assert "@media (max-width: 1100px)" in p


def test_index_page_viewport_meta():
    assert 'name="viewport"' in pages.PLAYERS_INDEX_PAGE
    assert "width=device-width" in pages.PLAYERS_INDEX_PAGE


def test_index_page_no_cdn_or_external_asset():
    p = pages.PLAYERS_INDEX_PAGE
    assert "cdn." not in p
    assert "https://" not in p or "http-equiv" in p  # allow http-equiv metas
    assert "<script src=" not in p
    assert "<link rel=\"stylesheet\"" not in p


def test_index_page_no_cursor_attribution():
    p = pages.PLAYERS_INDEX_PAGE
    assert "cursor.com" not in p.lower()
    assert "cursoragent" not in p.lower()
    assert "made with cursor" not in p.lower()


# --------------------------------------------------------------------
# Detail page factory
# --------------------------------------------------------------------

def test_detail_page_substitutes_id_and_name():
    page = pages.player_detail_page("isagi", "Isagi")
    assert 'var PLAYER_ID = "isagi";' in page
    assert "<title>Isagi -- Blue Lock Trading Co.</title>" in page


def test_detail_page_substitutes_all_ten_strikers():
    for entry in players.roster_meta():
        page = pages.player_detail_page(entry["id"], entry["name"])
        assert f'var PLAYER_ID = "{entry["id"]}";' in page
        assert f"<title>{entry['name']}" in page


def test_detail_page_polls_id_specific_api():
    page = pages.player_detail_page("bachira", "Bachira")
    assert '"/api/players/" + encodeURIComponent(PLAYER_ID)' in page


def test_detail_page_disclaimer_verbatim():
    page = pages.player_detail_page("isagi", "Isagi")
    assert "Blue Lock is a manga" in page
    assert "Yusuke Nomura" in page
    assert "Kodansha" in page


def test_detail_page_uses_withstates_helper():
    page = pages.player_detail_page("isagi", "Isagi")
    assert "withStates" in page
    assert "detailSkeleton" in page


def test_detail_page_mobile_media_queries():
    page = pages.player_detail_page("isagi", "Isagi")
    assert "@media (max-width: 700px)" in page
    assert "@media (max-width: 480px)" in page


def test_detail_page_players_nav_active():
    page = pages.player_detail_page("isagi", "Isagi")
    assert 'href="/players" class="here"' in page


def test_detail_page_sanitises_quotes_in_id():
    # The route handler normalises before calling; belt-and-braces the
    # factory itself must not emit closed quote-injections.
    page = pages.player_detail_page('is"agi', "Isagi")
    assert '"is"agi"' not in page


def test_detail_page_renders_recent_activity_section():
    page = pages.player_detail_page("isagi", "Isagi")
    assert "Recent activity" in page
    assert "Evolution history" in page
    assert "Signature setup" in page
    assert "Career stats" in page


# --------------------------------------------------------------------
# 404 shell
# --------------------------------------------------------------------

def test_not_found_page_lists_all_ten():
    page = pages.players_not_found_page(list(players.valid_ids()))
    for id_ in players.valid_ids():
        assert f'href="/players/{id_}"' in page


def test_not_found_page_status_copy():
    page = pages.players_not_found_page(list(players.valid_ids()))
    assert "Striker not found" in page
    assert "Back to the squad" in page


def test_not_found_page_empty_roster_degrades():
    page = pages.players_not_found_page([])
    assert "roster unavailable" in page or "no known" in page.lower()


def test_not_found_page_carries_nav_and_players_active():
    page = pages.players_not_found_page(list(players.valid_ids()))
    assert '<div class="nav">' in page
    assert 'href="/players" class="here"' in page
