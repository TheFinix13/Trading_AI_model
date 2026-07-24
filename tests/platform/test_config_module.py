"""F019 (I004) -- ``[internal] token`` config-dir resolution seam.

``agent.platform.config.load_config`` resolves the internal token in
this order:

1. ``<config_dir>/platform.toml`` (the ``BLUELOCK_CONFIG_DIR`` seam /
   in-process credentials override) -- config-dir WINS when set.
2. The repo-root ``platform.toml`` -- backwards-compatible fallback so
   repo-root-only installs (the VM) behave identically.
3. Unset in both places -> ``""`` and the submit gate fails closed
   (byte-for-byte the pre-F019 refusal).

Only the token key rides the seam; every other setting keeps its
repo-root semantics.
"""
from __future__ import annotations

import json
import secrets as _secrets
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import (  # noqa: E402
    approval_queue, credentials, kill_switches,
)
from agent.platform.config import load_config  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfgdir")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    monkeypatch.setenv(kill_switches.KILL_DIR_ENV,
                       str(tmp_path / "cfgdir" / "kill"))
    approval_queue.reset_state()
    yield
    credentials._reset_state_for_tests()
    approval_queue.reset_state()


def _write_toml(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[internal]\ntoken = "{token}"\n', encoding="utf-8")


class TestTokenResolutionOrder:

    def test_config_dir_wins_over_repo_root(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_toml(repo / "platform.toml", "repo-root-token")
        _write_toml(tmp_path / "cfgdir" / "platform.toml",
                    "config-dir-token")
        cfg = load_config(repo)
        assert cfg["internal"]["token"] == "config-dir-token"

    def test_repo_root_fallback_when_config_dir_file_absent(
            self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_toml(repo / "platform.toml", "repo-root-token")
        cfg = load_config(repo)
        assert cfg["internal"]["token"] == "repo-root-token"

    def test_repo_root_fallback_when_config_dir_file_has_no_token(
            self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_toml(repo / "platform.toml", "repo-root-token")
        seam = tmp_path / "cfgdir" / "platform.toml"
        seam.parent.mkdir(parents=True, exist_ok=True)
        seam.write_text("[internal]\n", encoding="utf-8")
        cfg = load_config(repo)
        assert cfg["internal"]["token"] == "repo-root-token"

    def test_unset_everywhere_stays_fail_closed(self, tmp_path: Path):
        # Pin the pre-F019 refusal: no token anywhere -> "" (the submit
        # gate refuses every request on empty token).
        repo = tmp_path / "repo"
        repo.mkdir()
        cfg = load_config(repo)
        assert cfg["internal"]["token"] == ""

    def test_malformed_config_dir_file_falls_back(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_toml(repo / "platform.toml", "repo-root-token")
        seam = tmp_path / "cfgdir" / "platform.toml"
        seam.parent.mkdir(parents=True, exist_ok=True)
        seam.write_text("not [valid toml", encoding="utf-8")
        cfg = load_config(repo)
        assert cfg["internal"]["token"] == "repo-root-token"

    def test_only_the_token_key_rides_the_seam(self, tmp_path: Path):
        # A config-dir file with other settings must not leak them into
        # the merged config -- repo-root semantics stay untouched.
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "platform.toml").write_text(
            'port = 9999\n[internal]\ntoken = "repo-token"\n',
            encoding="utf-8")
        seam = tmp_path / "cfgdir" / "platform.toml"
        seam.parent.mkdir(parents=True, exist_ok=True)
        seam.write_text(
            'port = 1111\nhost = "0.0.0.0"\n'
            '[internal]\ntoken = "seam-token"\n', encoding="utf-8")
        cfg = load_config(repo)
        assert cfg["internal"]["token"] == "seam-token"
        assert cfg["port"] == 9999          # repo-root wins for non-token
        assert cfg["host"] == "127.0.0.1"   # default, not the seam file


# ---------------------------------------------------------------------------
# API level: the submit gate honours a config-dir-provisioned token
# (the exact path the dogfood harness now uses -- zero repo-root writes).
# ---------------------------------------------------------------------------

def _request(url: str, method: str = "GET", body: dict | None = None,
             headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode(errors="replace")
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        code = e.code
    try:
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        parsed = None
    return code, parsed if isinstance(parsed, dict) else None


def _payload() -> dict:
    return {
        "symbol": "EURUSD", "side": "buy", "size": 0.01,
        "entry": 1.0850, "stop": 1.0800, "take_profit": 1.0950,
        "rationale": "config-seam test", "source_agent": "test",
        "risk_snapshot": {"worst_case_loss": 5.0},
    }


class TestSubmitGateViaConfigDirToken:

    def _server(self, tmp_path: Path):
        reviews = tmp_path / "reviews"
        reviews.mkdir(exist_ok=True)
        log_root = tmp_path / "logs"
        log_root.mkdir(exist_ok=True)
        handler = make_handler(log_root, tmp_path, reviews,
                               live_dir=tmp_path / "sq",
                               enforce_install_token=False,
                               enforce_onboarding_gate=False)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    def test_config_dir_token_accepted(self, tmp_path: Path):
        token = "seam-" + _secrets.token_hex(8)
        _write_toml(tmp_path / "cfgdir" / "platform.toml", token)
        srv = self._server(tmp_path)
        try:
            host, port = srv.server_address
            code, body = _request(
                f"http://{host}:{port}/api/approvals/submit",
                method="POST", body=_payload(),
                headers={"X-Bluelock-Internal-Token": token})
            assert code == 200
            assert body["ok"] is True
        finally:
            srv.shutdown()

    def test_wrong_token_still_refused(self, tmp_path: Path):
        _write_toml(tmp_path / "cfgdir" / "platform.toml",
                    "seam-" + _secrets.token_hex(8))
        srv = self._server(tmp_path)
        try:
            host, port = srv.server_address
            code, body = _request(
                f"http://{host}:{port}/api/approvals/submit",
                method="POST", body=_payload(),
                headers={"X-Bluelock-Internal-Token": "wrong"})
            assert code == 401
        finally:
            srv.shutdown()
