"""Top-level CLI dispatcher: `eurusd-agent <subcommand>`."""
from __future__ import annotations

import importlib
import sys

COMMANDS = {
    "download": "scripts.download_data",
    "backtest": "scripts.run_backtest",
    "train": "scripts.train_model",
    "gate": "scripts.check_gate",
    "live": "scripts.run_live",
    "paper": "scripts.run_live",
    "retrain": "scripts.weekly_retrain",
    "sanity": "scripts.visual_sanity",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: eurusd-agent <command> [args...]")
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
