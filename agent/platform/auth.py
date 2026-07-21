"""F006 -- install-scoped authentication.

Single-user, single-install model per D052. Not a user-account system
(that lands in Sprint 5+). Everything here is about proving that the
HTTP client hitting a non-localhost bind knows the install token
generated at first setup.

Public API::

    generate_install_token()          -> str  (freshly stored)
    load_install_token()              -> str | None
    clear_install_token()             -> bool
    install_token_fingerprint(token)  -> str
    auth_status(token)                -> dict
    check_request_token(header, cookie, query, fallback_token) -> bool
    is_install_configured()           -> bool
    RedactingFilter                   -- logging filter

Layout::

    keyring namespace = "bluelock"
    keyring key       = "install_token"

The fingerprint is the first 8 chars + "\u2026" + the last 8 chars of
the token, so users can record it without exposing the full string.
Fingerprint alone cannot be used to derive the token (log entropy is
~256 bit; fingerprint reveals 96 bit).
"""
from __future__ import annotations

import hmac
import logging
import re
import secrets

from agent.platform import credentials

AUTH_NAMESPACE = "bluelock"
INSTALL_TOKEN_KEY = "install_token"
INSTALL_TOKEN_BYTES = 32  # 256 bits => ~43 base64url chars
_INSTALL_TOKEN_MIN_LEN = 32
_INSTALL_TOKEN_MAX_LEN = 128
_TOKEN_CHAR_RE = re.compile(r"^[A-Za-z0-9_\-]{" + str(_INSTALL_TOKEN_MIN_LEN) +
                            r"," + str(_INSTALL_TOKEN_MAX_LEN) + r"}$")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token generation, storage, fingerprint
# ---------------------------------------------------------------------------

def generate_install_token() -> str:
    """Generate a fresh URL-safe install token and store it.

    Returns the plaintext token (the caller displays it once, then
    stores it via :func:`credentials.store_secret`). Overwrites any
    prior install token.
    """
    token = secrets.token_urlsafe(INSTALL_TOKEN_BYTES)
    ok = credentials.store_secret(AUTH_NAMESPACE, INSTALL_TOKEN_KEY, token)
    if not ok:
        raise RuntimeError(
            "install token could not be stored -- OS keychain unavailable "
            "and no fallback passphrase configured. Run through /onboarding "
            "to set a passphrase first.")
    return token


def load_install_token() -> str | None:
    """Return the stored install token or None if not configured."""
    return credentials.retrieve_secret(AUTH_NAMESPACE, INSTALL_TOKEN_KEY)


def clear_install_token() -> bool:
    """Erase the stored install token."""
    return credentials.delete_secret(AUTH_NAMESPACE, INSTALL_TOKEN_KEY)


def is_install_configured() -> bool:
    """True when an install token exists in the store."""
    return load_install_token() is not None


def install_token_fingerprint(token: str | None) -> str:
    """Return a display fingerprint (first 8 + last 8 chars).

    An empty / None token returns the empty string. The fingerprint
    intentionally leaks 16 characters of the token -- enough for the
    user to recognise it, not enough to reconstruct it (search space
    for the redacted middle stays ~256 bits).
    """
    if not token:
        return ""
    if len(token) <= 17:
        return token[:4] + "\u2026" + token[-4:]
    return token[:8] + "\u2026" + token[-8:]


# ---------------------------------------------------------------------------
# Request-time checks
# ---------------------------------------------------------------------------

def _is_well_formed(token: str | None) -> bool:
    if not token or not isinstance(token, str):
        return False
    return bool(_TOKEN_CHAR_RE.match(token))


def constant_time_equal(a: str | None, b: str | None) -> bool:
    """Constant-time string compare (side-channel resistant)."""
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def check_request_token(header_value: str | None = None,
                        cookie_value: str | None = None,
                        query_value: str | None = None,
                        fallback_token: str | None = None) -> bool:
    """Return True iff any of the presented credentials matches an
    accepted token.

    Accepted tokens = the stored install token (F006) PLUS the
    ``platform.toml`` `auth_token` fallback (pre-Sprint-1) when
    ``fallback_token`` is passed. This keeps the deployed VM's existing
    setup working (D052 backwards-compat).

    Every well-formed presented token is compared in constant time
    against every accepted token. Malformed presented tokens are
    rejected before comparison, so we never leak length information
    for the accepted tokens.
    """
    accepted: list[str] = []
    install = load_install_token()
    if install and _is_well_formed(install):
        accepted.append(install)
    if fallback_token:
        accepted.append(fallback_token)
    if not accepted:
        return False

    for presented in (header_value, cookie_value, query_value):
        if not _is_well_formed(presented):
            continue
        for known in accepted:
            if constant_time_equal(presented, known):
                return True
    return False


def auth_status() -> dict:
    """Return the payload for /api/auth/status.

    Never returns the token itself; only whether one is stored and its
    display fingerprint.
    """
    token = load_install_token()
    return {
        "authenticated": token is not None,
        "install_fingerprint": install_token_fingerprint(token) or None,
        "keyring_available": credentials.is_keyring_available(),
    }


# ---------------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------------

# Anything that looks like a URL-safe token of >=24 chars gets scrubbed.
_URL_SAFE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{24,}")

# Any occurrence of the substring "password=" (case-insensitive) followed
# by non-whitespace is redacted. Same for "token=", "secret=", "pass=".
_KV_SENSITIVE_RE = re.compile(
    r"(?i)(password|passphrase|token|secret|pass|apikey|api[_-]?key)"
    r"\s*[=:]\s*([^\s,;\"'&]+)")

# Explicit MT5 password field patterns.
_MT5_PW_RE = re.compile(
    r"(?i)(\"password\"\s*:\s*)\"([^\"]+)\"")


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs tokens / passwords from log lines.

    Installed on the root logger (or the platform's namespace root) at
    :func:`serve_platform.main` initialisation. The filter mutates the
    log record's ``msg`` and ``args`` before the formatter runs.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = _scrub_text(str(record.msg))
        except Exception:  # pragma: no cover -- filter must never raise
            pass
        try:
            if record.args:
                record.args = tuple(_scrub_any(a) for a in record.args)
        except Exception:  # pragma: no cover
            pass
        return True


def _scrub_text(text: str) -> str:
    text = _KV_SENSITIVE_RE.sub(
        lambda m: f"{m.group(1)}=<redacted>", text)
    text = _MT5_PW_RE.sub(
        lambda m: f"{m.group(1)}\"<redacted>\"", text)
    text = _URL_SAFE_TOKEN_RE.sub("<redacted-token>", text)
    return text


def _scrub_any(value: object) -> object:
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub_any(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        cls = type(value)
        return cls(_scrub_any(v) for v in value)
    return value


def install_redacting_filter(logger_name: str = "") -> RedactingFilter:
    """Mount a fresh :class:`RedactingFilter` on the target logger.

    Called once at server startup. Returns the filter instance so callers
    can remove it in tests. Idempotent -- calling twice replaces the
    prior filter.
    """
    target = logging.getLogger(logger_name)
    filt = RedactingFilter(name="auth.RedactingFilter")
    existing = [f for f in target.filters
                if isinstance(f, RedactingFilter)]
    for f in existing:
        target.removeFilter(f)
    target.addFilter(filt)
    return filt
