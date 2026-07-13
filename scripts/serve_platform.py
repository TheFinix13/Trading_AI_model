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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.platform import live_status, squad_events  # noqa: E402
from agent.platform.pages import HUB_PAGE, V1_PAGE, V2_PAGE  # noqa: E402

DEFAULT_RESEARCH_REVIEWS = (
    REPO_ROOT.parent / "finance-research-experiments" / "programs"
    / "M001_multi_agent_ensemble" / "reviews"
)

_MATCH_RE = re.compile(r"^/api/v2/match/([A-Za-z0-9_.-]+)/(summary|events)$")


def make_handler(log_root: Path, repo_root: Path, reviews_dir: Path):
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log-root", type=Path,
                    default=Path.home() / "Documents" / "TradingAgentLogs",
                    help="the live agent's log root (v1 page)")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT,
                    help="where the global kill_switch file lives")
    ap.add_argument("--research-reviews", type=Path,
                    default=DEFAULT_RESEARCH_REVIEWS,
                    help="M001 reviews dir holding g7_replay_cache_* (v2 page)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (0.0.0.0 to view from another machine)")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(args.log_root, args.repo_root, args.research_reviews),
    )
    print(f"Platform on http://{args.host}:{args.port}")
    print(f"  v1 log root:        {args.log_root}")
    print(f"  v2 research reviews: {args.research_reviews} "
          f"({'found' if args.research_reviews.exists() else 'MISSING — v2 will list no matches'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
