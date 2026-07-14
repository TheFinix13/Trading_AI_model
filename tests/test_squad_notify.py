"""Tests for the dedicated squad Telegram bot (agent/platform/squad_notify.py).

The v2 squad pages through its OWN bot (separate token + chat from the
v1 trading bot). Under test: config precedence (platform.toml [telegram]
wins over SQUAD_TELEGRAM_* env vars), the pure football-flavored
formatters, the rate-limiting router (goals always, proposals never,
league tables throttled), and the paper-loop wiring end-to-end with a
mocked transport — no real network anywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.notifications.telegram import TelegramConfig  # noqa: E402
from agent.platform.paper_loop import PaperLoop  # noqa: E402
from agent.platform.squad_notify import (  # noqa: E402
    SquadNotifier,
    build_league_table,
    build_squad_full_time,
    build_squad_goal,
    build_squad_halt,
    build_squad_kickoff,
    build_squad_miss,
    resolve_config,
)


class _FakeResponse:
    status_code = 200
    text = ""


class _FakeClient:
    def __init__(self):
        self.calls: list[dict] = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(json)
        return _FakeResponse()


class _RaisingClient:
    def post(self, url, json=None, timeout=None):
        raise ConnectionError("network unreachable")


def _notifier(client=None, summary_every=10) -> SquadNotifier:
    return SquadNotifier(
        TelegramConfig(bot_token="squad-tok", chat_id="777"),
        summary_every=summary_every, client=client or _FakeClient())


def _texts(client: _FakeClient) -> list[str]:
    return [c["text"] for c in client.calls]


# ---------------------------------------------------------------------------
# Config resolution: platform.toml [telegram] wins over SQUAD_TELEGRAM_* env
# ---------------------------------------------------------------------------

class TestResolveConfig:

    def test_env_fallback_when_no_toml(self):
        cfg, every = resolve_config(None, {
            "SQUAD_TELEGRAM_BOT_TOKEN": "env-tok",
            "SQUAD_TELEGRAM_CHAT_ID": "111",
        })
        assert cfg.bot_token == "env-tok"
        assert cfg.chat_id == "111"
        assert cfg.configured
        assert every == 10

    def test_toml_wins_over_env_per_key(self):
        cfg, every = resolve_config(
            {"bot_token": "toml-tok", "summary_every": 5},
            {"SQUAD_TELEGRAM_BOT_TOKEN": "env-tok",
             "SQUAD_TELEGRAM_CHAT_ID": "111"})
        assert cfg.bot_token == "toml-tok"   # toml wins
        assert cfg.chat_id == "111"          # env fills the gap
        assert every == 5

    def test_unconfigured_when_both_sources_empty(self):
        cfg, _ = resolve_config({}, {})
        assert not cfg.configured

    def test_v1_bot_env_vars_are_ignored(self):
        """The squad channel is separate BY DESIGN — the v1 bot's
        TG_BOT_TOKEN / TG_CHAT_ID must never leak into the squad bot."""
        cfg, _ = resolve_config(None, {
            "TG_BOT_TOKEN": "v1-tok", "TG_CHAT_ID": "999"})
        assert not cfg.configured

    def test_platform_toml_telegram_table_loads(self, tmp_path):
        from agent.platform.config import load_config
        (tmp_path / "platform.toml").write_text(
            '[telegram]\nbot_token = "t"\nchat_id = "42"\n'
            "summary_every = 3\n", encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["telegram"] == {
            "bot_token": "t", "chat_id": "42", "summary_every": 3}

    def test_platform_toml_without_telegram_table(self, tmp_path):
        from agent.platform.config import load_config
        cfg = load_config(tmp_path)
        assert cfg["telegram"]["bot_token"] == ""
        assert cfg["telegram"]["summary_every"] == 10


# ---------------------------------------------------------------------------
# Pure formatters
# ---------------------------------------------------------------------------

class TestFormatters:

    def test_kickoff(self):
        msg = build_squad_kickoff(
            source_label="g7_replay_cache_phi5-arm4", n_rows=1234,
            out_dir="/logs/squad_live")
        assert msg.splitlines()[0] == "*SQUAD | KICKOFF*"
        assert "g7_replay_cache_phi5-arm4" in msg
        assert "1234 rows queued" in msg
        assert "no broker orders" in msg

    def test_goal_is_symbol_first_and_dense(self):
        msg = build_squad_goal(agent_id="isagi_yoichi", symbol="EURUSD",
                               pips=42.5, tqs=0.61, r_multiple=1.5,
                               exit_reason="tp")
        assert msg.splitlines()[0] == "*EURUSD | GOAL — Isagi #11*"
        assert "`+42.5p`" in msg
        assert "`+1.50R`" in msg
        assert "TQS `0.61`" in msg
        assert "Exit: tp" in msg

    def test_goal_omits_missing_stats(self):
        msg = build_squad_goal(agent_id="barou_shoei", symbol="USDCAD",
                               pips=10.0)
        assert "TQS" not in msg
        assert "R`" not in msg
        assert "Exit:" not in msg

    def test_miss(self):
        msg = build_squad_miss(agent_id="bachira_meguru", symbol="USDCAD",
                               pips=-20.0, r_multiple=-1.0, exit_reason="sl")
        assert msg.splitlines()[0] == "*USDCAD | Shot MISSED — Bachira #8*"
        assert "`-20.0p`" in msg
        assert "`-1.00R`" in msg

    def test_unknown_agent_id_passes_through(self):
        msg = build_squad_goal(agent_id="mystery_player", symbol="GBPUSD",
                               pips=5.0)
        assert "mystery_player" in msg

    def test_halt_and_full_time(self):
        halt = build_squad_halt(reason="pause for review")
        assert halt.splitlines()[0] == "*SQUAD | MATCH HALTED*"
        assert "pause for review" in halt
        ft = build_squad_full_time(outcome="done")
        assert ft.splitlines()[0] == "*SQUAD | FULL TIME*"
        assert "replay exhausted" in ft

    def test_league_table_sorted_by_pips_with_team_total(self):
        msg = build_league_table({
            "isagi_yoichi": {"goals": 2, "trades": 3, "pips": 60.0},
            "bachira_meguru": {"goals": 0, "trades": 1, "pips": -20.0},
            "nagi_seishiro": {"goals": 3, "trades": 3, "pips": 90.5},
            "reo_mikage": {"goals": 0, "trades": 0, "pips": 0.0},  # benched
        })
        lines = msg.splitlines()
        assert lines[0] == "*SQUAD | League table*"
        assert lines[1].startswith("1. Nagi #7 — 3G/3T `+90.5p`")
        assert lines[2].startswith("2. Isagi #11 — 2G/3T `+60.0p`")
        assert lines[3].startswith("3. Bachira #8 — 0G/1T `-20.0p`")
        assert "Reo" not in msg  # no trades -> not listed
        assert "Team total: `+130.5p`" in msg

    def test_league_table_empty(self):
        assert "No shots on target yet." in build_league_table({})


# ---------------------------------------------------------------------------
# Router: rate limiting + fail-open, mocked transport
# ---------------------------------------------------------------------------

def _trade_row(agent="isagi_yoichi", symbol="EURUSD", pips=42.5,
               tqs=0.61, r=1.5, reason="tp") -> dict:
    return {"agent_id": agent, "symbol": symbol, "pnl_pips": pips,
            "r_multiple": r, "exit_reason": reason,
            "tqs_components": {"tqs": tqs}}


class TestSquadNotifierRouting:

    def test_proposals_and_rejections_never_page(self):
        client = _FakeClient()
        n = _notifier(client)
        n.notify_row({"agent_id": "isagi_yoichi"}, "proposals_all.jsonl")
        n.notify_row({"loser_agent_id": "barou_shoei"},
                     "proposals_rejected.jsonl")
        assert client.calls == []

    def test_winning_close_pages_a_goal(self):
        client = _FakeClient()
        n = _notifier(client)
        n.notify_row(_trade_row(), "trades.jsonl")
        assert len(client.calls) == 1
        assert "GOAL — Isagi #11" in _texts(client)[0]

    def test_losing_close_pages_a_miss(self):
        client = _FakeClient()
        n = _notifier(client)
        n.notify_row(_trade_row(pips=-20.0, r=-1.0, reason="sl"),
                     "trades.jsonl")
        assert "Shot MISSED" in _texts(client)[0]

    def test_league_table_every_n_closes(self):
        client = _FakeClient()
        n = _notifier(client, summary_every=2)
        for i in range(4):
            n.notify_row(_trade_row(pips=10.0 * (i + 1)), "trades.jsonl")
        tables = [t for t in _texts(client) if "League table" in t]
        assert len(tables) == 2  # after close #2 and close #4
        assert "1G/1T" not in tables[-1]
        assert "4G/4T" in tables[-1]
        assert "Team total: `+100.0p`" in tables[-1]

    def test_unconfigured_is_a_silent_noop(self):
        client = _FakeClient()
        n = SquadNotifier(TelegramConfig(), client=client)
        n.notify_kickoff(source_label="x", n_rows=1, out_dir="y")
        n.notify_row(_trade_row(), "trades.jsonl")
        n.notify_stop("done")
        assert client.calls == []

    def test_network_failure_never_raises(self):
        n = _notifier(_RaisingClient())
        n.notify_kickoff(source_label="x", n_rows=1, out_dir="y")
        n.notify_row(_trade_row(), "trades.jsonl")
        n.notify_stop("killed", reason="boom")

    def test_malformed_trade_row_never_raises(self):
        client = _FakeClient()
        n = _notifier(client)
        n.notify_row({"pnl_pips": "not-a-number"}, "trades.jsonl")

    def test_stop_sends_halt_plus_table_after_trades(self):
        client = _FakeClient()
        n = _notifier(client)
        n.notify_row(_trade_row(), "trades.jsonl")
        n.notify_stop("killed", reason="pause for review")
        texts = _texts(client)
        assert any("MATCH HALTED" in t for t in texts)
        assert texts[-1].startswith("*SQUAD | League table*")

    def test_stop_without_trades_skips_the_table(self):
        client = _FakeClient()
        n = _notifier(client)
        n.notify_stop("done")
        texts = _texts(client)
        assert len(texts) == 1
        assert "FULL TIME" in texts[0]


# ---------------------------------------------------------------------------
# Paper-loop wiring end-to-end (mocked transport)
# ---------------------------------------------------------------------------

@pytest.fixture()
def source_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "g7_replay_cache_source"
    cache.mkdir()
    (cache / "proposals_all.jsonl").write_text(json.dumps(
        {"agent_id": "isagi_yoichi", "timestamp": "2024-01-01T00:00:00+00:00",
         "symbol": "EURUSD", "direction": "long", "conviction": 0.75},
    ) + "\n", encoding="utf-8")
    (cache / "proposals_rejected.jsonl").write_text(json.dumps(
        {"tick_id": 1, "symbol": "USDCAD",
         "timestamp": "2024-01-01T04:00:00+00:00",
         "winner_agent_id": "isagi_yoichi", "loser_agent_id": "barou_shoei",
         "rejection_reason": "lower_conviction_same_symbol"},
    ) + "\n", encoding="utf-8")
    (cache / "trades.jsonl").write_text(json.dumps(
        {"agent_id": "isagi_yoichi", "symbol": "EURUSD",
         "entry_time": "2024-01-01 00:00:00+00:00",
         "exit_time": "2024-01-01 12:00:00+00:00",
         "direction": "long", "exit_reason": "tp", "pnl_pips": 42.5,
         "r_multiple": 1.5, "tqs_components": {"tqs": 0.61}},
    ) + "\n", encoding="utf-8")
    return cache


def _run(loop: PaperLoop, **kw) -> str:
    return loop.run(sleep=lambda s: None, log=lambda *a, **k: None, **kw)


class TestPaperLoopWiring:

    def test_full_replay_pages_kickoff_goal_fulltime_table(
            self, source_cache, tmp_path):
        client = _FakeClient()
        loop = PaperLoop(source_cache, tmp_path / "out", tick_seconds=0,
                         notifier=_notifier(client))
        assert _run(loop) == "done"
        texts = _texts(client)
        assert "KICKOFF" in texts[0]
        assert "3 rows queued" in texts[0]
        assert any("GOAL — Isagi #11" in t for t in texts)
        assert any("FULL TIME" in t for t in texts)
        assert "League table" in texts[-1]
        # Proposals/rejections replayed but never paged: exactly
        # kickoff + 1 goal + full-time + final table.
        assert len(texts) == 4

    def test_kill_pages_match_halted(self, source_cache, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "kill.txt").write_text("pause for review", encoding="utf-8")
        client = _FakeClient()
        loop = PaperLoop(source_cache, out, tick_seconds=0,
                         notifier=_notifier(client))
        assert _run(loop) == "killed"
        assert any("MATCH HALTED" in t and "pause for review" in t
                   for t in _texts(client))

    def test_no_notifier_stays_silent(self, source_cache, tmp_path):
        loop = PaperLoop(source_cache, tmp_path / "out", tick_seconds=0)
        assert _run(loop) == "done"  # notify_event(None) is a no-op

    def test_broken_transport_does_not_break_the_replay(
            self, source_cache, tmp_path):
        loop = PaperLoop(source_cache, tmp_path / "out", tick_seconds=0,
                         notifier=_notifier(_RaisingClient()))
        assert _run(loop) == "done"
        assert loop.remaining() == 0
