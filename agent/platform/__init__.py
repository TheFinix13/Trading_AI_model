"""Platform web UI (next-gen branch) — live v1 view + squad v2 pitch.

This package backs ``scripts/serve_platform.py``. It is strictly
READ-ONLY over two data planes:

* v1 — the running zones agent's own log root (``state.json``, daily
  logs, kill files). Nothing here can affect trading.
* v2 — M001 squad replay artifacts (JSONL files) produced by the
  research repo. Only artifact FILES are read; research code is never
  imported (hard workspace rule).
"""
