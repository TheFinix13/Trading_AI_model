"""F007 -- MT5 broker connection wizard backend.

Public API::

    is_mt5_available()                                  -> bool
    test_connection(login, password, server, timeout)   -> ConnectionResult
    save_credentials(alias, login, password, server, account_type) -> bool
    load_credentials(alias)                             -> dict | None
    list_aliases()                                      -> list[dict]
    delete_credentials(alias)                           -> bool
    reset_rate_limiter()                                -> None
    ALLOWED_SERVERS                                     -- module constant

Security invariants (pinned by tests/security/test_broker_connection.py):

1. **Password never appears in any log line, response body, or JSON
   payload emitted by this module.** Only ``credentials.store_secret``
   handles it, and that module already scrubs.
2. **Server URL enforced against the ALLOWED_SERVERS allow-list**;
   anything else is refused before the network is touched.
3. **Rate-limit: 5 test_connection attempts per minute** per process
   (single-user install per D052). The 6th attempt returns 429 with
   no MT5 call.
4. **MT5 is Windows-only**; on macOS / Linux `is_mt5_available()`
   returns False and `test_connection` short-circuits with a friendly
   payload -- no ImportError leaked to the caller.
"""
from __future__ import annotations

import collections
import ipaddress
import json
import logging
import re
import sys
import time
from typing import Any

from agent.platform import credentials

logger = logging.getLogger(__name__)

BROKER_NAMESPACE = "broker_mt5"

# Allow-listed MT5 server patterns. Servers are user-provided strings
# like "Exness-MT5Trial7" -- we enforce the prefix. Refresh with a new
# vendor requires a decision-log entry.
ALLOWED_SERVERS: tuple[str, ...] = (
    "Exness-",
    "MetaQuotes-",
    "ICMarketsSC-",
    "ICMarkets-",
    "Pepperstone-",
    "FTMO-Server",
    "OANDA-",
    "Deriv-",
    "XM-",
    "AdmiralMarkets-",
    "Demo-",
    "Sandbox-",
)

_ACCOUNT_TYPES: tuple[str, ...] = ("demo", "live", "unknown")

_MAX_LOGIN = 20  # decimal digits
_LOGIN_RE = re.compile(r"^\d{1,20}$")
_ALIAS_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
_SERVER_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

# Rate limiter -- one deque of past-attempt timestamps.
_RATE_LIMIT_WINDOW_SEC = 60.0
_RATE_LIMIT_MAX_ATTEMPTS = 5
_rate_attempts: collections.deque[float] = collections.deque()


def is_mt5_available() -> bool:
    """Whether the ``MetaTrader5`` package is importable on this host.

    MT5 client is Windows-only. We defer the import so tests + macOS
    dev sessions never crash on module load.
    """
    if sys.platform != "win32":
        return False
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        return False
    return True


def reset_rate_limiter() -> None:
    """Test helper -- clear the rate-limit window."""
    _rate_attempts.clear()


def _rate_limit_check() -> bool:
    """Returns True when a fresh attempt is allowed; False when the
    caller has hit the 5-per-60-sec ceiling.
    """
    now = time.monotonic()
    while _rate_attempts and (now - _rate_attempts[0]) > _RATE_LIMIT_WINDOW_SEC:
        _rate_attempts.popleft()
    if len(_rate_attempts) >= _RATE_LIMIT_MAX_ATTEMPTS:
        return False
    _rate_attempts.append(now)
    return True


def _validate_login(login: Any) -> str:
    """Normalise + validate the MT5 login field. Accepts int or digit-str.

    Rejects empty / non-numeric / oversized. Returns a string
    representation for downstream storage.
    """
    if isinstance(login, int):
        login = str(login)
    if not isinstance(login, str):
        raise ValueError("login must be a numeric MT5 login")
    login = login.strip()
    if not _LOGIN_RE.match(login):
        raise ValueError("login must be 1..20 decimal digits")
    return login


def _validate_password(password: Any) -> str:
    """Basic validation only -- content passes through to
    ``credentials.store_secret`` which does its own sanitisation.
    Never logs the value.
    """
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    if not password:
        raise ValueError("password must be non-empty")
    if len(password) > 512:
        raise ValueError("password exceeds 512 chars")
    return password


def _validate_server(server: Any) -> str:
    """Enforce allow-list of MT5 server prefixes."""
    if not isinstance(server, str) or not _SERVER_RE.match(server):
        raise ValueError("server must be 1..64 chars of [A-Za-z0-9_.-]")
    # Try to catch IP-literal payloads (defence-in-depth even though
    # the regex would already reject `:` and `/`).
    try:
        ipaddress.ip_address(server)
        raise ValueError("server must be a broker name, not an IP address")
    except ValueError:
        pass  # non-IP is exactly what we want
    for prefix in ALLOWED_SERVERS:
        if server.startswith(prefix):
            return server
    raise ValueError(f"server {server!r} not on allow-list "
                     f"({', '.join(ALLOWED_SERVERS)})")


def _validate_alias(alias: Any) -> str:
    if not isinstance(alias, str) or not _ALIAS_RE.match(alias):
        raise ValueError("alias must be 1..64 chars of [A-Za-z0-9_.-]")
    if ".." in alias or alias.startswith(".") or alias.endswith("."):
        raise ValueError("alias must not contain path-traversal patterns")
    return alias


def _validate_account_type(account_type: Any) -> str:
    if account_type not in _ACCOUNT_TYPES:
        raise ValueError(
            f"account_type must be one of {_ACCOUNT_TYPES}, got "
            f"{account_type!r}")
    return account_type


