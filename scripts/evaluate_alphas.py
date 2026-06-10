"""Per-alpha scorecards on the locked dev span (v2).

Thin wrapper around `scripts/evaluate.py` — kept as a separate entry point so
the v2 ablation grid (224 cells) can be wired in here without disturbing the
single-cell evaluation flow.
"""
from __future__ import annotations

from scripts.evaluate import main

if __name__ == "__main__":
    main()
