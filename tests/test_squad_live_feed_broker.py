"""I019 regression: ``--feed mt5`` must attach a real MT5 broker, never paper.

Before the fix, ``_connect_mt5`` built a bare ``LiveConfig()`` whose
``broker_type`` defaults to ``"paper"``. PaperBroker memoizes the
parquet cache once at boot, so the "live" squad runtime silently froze
at the newest cached bar — 8 silent weekdays in the 2026-07-28 weekly
review traced back to this. These tests pin the contract:

1. With credentials in the agent config, the squad feed builds an
   ``mt5`` broker with those credentials.
2. Without credentials it fails LOUDLY instead of degrading to the
   frozen paper snapshot.
3. An explicit paper LiveConfig is refused outright.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_squad_live  # noqa: E402


class _FakeBroker:
    def __init__(self, connect_ok: bool = True):
        self._connect_ok = connect_ok

    async def connect(self) -> bool:
        return self._connect_ok


def _agent_cfg(**overrides):
    base = dict(
        mt5_login="12345678",
        mt5_password="hunter2",
        mt5_server="Exness-MT5Trial",
        mt5_path="C:/mt5/terminal64.exe",
        data_dir=Path("/tmp/does-not-matter"),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_connect_mt5_uses_real_broker_with_env_credentials(monkeypatch):
    """Default path builds broker_type='mt5' from agent config creds."""
    captured: dict = {}

    def fake_create_broker(**kwargs):
        captured.update(kwargs)
        return _FakeBroker()

    monkeypatch.setattr("agent.config.load_config", lambda: _agent_cfg())
    monkeypatch.setattr("agent.live.broker.create_broker", fake_create_broker)

    broker = asyncio.run(run_squad_live._connect_mt5())

    assert isinstance(broker, _FakeBroker)
    assert captured["broker_type"] == "mt5"
    assert captured["login"] == 12345678
    assert captured["password"] == "hunter2"
    assert captured["server"] == "Exness-MT5Trial"


def test_connect_mt5_refuses_to_run_without_credentials(monkeypatch):
    """Missing creds -> loud RuntimeError, no silent paper fallback."""
    def fake_create_broker(**kwargs):  # pragma: no cover - must not run
        raise AssertionError("create_broker must not be called without creds")

    monkeypatch.setattr(
        "agent.config.load_config",
        lambda: _agent_cfg(mt5_login="", mt5_password=""),
    )
    monkeypatch.setattr("agent.live.broker.create_broker", fake_create_broker)

    with pytest.raises(RuntimeError, match="I019"):
        asyncio.run(run_squad_live._connect_mt5())


def test_connect_mt5_refuses_explicit_paper_config(monkeypatch):
    """A paper LiveConfig can never masquerade as a live mt5 feed."""
    from agent.live.config import LiveConfig

    monkeypatch.setattr("agent.config.load_config", lambda: _agent_cfg())

    with pytest.raises(RuntimeError, match="paper"):
        asyncio.run(run_squad_live._connect_mt5(LiveConfig(broker_type="paper")))


def test_connect_mt5_raises_when_broker_connect_fails(monkeypatch):
    """Connect failure surfaces as an error, not a degraded feed."""
    monkeypatch.setattr("agent.config.load_config", lambda: _agent_cfg())
    monkeypatch.setattr(
        "agent.live.broker.create_broker",
        lambda **kwargs: _FakeBroker(connect_ok=False),
    )

    with pytest.raises(RuntimeError, match="connect failed"):
        asyncio.run(run_squad_live._connect_mt5())
