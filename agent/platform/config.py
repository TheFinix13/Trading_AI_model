"""platform.toml loader — shared defaults for the platform server + tools.

Precedence: built-in defaults < ``platform.toml`` at the repo root <
CLI flags (the scripts pass ``default=cfg[...]`` to argparse, so an
explicit flag always wins). The file is optional; a missing or broken
file silently falls back to defaults so the server always starts.

Example file: ``platform.toml.example`` at the repo root.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_NAME = "platform.toml"


def _defaults(repo_root: Path) -> dict:
    return {
        "log_root": Path.home() / "Documents" / "TradingAgentLogs",
        "research_reviews": (repo_root.parent / "finance-research-experiments"
                             / "programs" / "M001_multi_agent_ensemble"
                             / "reviews"),
        "live_dir": None,   # derived from log_root below when unset
        "host": "127.0.0.1",
        "port": 8787,
        "auth_token": None,
        # Dedicated v2 squad Telegram bot ([telegram] table). Empty values
        # here fall back to SQUAD_TELEGRAM_BOT_TOKEN / SQUAD_TELEGRAM_CHAT_ID
        # env vars in agent.platform.squad_notify (toml wins per key).
        "telegram": {"bot_token": "", "chat_id": "", "summary_every": 10},
    }


def load_config(repo_root: Path, path: Path | None = None) -> dict:
    """Merged config dict. ``path`` overrides the default file location
    (used by tests)."""
    cfg = _defaults(repo_root)
    cfg_path = path or (repo_root / CONFIG_NAME)
    raw: dict = {}
    if cfg_path.is_file():
        try:
            raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            raw = {}
    for key in ("log_root", "research_reviews", "live_dir"):
        if raw.get(key):
            cfg[key] = Path(str(raw[key])).expanduser()
    if raw.get("host"):
        cfg["host"] = str(raw["host"])
    if raw.get("port"):
        try:
            cfg["port"] = int(raw["port"])
        except (TypeError, ValueError):
            pass
    if raw.get("auth_token"):
        cfg["auth_token"] = str(raw["auth_token"])
    tg = raw.get("telegram")
    if isinstance(tg, dict):
        for key in ("bot_token", "chat_id"):
            if tg.get(key):
                cfg["telegram"][key] = str(tg[key])
        if tg.get("summary_every"):
            try:
                cfg["telegram"]["summary_every"] = int(tg["summary_every"])
            except (TypeError, ValueError):
                pass
    if cfg["live_dir"] is None:
        cfg["live_dir"] = Path(cfg["log_root"]) / "squad_live"
    return cfg
