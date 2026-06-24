"""Top-level CLI dispatcher for v2.

Most v1 subcommands were burned with their backing scripts in the v2 reset
(training, retraining, walk-forward, confluence optimisation, ranking,
visual-sanity, journal-query …). What survives:

  download   — fetch / refresh OHLC parquet for a symbol
  evaluate   — run the v2 evaluation harness over the 224-cell ablation grid
  alphas     — per-alpha scorecards on the locked OOS window
  live       — start the live signal loop (paper / Exness / MT5)
  paper      — alias for ``live`` with ``--broker paper``
  smoke      — quick end-to-end sanity check
"""
from __future__ import annotations

import importlib
import sys

COMMANDS = {
    "download": "scripts.download_data",
    "evaluate": "scripts.evaluate",
    "alphas": "scripts.evaluate_alphas",
    "live": "scripts.run_live",
    "paper": "scripts.run_live",
    "smoke": "scripts.smoke_test",
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: multi-pair-agent <command> [args...]")
        print("Commands:")
        for k in COMMANDS:
            print(f"  {k}")
        return
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
    sys.argv = [cmd] + sys.argv[2:]
    mod = importlib.import_module(COMMANDS[cmd])
    mod.main()


if __name__ == "__main__":
    main()