def test_connection(login: Any,
                    password: Any,
                    server: Any,
                    timeout: float = 10.0) -> dict:
    """Attempt a login to the MT5 client and return the outcome.

    On macOS / Linux where MT5 is not available, returns a friendly
    ``success=False`` payload without touching the network.

    Password never appears in the response, never in a log line.
    Failed attempts log the login + server + error_code -- NOT the
    password.
    """
    try:
        login_str = _validate_login(login)
        _validate_password(password)  # only validates -- value discarded
        server_str = _validate_server(server)
    except ValueError as exc:
        logger.info("broker.test_connection outcome=validation_error "
                    "reason=%s", exc)
        return {
            "success": False,
            "error_code": None,
            "error_message": str(exc),
            "account_type": "unknown",
            "account_number": None,
            "balance_currency": None,
            "server": server if isinstance(server, str) else None,
        }

    if not _rate_limit_check():
        logger.info("broker.test_connection outcome=rate_limited "
                    "login=%s server=%s", login_str, server_str)
        return {
            "success": False,
            "error_code": 429,
            "error_message": "Too many attempts \u2014 wait a minute before retrying.",
            "account_type": "unknown",
            "account_number": int(login_str),
            "balance_currency": None,
            "server": server_str,
        }

    if not is_mt5_available():
        logger.info("broker.test_connection outcome=mt5_unavailable "
                    "login=%s server=%s platform=%s",
                    login_str, server_str, sys.platform)
        return {
            "success": False,
            "error_code": None,
            "error_message": (
                "MT5 client is not available on this platform. "
                "MT5 runs on Windows only."),
            "account_type": "unknown",
            "account_number": int(login_str),
            "balance_currency": None,
            "server": server_str,
        }

    # The real branch below runs on Windows only. It is intentionally
    # thin: we hand off to the platform's MT5 module, harvest a small
    # set of fields, and disconnect.
    try:  # pragma: no cover -- Windows-only
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        return {
            "success": False,
            "error_code": None,
            "error_message": "MetaTrader5 client not installed.",
            "account_type": "unknown",
            "account_number": int(login_str),
            "balance_currency": None,
            "server": server_str,
        }

    result: dict[str, Any] = {  # pragma: no cover -- Windows-only
        "success": False,
        "error_code": None,
        "error_message": None,
        "account_type": "unknown",
        "account_number": int(login_str),
        "balance_currency": None,
        "server": server_str,
    }
    try:  # pragma: no cover -- Windows-only branch
        ok = mt5.initialize(login=int(login_str), password=password,
                            server=server_str, timeout=int(timeout * 1000))
        if not ok:
            err = mt5.last_error()
            result["error_code"] = int(err[0]) if err else None
            result["error_message"] = str(err[1]) if err else "MT5 init failed"
            return result
        info = mt5.account_info()
        if info is None:
            err = mt5.last_error()
            result["error_code"] = int(err[0]) if err else None
            result["error_message"] = "MT5 account_info returned None"
        else:
            result["account_number"] = int(info.login)
            result["balance_currency"] = str(info.currency)
            trade_mode = getattr(info, "trade_mode", None)
            if trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
                result["account_type"] = "demo"
            elif trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
                result["account_type"] = "live"
            else:
                result["account_type"] = "unknown"
            result["success"] = True
        return result
    finally:  # pragma: no cover -- Windows-only branch
        try:
            mt5.shutdown()
        except Exception:
            pass


def save_credentials(alias: str, login: Any, password: str,
                     server: str, account_type: str) -> bool:
    """Persist a credential tuple under ``alias`` in the OS keychain.

    The password rides through ``credentials.store_secret`` which does
    the encryption + log scrubbing.
    """
    alias_s = _validate_alias(alias)
    login_s = _validate_login(login)
    _validate_password(password)
    server_s = _validate_server(server)
    account_type_s = _validate_account_type(account_type)

    payload = json.dumps({
        "login": login_s,
        "password": password,
        "server": server_s,
        "account_type": account_type_s,
    })
    ok = credentials.store_secret(BROKER_NAMESPACE, alias_s, payload)
    logger.info("broker.save_credentials alias=%s login=%s server=%s "
                "account_type=%s outcome=%s",
                alias_s, login_s, server_s, account_type_s,
                "ok" if ok else "fail")
    return ok


def load_credentials(alias: str) -> dict | None:
    """Decrypt the credential tuple stored under ``alias``.

    Server-side only. Never surfaced via HTTP.
    """
    alias_s = _validate_alias(alias)
    raw = credentials.retrieve_secret(BROKER_NAMESPACE, alias_s)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    required = {"login", "password", "server", "account_type"}
    if not required.issubset(parsed):
        return None
    return parsed


def list_aliases() -> list[dict]:
    """Enumerate stored aliases. Passwords absent by construction.

    Returns each row as ``{alias, account_type, server, login}``. The
    password field is never populated by this function.
    """
    keys = credentials.list_keys(BROKER_NAMESPACE)
    out: list[dict] = []
    for alias in keys:
        creds = load_credentials(alias)
        if creds is None:
            continue
        row = {
            "alias": alias,
            "account_type": creds.get("account_type", "unknown"),
            "server": creds.get("server"),
            "login": creds.get("login"),
        }
        # Belt + braces: strip any password key even though load
        # already knows better.
        row.pop("password", None)
        out.append(row)
    return out


def delete_credentials(alias: str) -> bool:
    """Erase the credential tuple for ``alias``."""
    alias_s = _validate_alias(alias)
    ok = credentials.delete_secret(BROKER_NAMESPACE, alias_s)
    logger.info("broker.delete_credentials alias=%s outcome=%s",
                alias_s, "ok" if ok else "miss")
    return ok
