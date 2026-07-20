"""Structure + HTTP tests for the /v2 UX pass on ``V2_PAGE``.

Covers the 2026-07-20 UX pass:

1. **Mode picker copy** — the dropdown now uses plain-English labels
   (``Historical replay · Single-shot rule`` etc.) instead of the raw
   internal ids ``g7retry1-phi41`` / ``g7retry1-arm4``. The internal
   ids MUST still appear as ``value=`` attributes on the client side
   (JS looks them up in ``MODE_LABELS``), but they must NOT appear as
   user-visible dropdown TEXT.
2. **Speed picker copy** — labels are ``Slow / Medium / Fast / Turbo``
   with speed-tier subtitles; the raw ``ev/s`` unit is no longer in
   the dropdown text.
3. **New UI plumbing** — info popover, waiting-panel, player tooltip,
   first-visit ribbon, guided tour overlay all present with the
   expected ids and localStorage keys.
4. **HUB glossary anchor** — the hub's ``<details class="glossary">``
   carries ``id="glossary"`` so the v2 info popover can deep-link to
   ``/#glossary``.
5. **HTTP smoke** — ``GET /v2`` still serves 200 text/html and
   contains the new mode labels in the response body.
"""
from __future__ import annotations

import re
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform.pages import HUB_PAGE, V2_PAGE  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


# ---------------------------------------------------------------------------
# 1) Static-string structure tests on V2_PAGE
# ---------------------------------------------------------------------------

class TestV2ModePickerCopy:
    """The mode dropdown speaks plain English; the raw aggregator ids
    only survive as option values, never as user-visible text."""

    def test_new_mode_labels_present(self):
        for marker in (
            "Historical replay",
            "Single-shot rule",
            "Twin-strike rule",
            "LIVE — Today's market",
        ):
            assert marker in V2_PAGE, f"missing mode label: {marker!r}"

    def test_mode_subtitles_present(self):
        # From MODE_LABELS in the JS block — surfaced as option title=
        # attributes and inside the info popover copy.
        for marker in (
            "Real MT5 bars, no orders sent",
            "one shot per pair per bar",
            "up to two shots per pair per bar",
            "G7-verdict",
        ):
            assert marker in V2_PAGE, f"missing subtitle fragment: {marker!r}"

    def test_internal_ids_still_available_as_wire_values(self):
        # These are directory names in the research repo replay cache;
        # they must survive as JS map keys so downstream logic (subtitle,
        # info popover, mode-kind branching) can key off the mode.
        for wire_id in ("g7retry1-phi41", "g7retry1-arm4", "__live__"):
            assert wire_id in V2_PAGE, f"missing wire id: {wire_id!r}"

    def test_no_raw_ids_in_dropdown_option_text(self):
        # Scan every <option ...>...</option> inside a <select id="match">
        # or <select id="speed"> and confirm the visible text carries
        # the plain-English labels, not the raw ids. Any `value=` is
        # fine — that's how the JS wires the pick to the API.
        select_re = re.compile(
            r'<select[^>]*id="(match|speed)"[^>]*>.*?</select>',
            re.DOTALL)
        option_re = re.compile(r"<option[^>]*>([^<]*)</option>")
        selects = select_re.findall(V2_PAGE)
        # We can't grep-count on findall of the pattern; use finditer.
        raw_visible: list[tuple[str, str]] = []
        for m in select_re.finditer(V2_PAGE):
            block = m.group(0)
            which = m.group(1)
            for opt in option_re.finditer(block):
                text = opt.group(1)
                # NB: the mode picker is populated by JS on load, so
                # the static template shipping empty <select id="match">
                # is expected — the test still guards the speed picker
                # explicitly for raw units, and any future statically-
                # baked <option> in either select.
                raw_visible.append((which, text))
        for which, text in raw_visible:
            for bad in ("phi41", "arm4"):
                assert bad not in text.lower(), (
                    f"raw id {bad!r} leaked into {which} <option> text: "
                    f"{text!r}")

    def test_speed_labels_use_tier_names(self):
        for marker in ("🐢 Slow", "⏩ Medium", "🚀 Fast", "⚡ Turbo"):
            assert marker in V2_PAGE, f"missing speed tier: {marker!r}"

    def test_speed_dropdown_has_no_raw_ev_s_text(self):
        # The speed dropdown option text still mentions "events/s" as
        # the subtitle unit, but not the terse "ev/s" jargon from the
        # old dropdown. Assert we did the copy swap.
        speed_re = re.compile(
            r'<select[^>]*id="speed"[^>]*>(.*?)</select>', re.DOTALL)
        m = speed_re.search(V2_PAGE)
        assert m is not None, "speed <select> block not found"
        speed_block = m.group(1)
        assert "ev/s" not in speed_block, (
            "old 'ev/s' unit still in the speed dropdown text: "
            f"{speed_block!r}")


