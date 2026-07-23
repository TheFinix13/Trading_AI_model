"""F014 -- Telegram bridge for the alerts bus.

Sends a Telegram message on each event whose type is enabled in the
`[alerts.telegram]` config block. Reuses the existing `[telegram]`
`bot_token` / `chat_id` from `platform.toml` -- F014 does NOT add a
new secret.

Fail-closed: any missing bot_token / chat_id, or a disabled config
block, short-circuits `send()` and returns False. Real Telegram
calls are gated on `alerts_telegram.is_enabled()`; tests mock
`httpx.post`.
"""
from __future__ import annotations

import logging
import threading
from copy import deepcopy

from agent.platform import alerts

TELEGRAM_API_BASE: str = "https://api.telegram.org/bot"

_DEFAULT_PER_EVENT: dict[str, bool] = {
    "trade_fill": True,
    "stop_hit": True,
    "kill_switch_trip": True,
    "risk_budget_breach": True,
    "approval_submitted": False,
    "platform_down": True,
    # F017 -- an ops alarm is exactly what Telegram is for.
    "watchdog_alert": True,
}

_LOG = logging.getLogger(__name__)

_LOCK = threading.RLock()
_STATE: dict = {
    "enabled": False,
    "bot_token": "",
    "chat_id": "",
    "per_event": dict(_DEFAULT_PER_EVENT),
    "subscription_id": None,
}


def configure(bot_token: str, chat_id: str,
              per_event: dict[str, bool] | None = None,
              enabled: bool = True) -> None:
    """Set the bridge config in-place. Idempotent."""
    with _LOCK:
        _STATE["bot_token"] = str(bot_token or "")
        _STATE["chat_id"] = str(chat_id or "")
        # Merge over defaults so an override for a subset is fine.
        merged = dict(_DEFAULT_PER_EVENT)
        for k, v in (per_event or {}).items():
            if k in _DEFAULT_PER_EVENT:
                merged[k] = bool(v)
        _STATE["per_event"] = merged
        _STATE["enabled"] = bool(enabled)


def load_config() -> dict:
    """Snapshot the current config (shape mirrors [alerts.telegram])."""
    with _LOCK:
        return {
            "enabled": bool(_STATE["enabled"]),
            "bot_token_configured": bool(_STATE["bot_token"]),
            "chat_id_configured": bool(_STATE["chat_id"]),
            "per_event": dict(_STATE["per_event"]),
        }


def is_enabled() -> bool:
    """True iff the config block is enabled AND we have both a
    bot_token and a chat_id."""
    with _LOCK:
        return bool(
            _STATE["enabled"]
            and _STATE["bot_token"]
            and _STATE["chat_id"]
        )


def _format_message(event: dict) -> str:
    ev_type = event.get("type", "unknown")
    payload = event.get("payload", {})
    lines = [f"[{ev_type}] {event.get('ts', '')}"]
    for k, v in payload.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def send(event: dict, client=None) -> bool:
    """Send a single event via Telegram. Returns True on success."""
    if not is_enabled():
        return False
    ev_type = event.get("type", "")
    with _LOCK:
        per_event = dict(_STATE["per_event"])
        bot_token = _STATE["bot_token"]
        chat_id = _STATE["chat_id"]
    if not per_event.get(ev_type, False):
        return False
    text = _format_message(event)
    payload = {"chat_id": chat_id, "text": text}
    url = f"{TELEGRAM_API_BASE}{bot_token}/sendMessage"
    try:
        if client is None:
            import httpx  # local import so the module loads without httpx
            client = httpx
        resp = client.post(url, json=payload, timeout=5.0)
        ok = getattr(resp, "status_code", 500) == 200
        return bool(ok)
    except Exception:
        _LOG.exception("alerts_telegram: failed to post event")
        return False


def start(client=None) -> str | None:
    """Attach a subscription that routes bus events to Telegram.

    Returns the subscription id (or None if disabled). Idempotent --
    calling twice replaces the previous subscription."""
    stop()
    if not is_enabled():
        return None

    def _on_event(ev: dict) -> None:
        send(ev, client=client)

    sub_id = alerts.subscribe(_on_event)
    with _LOCK:
        _STATE["subscription_id"] = sub_id
    return sub_id


def stop() -> None:
    with _LOCK:
        sub_id = _STATE.get("subscription_id")
        _STATE["subscription_id"] = None
    if sub_id:
        alerts.unsubscribe(sub_id)


def reset() -> None:  # claim-exempt: test-only
    stop()
    with _LOCK:
        _STATE["enabled"] = False
        _STATE["bot_token"] = ""
        _STATE["chat_id"] = ""
        _STATE["per_event"] = dict(_DEFAULT_PER_EVENT)


def snapshot() -> dict:  # claim-exempt: test-only internal state
    with _LOCK:
        return deepcopy(_STATE)


__all__ = [
    "TELEGRAM_API_BASE",
    "configure",
    "load_config",
    "is_enabled",
    "send",
    "start",
    "stop",
    "reset",
]
