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

from agent.platform import live_status, paper_loop, squad_events  # noqa: E402
from agent.platform.config import load_config  # noqa: E402
from agent.platform.pages import HUB_PAGE, V1_PAGE, V2_PAGE  # noqa: E402

PLATFORM_VERSION = "0.2.0"

_MATCH_RE = re.compile(
    r"^/api/v2/match/([A-Za-z0-9_.-]+)/(summary|events|event/(\d+))$")
_LIVE_RE = re.compile(r"^/api/v2/live/(summary|events|status|event/(\d+))$")


def make_handler(log_root: Path, repo_root: Path, reviews_dir: Path,
                 live_dir: Path | None = None):
    started_at = time.time()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, code: int = 200) -> None:
            self._send(json.dumps(payload).encode(), "application/json", code)

        def do_GET(self):  # noqa: N802
            path, _, query = self.path.partition("?")
            params = {}
            for pair in query.split("&"):
                k, _, v = pair.partition("=")
                if k:
                    params[k] = v

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

        def log_message(self, fmt, *args):  # quiet server
            pass

    return Handler


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
    args = ap.parse_args()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(args.log_root, args.repo_root, args.research_reviews,
                     live_dir=args.live_dir),
    )
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