class TestV2NewSurfaces:
    """The UX pass adds five new UI surfaces; each must be in the DOM
    or the JS wire-up will silently no-op."""

    def test_info_popover_present(self):
        assert 'id="info-popover"' in V2_PAGE
        assert 'id="mode-info-btn"' in V2_PAGE
        # MODE_HELP copy: at least the phrase that keys the LIVE mode.
        assert "watching live MT5 bars" in V2_PAGE

    def test_waiting_panel_present(self):
        assert 'id="waiting-panel"' in V2_PAGE
        for marker in ("Waiting on the market",
                       "Next bar close",
                       "Workspace",
                       "On standby"):
            assert marker in V2_PAGE, f"missing waiting-panel label: {marker!r}"

    def test_player_tooltip_present(self):
        assert 'id="player-tooltip"' in V2_PAGE
        # Playstyle map — hover tooltips key off these agent ids.
        for aid in ("isagi_yoichi", "bachira_meguru", "itoshi_rin",
                    "chigiri_hyoma", "reo_mikage", "nagi_seishiro",
                    "barou_shoei"):
            assert aid in V2_PAGE, f"missing agent id in PLAYER_INFO: {aid!r}"
        for style in ("conservative_metavision", "rebel_tight",
                      "analytical_precision", "speed_momentum",
                      "copier_hrp", "confluence_only", "solo_king"):
            assert style in V2_PAGE, f"missing playstyle string: {style!r}"

    def test_first_visit_ribbon_present(self):
        assert 'id="v2-ribbon"' in V2_PAGE
        assert "First time here?" in V2_PAGE
        # localStorage key that gates the ribbon on repeat visits.
        assert "v2_visited" in V2_PAGE
        assert "Show me around" in V2_PAGE

    def test_guided_tour_present(self):
        for marker in (
            'id="tour-shade"',
            'id="tour-tooltip"',
            'id="take-tour"',
            "TOUR_STEPS",
        ):
            assert marker in V2_PAGE, f"missing tour piece: {marker!r}"
        # Each of the 6 tour-step titles surfaces in the static string.
        for step_title in ("Mode picker", "Info button", "The pitch",
                           "Match ticker", "League table", "Playback speed"):
            assert step_title in V2_PAGE, f"missing tour step: {step_title!r}"


class TestV2ModeAwareCopy:
    """Subtitle and popover text must adapt to the current mode."""

    def test_live_subtitle_copy(self):
        # From MODE_SUBTITLE.live in the JS.
        for marker in ("Reading live MT5 bars in real time",
                       "shadow paper only"):
            assert marker in V2_PAGE, f"missing live-subtitle: {marker!r}"

    def test_replay_subtitle_copy_retained(self):
        # The pre-existing walk-forward wording must still be reachable
        # (the JS swaps between live / replay subtitle strings).
        assert "Walk-forward replay played as a match" in V2_PAGE

    def test_subtitle_element_has_id_for_js_swap(self):
        assert 'id="v2-subtitle"' in V2_PAGE


class TestV2HubGlossaryLink:
    """The v2 info popover deep-links to the hub glossary via
    ``/#glossary`` — the anchor must exist on the hub."""

    def test_hub_details_carries_glossary_id(self):
        assert 'id="glossary"' in HUB_PAGE
        # Belt + braces: the id must be on the <details> so the hash
        # actually scrolls to it (and browsers auto-open the details).
        assert 'class="glossary" id="glossary"' in HUB_PAGE or \
            'id="glossary"' in HUB_PAGE.split(
                '<details class="glossary"')[1].split(">")[0] + ">"

    def test_v2_popover_links_to_glossary(self):
        assert "/#glossary" in V2_PAGE


# ---------------------------------------------------------------------------
# 2) HTTP integration — /v2 still renders with the new copy
# ---------------------------------------------------------------------------

@pytest.fixture()
def cold_server(tmp_path: Path):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    log_root = tmp_path / "logs"
    log_root.mkdir()
    live_dir = tmp_path / "squad_live"
    handler = make_handler(log_root, tmp_path, reviews, live_dir=live_dir)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def _get(url: str) -> tuple[int, dict, bytes]:
    with urllib.request.urlopen(url) as resp:
        return resp.status, dict(resp.headers), resp.read()


class TestV2Http:

    def test_v2_serves_html_with_new_mode_copy(self, cold_server):
        status, headers, body = _get(cold_server + "/v2")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/html")
        assert b"Blue Lock squad" in body
        # The plain-English labels reach the wire.
        assert b"Historical replay" in body
        assert b"Twin-strike rule" in body
        assert b"Single-shot rule" in body
        # The tour + ribbon markup ship on every load; JS decides
        # whether to open the ribbon based on localStorage.
        assert b"v2-ribbon" in body
        assert b"tour-shade" in body

    def test_v2_no_raw_aggregator_ids_in_dropdown_text(self, cold_server):
        # HTTP-level double check: even though the server ships the JS
        # to populate the <select> at runtime, no static <option> in
        # the served page should hard-code raw "phi41"/"arm4" as text
        # content. (Values inside `value="..."` are fine.)
        _, _, body = _get(cold_server + "/v2")
        html = body.decode("utf-8")
        select_re = re.compile(
            r'<select[^>]*id="(match|speed)"[^>]*>.*?</select>',
            re.DOTALL)
        option_re = re.compile(r"<option[^>]*>([^<]*)</option>")
        for m in select_re.finditer(html):
            for opt in option_re.finditer(m.group(0)):
                text = opt.group(1)
                assert "phi41" not in text, (
                    f"phi41 in dropdown text: {text!r}")
                assert "arm4" not in text, (
                    f"arm4 in dropdown text: {text!r}")
