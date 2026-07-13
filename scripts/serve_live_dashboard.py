"""Live agent dashboard — real-time web view of the running zones agent (v1).

Thin v1-only variant of ``scripts/serve_platform.py`` (which adds the
hub and the /v2 squad pitch). Both share the same read-only collectors
in ``agent/platform/live_status.py``; prefer ``serve_platform.py`` for
day-to-day use.

Serves a self-refreshing dark-theme page showing, per symbol, what the
live agent is actually doing on the market RIGHT NOW:

* aliveness (last log activity vs the 15-min heartbeat contract)
* open positions with entry / stops / excursion from ``state.json``
* day PnL, daily-DD halt state, post-loss guard posture
* kill-switch status (per-symbol + global)
* a merged decision feed — signals evaluated, rejections with reasons,
  guard blocks, trade opens/closes, ladder events — parsed from the
  daily logs the agent already writes. No agent code is touched; this
  server is strictly READ-ONLY over the log root.

Run (VM or Mac):

    python scripts/serve_live_dashboard.py \
        --log-root ~/Documents/TradingAgentLogs --port 8787

Then open http://127.0.0.1:8787 . Use ``--host 0.0.0.0`` to view the
page from another machine (e.g. the Mac browsing to the VM's IP).

stdlib only — no new dependencies on the VM.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.platform.live_status import collect_status  # noqa: E402
from agent.platform.pages import V1_PAGE  # noqa: E402


def make_handler(log_root: Path, repo_root: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            # /api/status kept for backward compatibility with the
            # original v1-only page; /api/v1/status matches the platform.
            if self.path.startswith(("/api/status", "/api/v1/status")):
                body = json.dumps(collect_status(log_root, repo_root)).encode()
                ctype = "application/json"
            elif self.path in ("/", "/index.html", "/v1"):
                body = V1_PAGE.encode()
                ctype = "text/html; charset=utf-8"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # quiet server
            pass

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log-root", type=Path,
                    default=Path.home() / "Documents" / "TradingAgentLogs")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT,
                    help="where the global kill_switch file lives")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (0.0.0.0 to view from another machine)")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port),
                                 make_handler(args.log_root, args.repo_root))
    print(f"Live dashboard on http://{args.host}:{args.port} "
          f"(log root: {args.log_root})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
