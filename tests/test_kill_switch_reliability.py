"""Kill-switch reliability regressions found from a week of VM agent logs
(2026-06-30 -> 2026-07-06): a single bare relative ``kill.txt`` was shared
across all three symbol processes (each launched from the same repo CWD),
so EURUSD's false-alarm daily-DD halt (from a fabricated $0 account read
during Exness maintenance) silently halted GBPUSD and USDCAD too, and kept
halting them across VM/script restarts with zero indication why.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.utils import kill_switch_active, kill_switch_reason

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "run_live_kswitch", _PROJECT_ROOT / "scripts" / "run_live.py")
run_live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_live)


# ---------------------------------------------------------------------------
# agent.utils.kill_switch_reason
# ---------------------------------------------------------------------------


def test_kill_switch_reason_none_when_file_missing(tmp_path):
    assert kill_switch_reason(tmp_path / "kill.txt") is None


def test_kill_switch_reason_returns_file_content(tmp_path):
    path = tmp_path / "kill.txt"
    path.write_text("Auto-kill: Daily DD halt: 100.0% (limit 3.0%)\n2026-07-02T19:29:32+00:00\n")
    reason = kill_switch_reason(path)
    assert "Daily DD halt" in reason
    assert "100.0%" in reason


def test_kill_switch_reason_respects_skip_env(tmp_path, monkeypatch):
    path = tmp_path / "kill.txt"
    path.write_text("Auto-kill: something bad")
    monkeypatch.setenv("SKIP_KILL_SWITCH", "1")
    assert kill_switch_reason(path) is None
    assert kill_switch_active(path) is False


# ---------------------------------------------------------------------------
# Per-symbol kill file scoping
# ---------------------------------------------------------------------------


def test_kill_file_is_scoped_per_symbol_under_log_root(tmp_path):
    import copy

    from agent.config import load_config

    # load_config() is lru_cache'd (one shared Config instance) — copy
    # before mutating .symbol so this doesn't leak into other tests.
    cfg = copy.copy(load_config())
    cfg.symbol = "USDCAD"
    args = SimpleNamespace(
        broker="paper", interval=30, no_revenge_guard=False, balance=None,
        no_telegram=True,
    )
    live = run_live._build_live_config(cfg, args, ["H4"], tmp_path)
    assert live.kill_file == str(tmp_path / "USDCAD" / "kill.txt")


def test_different_symbols_get_different_kill_files(tmp_path):
    import copy

    from agent.config import load_config

    args = SimpleNamespace(
        broker="paper", interval=30, no_revenge_guard=False, balance=None,
        no_telegram=True,
    )
    # load_config() is lru_cache'd (one shared Config instance) — copy
    # before mutating .symbol so the two calls don't clobber each other.
    cfg_a = copy.copy(load_config())
    cfg_a.symbol = "EURUSD"
    cfg_b = copy.copy(load_config())
    cfg_b.symbol = "GBPUSD"
    live_a = run_live._build_live_config(cfg_a, args, ["H4"], tmp_path)
    live_b = run_live._build_live_config(cfg_b, args, ["H4"], tmp_path)
    assert live_a.kill_file != live_b.kill_file
    assert "EURUSD" in live_a.kill_file
    assert "GBPUSD" in live_b.kill_file


# ---------------------------------------------------------------------------
# Startup refuses to silently loop if a kill file already exists
# ---------------------------------------------------------------------------


def test_main_refuses_to_start_when_kill_file_present(monkeypatch, tmp_path, caplog):
    fake_route = SimpleNamespace(
        symbol="EURUSD", timeframe="H4", session="all", mode="htf_against",
        risk_scale=1.0, alpha=SimpleNamespace(name="zone_h4_all"),
    )
    monkeypatch.setattr(run_live, "build_live_routes",
                        lambda symbol, cfg: [fake_route])
    monkeypatch.setattr(run_live, "setup_live_logging",
                        lambda symbol, log_dir=None: tmp_path / symbol / "x.log")

    kill_path = tmp_path / "EURUSD" / "kill.txt"
    kill_path.parent.mkdir(parents=True, exist_ok=True)
    kill_path.write_text("Auto-kill: Daily DD halt: 100.0% (limit 3.0%)\n")

    monkeypatch.setattr(sys, "argv", [
        "run_live.py", "--symbol", "EURUSD", "--log-dir", str(tmp_path),
    ])

    import logging
    with caplog.at_level(logging.ERROR, logger="run_live"):
        with pytest.raises(SystemExit) as exc:
            run_live.main()
    assert exc.value.code == 1
    assert "REFUSING TO START" in caplog.text
    assert "Daily DD halt" in caplog.text


def test_main_ignores_kill_file_when_kill_switch_off(monkeypatch, tmp_path):
    # main() sets os.environ["SKIP_KILL_SWITCH"] directly (not via
    # monkeypatch) when --kill-switch off is passed. monkeypatch.delenv on
    # an absent key registers nothing to restore, so seed a placeholder via
    # setenv first — monkeypatch always restores to the pre-test state
    # (here: unset) at teardown regardless of what main() sets it to in
    # between. Without this the leak silently disables every later test's
    # kill-switch checks in the same pytest session.
    monkeypatch.setenv("SKIP_KILL_SWITCH", "0")
    fake_route = SimpleNamespace(
        symbol="EURUSD", timeframe="H4", session="all", mode="htf_against",
        risk_scale=1.0, alpha=SimpleNamespace(name="zone_h4_all"),
    )
    monkeypatch.setattr(run_live, "build_live_routes",
                        lambda symbol, cfg: [fake_route])
    monkeypatch.setattr(run_live, "setup_live_logging",
                        lambda symbol, log_dir=None: tmp_path / symbol / "x.log")

    kill_path = tmp_path / "EURUSD" / "kill.txt"
    kill_path.parent.mkdir(parents=True, exist_ok=True)
    kill_path.write_text("Auto-kill: something")

    async def fake_health(args, cfg, live):
        return False  # force a clean, early exit(1) after the preflight check

    monkeypatch.setattr(run_live, "_startup_health", fake_health)
    monkeypatch.setattr(sys, "argv", [
        "run_live.py", "--symbol", "EURUSD", "--log-dir", str(tmp_path),
        "--kill-switch", "off",
    ])
    with pytest.raises(SystemExit) as exc:
        run_live.main()
    # Reaches _startup_health (which we force to fail) rather than being
    # refused at the kill-file preflight check.
    assert exc.value.code == 1
