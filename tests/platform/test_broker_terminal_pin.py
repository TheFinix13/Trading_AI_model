"""Dual-terminal MT5 pin (2026-07-24 account-contention incident).

``[broker] terminal_path`` in platform.toml pins every platform-side
``mt5.initialize`` (broker-wizard probe, F018 demo executor) to a
dedicated terminal install so the machine-default terminal — the v1
zones agent's — is never switched to another account.

Covered here:

1. ``load_config`` parses the ``[broker]`` table (defaults, values,
   the literal-true-only ``portable`` acknowledgement posture).
2. ``broker_connection.terminal_launch_args()`` maps config into
   ``mt5.initialize`` splice args — ``([], {})`` when unpinned so the
   historic single-terminal call stays byte-identical.
3. ``RealMt5OrderAdapter.connect`` passes the pin positionally
   (the MetaTrader5 package declares ``path`` as an unnamed first
   parameter).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import broker_connection, live_executor  # noqa: E402
from agent.platform import config as config_module  # noqa: E402
from agent.platform.config import load_config  # noqa: E402


class TestBrokerConfigParsing:
    def test_defaults_when_absent(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert cfg["broker"] == {"terminal_path": "", "portable": False}

    def test_values_parsed(self, tmp_path: Path) -> None:
        (tmp_path / "platform.toml").write_text(
            '[broker]\nterminal_path = "C:/MT5-V2/terminal64.exe"\n'
            "portable = true\n", encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["broker"]["terminal_path"] == "C:/MT5-V2/terminal64.exe"
        assert cfg["broker"]["portable"] is True

    def test_portable_literal_true_only(self, tmp_path: Path) -> None:
        (tmp_path / "platform.toml").write_text(
            '[broker]\nterminal_path = "C:/x/terminal64.exe"\n'
            'portable = "yes"\n', encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["broker"]["portable"] is False

    def test_path_whitespace_stripped(self, tmp_path: Path) -> None:
        (tmp_path / "platform.toml").write_text(
            '[broker]\nterminal_path = "  C:/x/terminal64.exe  "\n',
            encoding="utf-8")
        cfg = load_config(tmp_path)
        assert cfg["broker"]["terminal_path"] == "C:/x/terminal64.exe"


class TestTerminalLaunchArgs:
    def _patch_cfg(self, monkeypatch: pytest.MonkeyPatch,
                   broker: dict) -> None:
        monkeypatch.setattr(
            config_module, "load_config",
            lambda repo_root, path=None: {"broker": broker})

    def test_unpinned_is_empty(self, monkeypatch) -> None:
        self._patch_cfg(monkeypatch, {"terminal_path": "",
                                      "portable": False})
        assert broker_connection.terminal_launch_args() == ([], {})

    def test_pinned_returns_path_and_portable(self, monkeypatch) -> None:
        self._patch_cfg(monkeypatch, {"terminal_path": "C:/MT5-V2/t.exe",
                                      "portable": True})
        args, kwargs = broker_connection.terminal_launch_args()
        assert args == ["C:/MT5-V2/t.exe"]
        assert kwargs == {"portable": True}

    def test_config_error_falls_back_unpinned(self, monkeypatch) -> None:
        def _boom(repo_root, path=None):
            raise OSError("disk gone")
        monkeypatch.setattr(config_module, "load_config", _boom)
        assert broker_connection.terminal_launch_args() == ([], {})


class _FakeMt5:
    """Records initialize/login args; connect() succeeds."""

    def __init__(self) -> None:
        self.initialize_calls: list[tuple[tuple, dict]] = []
        self.login_calls: list[tuple[tuple, dict]] = []

    def initialize(self, *args, **kwargs):
        self.initialize_calls.append((args, kwargs))
        return True

    def login(self, *args, **kwargs):
        self.login_calls.append((args, kwargs))
        return True

    def shutdown(self):
        return None


class TestAdapterUsesPin:
    _CREDS = {"login": "436983644", "password": "pw-not-real",
              "server": "Exness-MT5Trial9"}

    def _wire(self, monkeypatch: pytest.MonkeyPatch,
              pin: tuple[list, dict]) -> _FakeMt5:
        fake = _FakeMt5()
        monkeypatch.setattr(live_executor.RealMt5OrderAdapter, "_mt5",
                            staticmethod(lambda: fake))
        monkeypatch.setattr(live_executor.broker_connection,
                            "load_credentials",
                            lambda alias: dict(self._CREDS))
        monkeypatch.setattr(live_executor.broker_connection,
                            "terminal_launch_args", lambda: pin)
        return fake

    def test_pinned_path_passed_positionally(self, monkeypatch) -> None:
        fake = self._wire(monkeypatch,
                          (["C:/MT5-V2/t.exe"], {"portable": True}))
        adapter = live_executor.RealMt5OrderAdapter()
        assert adapter.connect("v2-platform") is True
        assert fake.initialize_calls == [
            (("C:/MT5-V2/t.exe",), {"portable": True})]
        assert fake.login_calls[0][0] == (436983644,)

    def test_unpinned_keeps_bare_initialize(self, monkeypatch) -> None:
        fake = self._wire(monkeypatch, ([], {}))
        adapter = live_executor.RealMt5OrderAdapter()
        assert adapter.connect("v2-platform") is True
        assert fake.initialize_calls == [((), {})]
