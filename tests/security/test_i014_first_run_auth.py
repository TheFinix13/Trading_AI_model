"""I014 -- first-run auth UX: the F008 onboarding redirect must not
strand an authorized visitor.

The VM cutover exposed the bug: `GET /?token=X` on a fresh install
passed auth, then hit the first-visit 302 -- which dropped the query
string AND bypassed `_send`, so the session cookie planted by
`_authorized` was never emitted. The browser arrived at `/onboarding`
with neither token nor cookie and every page 401'd until the user
manually re-appended `?token=`.

Contract pinned here:

1. The 302 Location preserves the original query string.
2. The 302 response carries the `platform_token` Set-Cookie.
3. Following the redirect with ONLY the cookie succeeds (200).
4. A wrong token still 401s BEFORE the gate -- and no cookie is set.
5. Gate-off / no-token installs keep the bare `/onboarding` Location.
"""
from __future__ import annotations

import http.client
import secrets as _secrets
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import broker_connection, credentials  # noqa: E402
from scripts.serve_platform import make_handler  # noqa: E402


def _raw_get(host: str, port: int, target: str,
             cookie: str | None = None) -> tuple[int, dict, str]:
    """GET without redirect-following; returns (status, headers, body)."""
    conn = http.client.HTTPConnection(host, port, timeout=10)
    headers = {"Cookie": cookie} if cookie else {}
    conn.request("GET", target, headers=headers)
    resp = conn.getresponse()
    body = resp.read().decode(errors="replace")
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, hdrs, body


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path / "cfg")
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    broker_connection.reset_rate_limiter()
    yield
    credentials._reset_state_for_tests()
    broker_connection.reset_rate_limiter()


def _server(tmp_path: Path, auth_token: str | None):
    reviews = tmp_path / "reviews"
    reviews.mkdir(exist_ok=True)
    log_root = tmp_path / "logs"
    log_root.mkdir(exist_ok=True)
    handler = make_handler(log_root, tmp_path, reviews,
                           live_dir=tmp_path / "sq",
                           auth_token=auth_token,
                           enforce_onboarding_gate=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class TestFirstRunRedirectKeepsAuth:

    def test_redirect_preserves_query_token(self, tmp_path):
        token = _secrets.token_hex(8)
        srv = _server(tmp_path, token)
        try:
            host, port = srv.server_address
            status, hdrs, _ = _raw_get(host, port, f"/?token={token}")
            assert status == 302
            assert hdrs["location"] == f"/onboarding?token={token}"
        finally:
            srv.shutdown()

    def test_redirect_sets_session_cookie(self, tmp_path):
        token = _secrets.token_hex(8)
        srv = _server(tmp_path, token)
        try:
            host, port = srv.server_address
            status, hdrs, _ = _raw_get(host, port, f"/?token={token}")
            assert status == 302
            cookie = hdrs.get("set-cookie", "")
            assert f"platform_token={token}" in cookie
            assert "HttpOnly" in cookie
            assert "SameSite=Strict" in cookie
        finally:
            srv.shutdown()

    def test_cookie_alone_reaches_onboarding(self, tmp_path):
        """The full first-run hop: token once, cookie ever after."""
        token = _secrets.token_hex(8)
        srv = _server(tmp_path, token)
        try:
            host, port = srv.server_address
            _, hdrs, _ = _raw_get(host, port, f"/?token={token}")
            cookie = hdrs["set-cookie"].split(";")[0]
            status, _, body = _raw_get(host, port, "/onboarding",
                                       cookie=cookie)
            assert status == 200
            assert "Set up your Blue Lock install" in body
        finally:
            srv.shutdown()

    def test_wrong_token_gets_401_and_no_cookie(self, tmp_path):
        srv = _server(tmp_path, _secrets.token_hex(8))
        try:
            host, port = srv.server_address
            status, hdrs, body = _raw_get(host, port, "/?token=wrong")
            assert status == 401
            assert "set-cookie" not in hdrs
            assert "unauthorized" in body
        finally:
            srv.shutdown()

    def test_no_auth_token_keeps_bare_location(self, tmp_path):
        """Localhost installs without a token: behaviour unchanged."""
        srv = _server(tmp_path, None)
        try:
            host, port = srv.server_address
            status, hdrs, _ = _raw_get(host, port, "/")
            assert status == 302
            assert hdrs["location"] == "/onboarding"
            assert "set-cookie" not in hdrs
        finally:
            srv.shutdown()
