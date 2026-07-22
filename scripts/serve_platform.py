"""Trading platform web server — hub, /v1 live view, /v2 squad pitch.

One stdlib-only process serving three pages:

* ``/``    hub — links to both views with their live/sim status.
* ``/v1``  zones agent LIVE dashboard: read-only over the running
           agent's log root (``state.json``, daily logs, kill files).
           Auto-refreshes every 10 s. Nothing here can affect trading.
* ``/v2``  Blue Lock squad pitch: the M001 ensemble replayed as a
           football match (passes = proposals, tackles = aggregator
           rejections, Sentinel wall, goals = winning trades). Reads
           replay artifact FILES from the research repo read-only —
           research code is never imported (hard workspace rule).

Run on the VM (second clone, next-gen branch — never the trading clone):

    python scripts/serve_platform.py ^
        --log-root %USERPROFILE%\\Documents\\TradingAgentLogs ^
        --host 0.0.0.0 --port 8787

Then browse http://<VM-IP>:8787 from the Mac. On the Mac itself the
defaults work as-is (sibling research checkout is auto-detected).

``scripts/serve_live_dashboard.py`` remains as the v1-only variant;
this server supersedes it for day-to-day use.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.platform import (  # noqa: E402
    alerts, alerts_sse, alerts_telegram, approval_queue, auth,
    broker_connection, broker_health, credentials, hq, kill_switch_admin,
    kill_switches, live_status, onboarding, paper_loop, performance,
    players, rate_limiter, research, risk_budget, squad_events,
)
from agent.platform.config import load_config  # noqa: E402
from agent.platform.pages import (  # noqa: E402
    ALERTS_PAGE, APPROVALS_PAGE, BROKER_WIZARD_PAGE, HQ_PAGE, HUB_PAGE,
    KILL_SWITCHES_PAGE, LIVE_MODE_TOGGLE_PAGE, ONBOARDING_PAGE,
    PERFORMANCE_PAGE, PLAYERS_INDEX_PAGE, RESEARCH_PAGE, RESET_INSTALL_PAGE,
    RISK_PAGE, V1_PAGE, V2_PAGE,
    player_detail_page, players_not_found_page,
)


def _derive_research_root(reviews_dir: Path) -> Path | None:
    """Climb up from `--research-reviews` until we find a directory
    that looks like the finance-research-experiments repo root.

    The default `research_reviews` path is
    ``.../finance-research-experiments/programs/M001_multi_agent_ensemble/reviews``,
    so we look up to three parents deep. Returns None when the reviews
    dir doesn't exist -- the F003 page falls back to the friendly
    empty state (`source_exists=False`).
    """
    if not reviews_dir or not reviews_dir.exists():
        return None
    for candidate in (reviews_dir,
                      *(reviews_dir.parents)[:5]):
        if candidate.name == "finance-research-experiments":
            return candidate
        if (candidate / "experiments").is_dir() and (candidate / "programs").is_dir():
            return candidate
    return None

PLATFORM_VERSION = "0.2.0"

_MATCH_RE = re.compile(
    r"^/api/v2/match/([A-Za-z0-9_.-]+)/(summary|events|event/(\d+))$")
_LIVE_RE = re.compile(
    r"^/api/v2/live/(summary|events|status|workspace|event/(\d+))$")
_PLAYER_URL_RE = re.compile(r"^/players/([A-Za-z0-9_-]+)/?$")
_PLAYER_API_RE = re.compile(r"^/api/players/([A-Za-z0-9_-]+)$")
_BROKER_ALIAS_RE = re.compile(r"^/api/broker/([A-Za-z0-9_.\-]+)$")
_APPROVAL_ACTION_RE = re.compile(
    r"^/api/approvals/([A-Za-z0-9_-]+)/(approve|reject)$")

# Path to the F007 live-broker warning served over /api/broker/live-warning.
_LIVE_WARNING_PATH = REPO_ROOT / "company" / "legal" / "live-broker-warning.md"

# F006 install-token gate exempts a small allow-list so the setup /
# health flow can call the platform before an install token exists.
_UNAUTHENTICATED_API_PATHS: frozenset[str] = frozenset({
    "/api/auth/status",         # F006 -- probe whether the install is set up
    "/api/broker/live-warning", # F007 -- live-broker legal warning text
    "/api/onboarding/state",    # F008 -- wizard reads state on load
    "/api/onboarding/passphrase",  # F008 -- setup happens before token exists
    "/api/onboarding/pairs",    # F008 -- setup happens before token exists
    "/api/onboarding/complete", # F008 -- setup happens before token exists
    "/api/onboarding/reset",    # F008 -- reset must work without a token
    "/api/live-mode/warning",   # F013 -- disclaimer loads BEFORE ceremony auth
    "/api/approvals/warning",   # F013 -- approval-queue warning readable pre-auth
})

# F009 -- routes that require the install-token gate BUT skip the rate
# limiter and session-expiry checks.
#
# F014's SSE stream is a long-lived connection; putting it through the
# per-request bucket would trickle-drain the user's tokens even though
# they only opened one page. Exempted here (still install-token-gated
# through `_authorized`, so unauthenticated clients cannot subscribe).
_RATE_LIMIT_EXEMPT_PATHS: frozenset[str] = frozenset({
    "/api/alerts/stream",
})

# F008 first-visit gate. When onboarding is not yet complete, every
# non-exempt HTML route redirects to /onboarding. HTTP routes that
# would break the wizard's own lifecycle stay reachable.
_ONBOARDING_HTML_ALLOWED: frozenset[str] = frozenset({
    "/onboarding", "/onboarding/",
    "/settings/reset-install", "/settings/reset-install/",
    "/settings/broker", "/settings/broker/",  # so wizard step 3 works
    "/settings/kill-switches", "/settings/kill-switches/",  # F011 safety UI always reachable
    "/settings/live-mode", "/settings/live-mode/",  # F013 safety UI always reachable
    "/healthz",
})


def make_handler(log_root: Path, repo_root: Path, reviews_dir: Path,
                 live_dir: Path | None = None,
                 auth_token: str | None = None,
                 company_ledger_path: Path | None = None,
                 research_root: Path | None = None,
                 research_manifest_path: Path | None = None,
                 enforce_install_token: bool = False,
                 enforce_onboarding_gate: bool = False):
    """``auth_token`` enables token auth on every route except /healthz
    (so uptime probes stay simple). main() only passes it through when
    binding non-localhost — on 127.0.0.1 the platform stays open.

    ``enforce_install_token`` (F006, Sprint 1): when True, every
    ``/api/*`` route (except a small allow-list -- see
    ``_UNAUTHENTICATED_API_PATHS``) requires either the presented
    install token stored in the OS keychain OR the pre-Sprint-1
    ``auth_token`` fallback. main() sets this to True only on
    non-localhost binds; localhost single-user dev stays open per D052.

    ``enforce_onboarding_gate`` (F008, Sprint 1): when True, any HTML
    GET to a non-exempt route redirects to ``/onboarding`` until
    :func:`onboarding.is_first_visit` returns False. Off by default so
    unit tests hitting `/hq`, `/players` etc. keep the Sprint 0
    contract. main() flips this on when binding non-localhost, and the
    F008 API tests opt in explicitly.

    ``company_ledger_path`` overrides the default
    ``<repo_root>/company/ledger/company_state.json`` path used by the
    /hq dashboard. Tests pass a fixture path; production leaves it
    None so `hq.hq_state()` picks up the shipped ledger.

    ``research_root`` is the root of the sibling
    `finance-research-experiments` checkout (or None when it isn't on
    this machine -- F003 renders a friendly empty state).
    ``research_manifest_path`` overrides the default
    ``<repo_root>/company/research/publication_manifest.json``.
    """
    started_at = time.time()
    derived_research_root = research_root or _derive_research_root(reviews_dir)

    class Handler(BaseHTTPRequestHandler):
        _set_cookie: str | None = None

        def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if self._set_cookie:
                self.send_header("Set-Cookie", self._set_cookie)
                self._set_cookie = None
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, code: int = 200) -> None:
            self._send(json.dumps(payload).encode(), "application/json", code)

        def _authorized(self, params: dict) -> bool:
            """?token= / Bearer header / cookie. A correct query token
            plants a session cookie so page-issued fetches (which carry
            no query token) keep working."""
            if auth_token is None:
                return True
            if params.get("token") == auth_token:
                self._set_cookie = (f"platform_token={auth_token}; Path=/; "
                                    "HttpOnly; SameSite=Strict")
                return True
            authz = self.headers.get("Authorization", "")
            if authz == f"Bearer {auth_token}":
                return True
            cookies = self.headers.get("Cookie", "")
            for part in cookies.split(";"):
                k, _, v = part.strip().partition("=")
                if k == "platform_token" and v == auth_token:
                    return True
            return False

        def _install_gate_authorized(self, params: dict) -> bool:
            """F006 auth gate for /api/* routes.

            Accepts:
              - X-Bluelock-Token header
              - Authorization: Bearer
              - platform_token cookie
              - ?token= query param
            All are compared in constant time. The pre-Sprint-1
            ``platform.toml`` ``auth_token`` remains a valid fallback so
            the deployed VM's config keeps working (D052).
            """
            header_token = (self.headers.get("X-Bluelock-Token")
                            or "").strip() or None
            authz = self.headers.get("Authorization", "")
            bearer = None
            if authz.startswith("Bearer "):
                bearer = authz[len("Bearer "):].strip() or None
            cookies = self.headers.get("Cookie", "")
            cookie_token = None
            for part in cookies.split(";"):
                k, _, v = part.strip().partition("=")
                if k == "platform_token" and v:
                    cookie_token = v
                    break
            query_token = params.get("token")
            # Any of the four positions can carry the token.
            if auth.check_request_token(header_value=header_token,
                                        cookie_value=cookie_token,
                                        query_value=query_token,
                                        fallback_token=auth_token):
                return True
            if bearer and auth.check_request_token(
                    header_value=bearer, fallback_token=auth_token):
                return True
            return False

        # F009 -- Response helpers for 429 rate-limit and 401 expired.
        def _reject_rate_limited(self, retry_after: float) -> None:
            body = json.dumps({
                "error": "rate limited",
                "hint": "wait before retrying",
                "retry_after_seconds": retry_after,
            }).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Retry-After", str(int(max(1.0, retry_after))))
            self.end_headers()
            self.wfile.write(body)

        def _reject_session_expired(self) -> None:
            self._json({
                "error": "session expired",
                "hint": "rotate your token via POST /api/auth/rotate",
            }, 401)

        def _install_gate_pass(self, path: str) -> tuple[bool, str, float]:
            """Run the F006 install-gate + F009 rate-limit + F009 session-
            expiry check in one place.

            Returns ``(passed, failure_reason, retry_after)`` where
            failure_reason is one of ``""`` (passed), ``"unauth"``,
            ``"rate_limited"``, ``"session_expired"``. ``retry_after`` is
            populated only when ``failure_reason == "rate_limited"``.
            """
            params = self._parse_query_params()
            if not self._install_gate_authorized(params):
                return False, "unauth", 0.0
            # Rate limit + session expiry keyed on the fingerprint so no
            # raw token is passed to the limiter. Localhost path
            # short-circuits above via ``_needs_install_gate``.
            if path in _RATE_LIMIT_EXEMPT_PATHS:
                return True, "", 0.0
            fp = auth.install_token_fingerprint(auth.load_install_token()) \
                or "fallback"
            # F009 session expiry only bites when we're comparing against
            # the F006 install token; the pre-Sprint-1 platform.toml
            # fallback is D052 backwards-compat and stays unchanged.
            if auth.is_install_configured() and auth.is_session_expired():
                # A rotate call is still allowed even when the current
                # session has expired -- it's the recovery path.
                if path != "/api/auth/rotate":
                    return False, "session_expired", 0.0
            allowed, retry = rate_limiter.check(fp)
            if not allowed:
                return False, "rate_limited", retry
            if auth.is_install_configured():
                auth.record_session_activity()
            return True, "", 0.0

        def _parse_query_params(self) -> dict:
            _path, _, query = self.path.partition("?")
            params = {}
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                if k:
                    params[k] = v
            return params

        def _needs_install_gate(self, path: str) -> bool:
            if not enforce_install_token:
                return False
            if not path.startswith("/api/"):
                return False
            if path in _UNAUTHENTICATED_API_PATHS:
                return False
            return True

        def _html_route_needs_onboarding(self, path: str) -> bool:
            """F008 -- True iff this GET should 302 to /onboarding.

            Only HTML routes are gated: API routes have their own
            allow-list. The wizard's own routes are exempt so it can
            drive itself, as is `/settings/broker` (embedded step
            3 of the wizard).

            The gate is off unless ``enforce_onboarding_gate=True``
            was passed to :func:`make_handler`. That keeps single-user
            localhost dev unchanged from the Sprint 0 contract while
            main() flips it on for real deployments.
            """
            if not enforce_onboarding_gate:
                return False
            if path.startswith("/api/"):
                return False
            if path.startswith("/static/") or path.startswith("/assets/"):
                return False
            if path in _ONBOARDING_HTML_ALLOWED:
                return False
            try:
                return onboarding.is_first_visit()
            except (ValueError, RuntimeError):
                return False

        def do_GET(self):  # noqa: N802
            path, _, query = self.path.partition("?")
            params = {}
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                if k:
                    params[k] = v

            if path != "/healthz" and not self._authorized(params):
                self._json({"error": "unauthorized — pass ?token= or "
                                     "Authorization: Bearer"}, 401)
                return

            if self._needs_install_gate(path):
                ok, reason, retry = self._install_gate_pass(path)
                if not ok:
                    if reason == "rate_limited":
                        self._reject_rate_limited(retry)
                        return
                    if reason == "session_expired":
                        self._reject_session_expired()
                        return
                    self._json({"error": "install-token required",
                                "hint": "send X-Bluelock-Token header"}, 401)
                    return

            if path == "/api/auth/status":
                self._json(auth.auth_status())
                return

            # F008 -- onboarding read routes (must precede first-visit
            # redirect so the wizard can load its own state).
            if path == "/api/onboarding/state":
                self._json(onboarding.get_onboarding_state())
                return
            if path in ("/onboarding", "/onboarding/"):
                self._send(ONBOARDING_PAGE.encode(),
                           "text/html; charset=utf-8")
                return
            if path in ("/settings/reset-install",
                        "/settings/reset-install/"):
                self._send(RESET_INSTALL_PAGE.encode(),
                           "text/html; charset=utf-8")
                return

            # F011 -- kill-switches admin page + status API.
            if path in ("/settings/kill-switches",
                        "/settings/kill-switches/"):
                self._send(KILL_SWITCHES_PAGE.encode(),
                           "text/html; charset=utf-8")
                return
            if path == "/api/kill-switches/status":
                self._json({
                    "killed_scopes": kill_switches.list_killed(),
                    "events": kill_switch_admin.recent_events(20),
                    "supported_symbols": list(
                        kill_switches.SUPPORTED_SYMBOLS),
                })
                return

            # F012 -- risk dashboard.
            if path == "/risk":
                self._send(RISK_PAGE.encode(),
                           "text/html; charset=utf-8")
                return
            if path == "/api/risk/state":
                budget = risk_budget.remaining_budget()
                brokers = broker_health.list_health_states()
                self._json({
                    "budget": budget,
                    "brokers": brokers,
                    "exposure": {
                        "open_positions": 0,
                        "notional_usd": 0.0,
                        "note": "Sprint 2 -- live-mode default OFF, no live "
                                "positions; placeholder for future "
                                "integration.",
                    },
                    "as_of": budget.get("as_of"),
                })
                return
            if path == "/api/risk/budgets":
                self._json(risk_budget.load_config())
                return

            # F013 -- approvals queue + live-mode toggle.
            if path in ("/approvals", "/approvals/"):
                self._send(APPROVALS_PAGE.encode(),
                           "text/html; charset=utf-8")
                return
            if path in ("/settings/live-mode", "/settings/live-mode/"):
                self._send(LIVE_MODE_TOGGLE_PAGE.encode(),
                           "text/html; charset=utf-8")
                return
            if path == "/api/approvals/list":
                status = params.get("status", "all")
                try:
                    entries = approval_queue.list_entries(
                        status=status, limit=100)
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                    return
                self._json({"entries": entries})
                return
            if path == "/api/approvals/warning":
                warn_path = (REPO_ROOT / "company" / "legal"
                             / "approval-queue-warning.md")
                try:
                    body = warn_path.read_text(encoding="utf-8")
                except OSError:
                    body = ""
                self._json({"body": body})
                return
            if path == "/api/live-mode/status":
                self._json({"enabled": approval_queue.is_live_mode_enabled()})
                return
            if path == "/api/live-mode/warning":
                warn_path = (REPO_ROOT / "company" / "legal"
                             / "live-mode-warning.md")
                try:
                    body = warn_path.read_text(encoding="utf-8")
                except OSError:
                    body = ""
                self._json({"body": body})
                return

            # F014 -- alerts stream + config + page.
            if path in ("/alerts", "/alerts/"):
                self._send(ALERTS_PAGE.encode(),
                           "text/html; charset=utf-8")
                return
            if path == "/api/alerts/config":
                self._json(alerts_telegram.load_config())
                return
            if path == "/api/alerts/recent":
                self._json({"events": alerts.recent(100)})
                return
            if path == "/api/alerts/stream":
                # Long-lived SSE. Auth gate has already fired above.
                # Ring buffer drains as `initial_history` so a
                # reconnecting client catches up cheaply.
                try:
                    alerts_sse.sse_stream_response(
                        self,
                        initial_history=list(reversed(alerts.recent(100))))
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            # F008 first-visit gate -- HTML routes redirect to
            # /onboarding until the user completes setup. HTTP API
            # routes and the broker wizard (referenced from step 3)
            # stay reachable so the wizard can drive itself.
            if self._html_route_needs_onboarding(path):
                self.send_response(302)
                self.send_header("Location", "/onboarding")
                self.end_headers()
                return

            # F007 -- broker wizard routes
            if path in ("/settings/broker", "/settings/broker/"):
                self._send(BROKER_WIZARD_PAGE.encode(),
                           "text/html; charset=utf-8")
                return
            if path == "/api/broker/list":
                self._json({"aliases": broker_connection.list_aliases()})
                return
            if path == "/api/broker/live-warning":
                warn = _load_live_warning()
                self._send(warn.encode(),
                           "text/plain; charset=utf-8")
                return

            if path in ("/", "/index.html"):
                self._send(HUB_PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/healthz":
                self._json({
                    "status": "ok",
                    "version": PLATFORM_VERSION,
                    "uptime_seconds": round(time.time() - started_at, 1),
                })
            elif path == "/v1":
                self._send(V1_PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/v2":
                self._send(V2_PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/hq":
                self._send(HQ_PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/performance":
                self._send(PERFORMANCE_PAGE.encode(),
                           "text/html; charset=utf-8")
            elif path == "/api/performance/state":
                # F001: performance data plane. Reads v1 daily-log
                # [TRADE CLOSED] lines + v2 shadow-paper close events;
                # returns derived stats + equity curve. Missing data
                # sources degrade to shaped-empty payload -- never a
                # 500.
                self._json(performance.get_state(
                    log_root=log_root, live_dir=live_dir))
            elif path in ("/players", "/players/"):
                # F002: /players index -- ten-striker card grid.
                self._send(PLAYERS_INDEX_PAGE.encode(),
                           "text/html; charset=utf-8")
            elif (pu := _PLAYER_URL_RE.match(path)):
                # F002: /players/<id> detail page. Unknown id -> 404
                # shell that lists the ten valid slugs as links.
                raw = pu.group(1)
                canonical = players.normalize_id(raw)
                if canonical is None:
                    self._send(
                        players_not_found_page(
                            list(players.valid_ids())).encode(),
                        "text/html; charset=utf-8", 404)
                else:
                    row = next((r for r in players.roster_meta()
                                if r["id"] == canonical), None)
                    display_name = (row["name"] if row else canonical)
                    self._send(
                        player_detail_page(canonical, display_name).encode(),
                        "text/html; charset=utf-8")
            elif path in ("/api/players/list", "/api/players"):
                # F002: index API -- ten-row roster payload.
                self._json(players.list_state(live_dir=live_dir))
            elif (pa := _PLAYER_API_RE.match(path)):
                # F002: detail API -- one striker's full payload.
                raw = pa.group(1)
                canonical = players.normalize_id(raw)
                if canonical is None:
                    self._json({"error": "unknown striker",
                                "valid_ids": list(players.valid_ids())}, 404)
                else:
                    payload = players.get_player(
                        canonical, live_dir=live_dir)
                    if payload is None:
                        self._json({"error": "unknown striker"}, 404)
                    else:
                        self._json(payload)
            elif path == "/research":
                # F003: /research verdict timeline (CPO-gated).
                self._send(RESEARCH_PAGE.encode(),
                           "text/html; charset=utf-8")
            elif path == "/api/research/verdicts":
                # F003: CPO-gated allow-list of published verdicts.
                # Backend parses every canonical REPORT.md on tape but
                # only emits entries the publication_manifest.json
                # explicitly allows. Missing research repo -> friendly
                # source_exists=False payload, never a 500.
                self._json(research.get_state(
                    research_root=derived_research_root,
                    manifest_path=research_manifest_path))
            elif path == "/api/hq/state":
                # HQ dashboard state -- reads company/ledger/company_state.json
                # (or company_ledger_path override in tests). Missing /
                # malformed ledger returns a well-shaped skeleton payload
                # with meta.unconfigured=True so the dashboard renders a
                # friendly "not configured" state instead of a 500.
                self._json(hq.hq_state(ledger_path=company_ledger_path))
            elif path == "/api/v1/status":
                self._json(live_status.collect_status(log_root, repo_root))
            elif path == "/api/v2/matches":
                self._json({
                    "reviews_dir": str(reviews_dir),
                    "matches": squad_events.list_matches(reviews_dir),
                })
            elif (lm := _LIVE_RE.match(path)):
                # Live tail of the paper loop's output dir. Same parser
                # and schema as replay caches; the mtime cache picks up
                # appends, so polling a cursor here IS the live stream.
                kind = lm.group(1)
                if kind == "status":
                    self._json(paper_loop.live_status(live_dir)
                               if live_dir else
                               {"dir": None, "exists": False,
                                "running": False,
                                "error": "no live dir configured"})
                    return
                if kind == "workspace":
                    # Latest workspace snapshot -- the "what is the squad
                    # thinking right now" panel on /v2 LIVE. Returns
                    # {exists:False, thoughts:[]} when no snapshot yet
                    # (fresh dir), matching paper_loop.live_workspace.
                    self._json(paper_loop.live_workspace(live_dir)
                               if live_dir else
                               {"exists": False, "thoughts": []})
                    return
                if live_dir is None or not live_dir.is_dir():
                    self._json({"error": "live dir not found"}, 404)
                    return
                if kind == "summary":
                    _, summary = squad_events.build_timeline(live_dir)
                    self._json(summary)
                elif kind.startswith("event/"):
                    detail = squad_events.get_event_detail(
                        live_dir, int(lm.group(2)))
                    if detail is None:
                        self._json({"error": "event index out of range"}, 404)
                    else:
                        self._json(detail)
                else:
                    try:
                        cursor = int(params.get("cursor", "0"))
                        limit = int(params.get("limit", "500"))
                    except ValueError:
                        self._json({"error": "bad cursor/limit"}, 400)
                        return
                    self._json(squad_events.get_events(live_dir, cursor, limit))
            elif (m := _MATCH_RE.match(path)):
                match_id, kind = m.group(1), m.group(2)
                cache_dir = reviews_dir / match_id
                # The regex forbids path separators, but resolve-and-check
                # anyway so the server can never read outside reviews_dir.
                if (not cache_dir.resolve().is_relative_to(reviews_dir.resolve())
                        or not cache_dir.is_dir()):
                    self._json({"error": "unknown match"}, 404)
                    return
                if kind == "summary":
                    _, summary = squad_events.build_timeline(cache_dir)
                    self._json(summary)
                elif kind.startswith("event/"):
                    detail = squad_events.get_event_detail(
                        cache_dir, int(m.group(3)))
                    if detail is None:
                        self._json({"error": "event index out of range"}, 404)
                    else:
                        self._json(detail)
                else:
                    try:
                        cursor = int(params.get("cursor", "0"))
                        limit = int(params.get("limit", "500"))
                    except ValueError:
                        self._json({"error": "bad cursor/limit"}, 400)
                        return
                    self._json(squad_events.get_events(cache_dir, cursor, limit))
            else:
                self._send(b"not found", "text/plain", 404)

        def _read_body_json(self) -> dict | None:
            """Best-effort JSON body reader. Returns None on any error."""
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                return None
            if length <= 0 or length > 65536:
                return None
            try:
                raw = self.rfile.read(length)
            except OSError:
                return None
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                return None
            return parsed if isinstance(parsed, dict) else None

        def do_POST(self):  # noqa: N802 -- F007 broker APIs
            path, _, query = self.path.partition("?")
            params = {}
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                if k:
                    params[k] = v

            if not self._authorized(params):
                self._json({"error": "unauthorized"}, 401)
                return

            if self._needs_install_gate(path):
                ok, reason, retry = self._install_gate_pass(path)
                if not ok:
                    if reason == "rate_limited":
                        self._reject_rate_limited(retry)
                        return
                    if reason == "session_expired":
                        self._reject_session_expired()
                        return
                    self._json({"error": "install-token required"}, 401)
                    return

            # F009 -- token rotation. Requires a currently-valid install
            # token in the request; on success a fresh token is minted
            # and returned once (the client displays it, stores it).
            if path == "/api/auth/rotate":
                try:
                    new_token = auth.rotate_install_token()
                except RuntimeError as exc:
                    self._json({"success": False, "error": str(exc)}, 400)
                    return
                # Reset the rate-limit bucket for the OLD fingerprint;
                # the new fingerprint starts with a full bucket lazily.
                rate_limiter.reset()
                self._json({
                    "success": True,
                    "install_token": new_token,
                    "install_fingerprint": auth.install_token_fingerprint(
                        new_token),
                })
                return

            # F008 -- onboarding write routes (exempt from install
            # gate; they run before setup completes).
            if path == "/api/onboarding/state":
                # Idempotent step-persistence -- the wizard sends this
                # on every showStep() call so a reload resumes.
                step = params.get("step")
                if step:
                    try:
                        onboarding.set_current_step(step)
                    except ValueError:
                        pass
                self._json({"ok": True})
                return
            if path == "/api/onboarding/passphrase":
                body = self._read_body_json() or {}
                pw = body.get("passphrase", "")
                skipped = bool(body.get("skipped"))
                ka = credentials.is_keyring_available() if skipped \
                    else None
                ok, msg = onboarding.validate_passphrase(
                    pw, keyring_available=ka)
                if ok and pw:
                    credentials.set_encrypted_file_passphrase(pw)
                self._json({"ok": ok, "message": msg})
                return
            if path == "/api/onboarding/pairs":
                body = self._read_body_json() or {}
                try:
                    onboarding.set_default_pairs(body.get("pairs", []))
                except ValueError as exc:
                    self._json({"ok": False, "message": str(exc)}, 400)
                    return
                self._json({"ok": True,
                            "pairs": onboarding.get_default_pairs()})
                return
            if path == "/api/onboarding/complete":
                ok = onboarding.mark_setup_complete()
                self._json({"ok": ok})
                return
            if path == "/api/onboarding/reset":
                ok = onboarding.reset_install()
                self._json({"ok": ok})
                return

            # F011 -- kill-switch admin write path. Every activate /
            # clear appends to the JSONL audit log inside the module.
            if path == "/api/kill-switches/activate":
                body = self._read_body_json() or {}
                symbol = body.get("symbol")
                sym = None if symbol in (None, "", "GLOBAL") else str(symbol)
                try:
                    kill_switch_admin.activate_kill(
                        symbol=sym,
                        reason=str(body.get("reason", "")),
                        by=str(body.get("by", "user")))
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
                    return
                self._json({"ok": True})
                return
            if path == "/api/kill-switches/clear":
                body = self._read_body_json() or {}
                symbol = body.get("symbol")
                sym = None if symbol in (None, "", "GLOBAL") else str(symbol)
                try:
                    kill_switch_admin.clear_kill(symbol=sym)
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
                    return
                self._json({"ok": True})
                return

            # F012 -- risk budget write path (auth-gated).
            if path == "/api/risk/budgets":
                body = self._read_body_json() or {}
                if not isinstance(body, dict):
                    self._json({"ok": False,
                                "error": "expected JSON object"}, 400)
                    return
                ok = risk_budget.save_config(body)
                if ok:
                    self._json({"ok": True,
                                "budgets": risk_budget.load_config()})
                else:
                    self._json({"ok": False,
                                "error": "unable to write config"}, 500)
                return

            # F013 -- approvals + live-mode toggle write path (auth-gated).
            m = _APPROVAL_ACTION_RE.match(path)
            if m is not None:
                approval_id, action = m.group(1), m.group(2)
                body = self._read_body_json() or {}
                if action == "approve":
                    ok = approval_queue.approve(approval_id, by="user")
                    self._json({"ok": ok})
                    return
                ok = approval_queue.reject(
                    approval_id, str(body.get("reason", "")), by="user")
                self._json({"ok": ok})
                return
            if path == "/api/approvals/submit":
                # Internal-only endpoint. Sprint 2 does NOT call this
                # from any live pathway (D065 invariant); the internal
                # token is required + empty token fails closed.
                cfg_now = load_config(REPO_ROOT)
                internal_token = (cfg_now.get("internal", {})
                                  .get("token") or "")
                header_token = self.headers.get("X-Bluelock-Internal-Token", "")
                if (not internal_token
                        or not auth.constant_time_equal(
                            internal_token, header_token)):
                    self._json({"ok": False,
                                "error": "internal-token required"}, 401)
                    return
                body = self._read_body_json() or {}
                try:
                    approval_id = approval_queue.submit(body)
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
                    return
                self._json({"ok": True, "id": approval_id})
                return
            if path == "/api/live-mode/enable":
                body = self._read_body_json() or {}
                ok, reason = approval_queue.enable_ceremony(
                    acknowledged=bool(body.get("acknowledged", False)),
                    confirmation=str(body.get("confirmation", "")))
                if not ok:
                    self._json({"ok": False, "error": reason}, 400)
                    return
                self._json({"ok": True,
                            "enabled": approval_queue.is_live_mode_enabled()})
                return
            if path == "/api/live-mode/disable":
                ok = approval_queue.disable()
                self._json({"ok": ok,
                            "enabled": approval_queue.is_live_mode_enabled()})
                return

            # F014 -- alerts config write path + test-event publisher.
            if path == "/api/alerts/config":
                body = self._read_body_json() or {}
                if not isinstance(body, dict):
                    self._json({"ok": False,
                                "error": "expected JSON object"}, 400)
                    return
                cfg_now = load_config(REPO_ROOT)
                bot_token = str(cfg_now.get("telegram", {})
                                .get("bot_token", "") or "")
                chat_id = str(cfg_now.get("telegram", {})
                              .get("chat_id", "") or "")
                alerts_telegram.configure(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    per_event=body.get("per_event") or {},
                    enabled=bool(body.get("enabled", False)))
                alerts_telegram.start()
                self._json({"ok": True,
                            "config": alerts_telegram.load_config()})
                return
            if path == "/api/alerts/test":
                event = alerts.publish(
                    "trade_fill",
                    {"test": True,
                     "note": "synthetic event from POST /api/alerts/test"})
                self._json({"ok": True, "event": event})
                return

            if path == "/api/broker/test-connection":
                body = self._read_body_json() or {}
                result = broker_connection.test_connection(
                    login=body.get("login"),
                    password=body.get("password"),
                    server=body.get("server"))
                # Scrub password from ever hitting the response even
                # accidentally (test_connection already omits it).
                result.pop("password", None)
                self._json(result)
                return
            if path == "/api/broker/save":
                body = self._read_body_json() or {}
                try:
                    ok = broker_connection.save_credentials(
                        alias=body.get("alias", ""),
                        login=body.get("login"),
                        password=body.get("password", ""),
                        server=body.get("server", ""),
                        account_type=body.get("account_type", "demo"))
                except ValueError as exc:
                    self._json({"success": False, "error": str(exc)}, 400)
                    return
                except TypeError as exc:
                    self._json({"success": False, "error": str(exc)}, 400)
                    return
                self._json({"success": ok})
                return

            self._send(b"not found", "text/plain", 404)

        def do_DELETE(self):  # noqa: N802 -- F007 broker APIs
            path, _, query = self.path.partition("?")
            params = {}
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                if k:
                    params[k] = v

            if not self._authorized(params):
                self._json({"error": "unauthorized"}, 401)
                return
            if self._needs_install_gate(path):
                ok, reason, retry = self._install_gate_pass(path)
                if not ok:
                    if reason == "rate_limited":
                        self._reject_rate_limited(retry)
                        return
                    if reason == "session_expired":
                        self._reject_session_expired()
                        return
                    self._json({"error": "install-token required"}, 401)
                    return

            m = _BROKER_ALIAS_RE.match(path)
            if m:
                alias = m.group(1)
                try:
                    ok = broker_connection.delete_credentials(alias)
                except ValueError as exc:
                    self._json({"success": False, "error": str(exc)}, 400)
                    return
                self._json({"success": ok})
                return

            self._send(b"not found", "text/plain", 404)

        def log_message(self, fmt, *args):  # quiet server
            pass

    return Handler


def _load_live_warning() -> str:
    """Read the F007 live-broker warning text from disk. Missing file
    falls back to a minimal safe message rather than raising."""
    try:
        return _LIVE_WARNING_PATH.read_text(encoding="utf-8")
    except OSError:
        return ("Live trading uses real money and can lose real money. "
                "Only continue if you have read the docs and are certain.")


def main() -> None:
    # Defaults come from platform.toml (if present); flags override.
    cfg = load_config(REPO_ROOT)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log-root", type=Path, default=cfg["log_root"],
                    help="the live agent's log root (v1 page)")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT,
                    help="where the global kill_switch file lives")
    ap.add_argument("--research-reviews", type=Path,
                    default=cfg["research_reviews"],
                    help="M001 reviews dir holding g7_replay_cache_* (v2 page)")
    ap.add_argument("--live-dir", type=Path, default=cfg["live_dir"],
                    help="paper-loop output dir tailed by /api/v2/live/*")
    ap.add_argument("--host", default=cfg["host"],
                    help="bind address (0.0.0.0 to view from another machine)")
    ap.add_argument("--port", type=int, default=cfg["port"])
    ap.add_argument("--auth-token", default=cfg["auth_token"],
                    help="require this token on all routes when binding "
                         "non-localhost (?token=, Bearer header, or the "
                         "cookie set on first tokened visit)")
    ap.add_argument("--company-ledger", type=Path, default=None,
                    help="override path to company/ledger/company_state.json "
                         "(the /hq dashboard's data source); defaults to the "
                         "shipped ledger under the repo root")
    args = ap.parse_args()

    # Auth only bites on non-localhost binds; local browsing stays open.
    localhost = args.host in ("127.0.0.1", "localhost", "::1")
    effective_token = None if localhost else args.auth_token
    if not localhost and not args.auth_token:
        print("WARNING: binding non-localhost without --auth-token — "
              "anyone on the network can read the dashboards")

    # F006 (per D048 + D052): mount the log-redaction filter early so any
    # accidental log line goes through it before hitting stdout / stderr.
    # Enforce the install-token gate on /api/* only for non-localhost
    # binds; localhost single-user dev stays open per D052.
    auth.install_redacting_filter("")
    auth.install_redacting_filter("agent.platform")

    # F009 -- rate limiter + session expiry config wiring. Both defaults
    # match the module-level defaults; explicit config wins.
    rl_cfg = cfg.get("rate_limit", {})
    rate_limiter.set_config(
        requests_per_minute=rl_cfg.get("requests_per_minute", 60),
        capacity=rl_cfg.get("capacity"),
        refill_per_sec=rl_cfg.get("refill_per_sec"),
    )
    expiry_days = int(cfg.get("session", {}).get("expiry_days", 7))
    auth.set_session_expiry_seconds(expiry_days * 24 * 3600)

    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(args.log_root, args.repo_root, args.research_reviews,
                     live_dir=args.live_dir, auth_token=effective_token,
                     company_ledger_path=args.company_ledger,
                     enforce_install_token=not localhost,
                     enforce_onboarding_gate=not localhost),
    )
    if effective_token:
        print("Auth: token required on all routes except /healthz")
    if not localhost:
        print("F006 install-token gate: enabled on /api/* "
              "(bring your token via X-Bluelock-Token / Bearer / cookie / ?token=)")
        print("F008 onboarding gate: enabled -- HTML routes redirect "
              "to /onboarding until setup completes")
    print(f"Platform v{PLATFORM_VERSION} on http://{args.host}:{args.port}")
    print(f"  v1 log root:        {args.log_root}")
    print(f"  v2 research reviews: {args.research_reviews} "
          f"({'found' if args.research_reviews.exists() else 'MISSING — v2 will list no matches'})")
    print(f"  v2 live dir:        {args.live_dir} "
          f"({'found' if args.live_dir.is_dir() else 'not created yet — LIVE mode idle'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
