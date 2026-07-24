"""F006 -- encrypted credential storage.

Thin wrapper over the ``keyring`` package (OS keychain) with a Fernet
encrypted-file fallback for environments where a keychain backend is
not available (headless Linux boxes, some CI runners).

Public API::

    store_secret(namespace, key, value)       -> True on success
    retrieve_secret(namespace, key)           -> str | None
    delete_secret(namespace, key)             -> True on success
    list_keys(namespace)                      -> list[str]   (keys only)
    is_keyring_available()                    -> bool
    set_encrypted_file_passphrase(passphrase) -> None (per-process)
    encrypted_file_path()                     -> Path

Every function is deliberately defensive: `store_secret` returns False
instead of raising when neither backend is usable, so callers can
render a friendly error to the user rather than a stacktrace.

Security invariants (pinned by tests/security/test_credentials.py):

1. **No plaintext value ever appears in a log line.** Every log call
   in this module scrubs the ``value`` argument through
   ``_redact(value)`` before formatting.
2. **`list_keys` never returns values.** It's the "safe listing" API;
   the /api/broker/list HTTP endpoint uses this exclusively.
3. **The encrypted-file fallback holds Fernet-encrypted bytes, not
   plaintext**, and the passphrase is derived through PBKDF2 with 200k
   iterations against a random-per-install salt.
4. **Empty / whitespace / control-char inputs are rejected** by
   ``_sanitize_key`` and ``_sanitize_namespace``, and path-traversal
   attempts (``..``, ``/``) in the namespace are refused.

Layout on disk (fallback file only)::

    <config_dir>/credentials.enc      # Fernet-encrypted JSON bag
    <config_dir>/credentials.salt     # 16-byte PBKDF2 salt

Where ``<config_dir>`` = ``$BLUELOCK_CONFIG_DIR`` if set, else
``~/.config/bluelock`` (POSIX) / ``%APPDATA%\\Bluelock`` (Windows).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

try:
    import keyring
    from keyring.errors import KeyringError, NoKeyringError
    _KEYRING_IMPORTED = True
except ImportError:  # pragma: no cover -- keyring is in requirements
    keyring = None  # type: ignore[assignment]

    class KeyringError(Exception):  # type: ignore[no-redef]
        """Fallback when keyring is not installed."""

    class NoKeyringError(KeyringError):  # type: ignore[no-redef]
        """Fallback when keyring is not installed."""

    _KEYRING_IMPORTED = False


logger = logging.getLogger(__name__)

# Namespaces and keys allow letters, digits, underscore, hyphen, dot.
# Everything else -- including path separators, control chars, empty --
# is rejected. Length capped at 64.
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

# Values (secrets) may be arbitrary Unicode but MUST be non-empty and
# under a hard cap. Control chars outside \t\n are refused too.
_MAX_VALUE_LEN = 8192
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

_PBKDF2_ITERATIONS = 200_000
_PBKDF2_SALT_BYTES = 16

# Per-process passphrase override for the encrypted-file fallback.
# Set by set_encrypted_file_passphrase() (called by the onboarding
# passphrase step). None => attempt env var BLUELOCK_PASSPHRASE.
_process_passphrase: str | None = None

# Force-fallback mode used by tests to exercise the encrypted-file path
# without touching the real OS keychain.
_FORCE_FALLBACK: bool = False

# Override for the config dir (used by tests to point at tmp_path).
_config_dir_override: Path | None = None

# A006 (2026-07-24 audit): the fallback bag is one file mutated via
# read-modify-write; without a lock two concurrent store/delete calls
# can interleave and silently drop each other's alias. Guard every
# RMW cycle with this lock.
_BAG_LOCK = threading.RLock()


def _redact(s: str | None) -> str:
    """Return a fixed-length placeholder for a possibly-sensitive value.

    Used before any log call. Never returns the real value.
    """
    if s is None:
        return "<none>"
    if not isinstance(s, str):
        return "<non-string>"
    return f"<redacted:{len(s)}chars>"


def _sanitize_namespace(namespace: str) -> str:
    if not isinstance(namespace, str) or not _SAFE_TOKEN_RE.match(namespace):
        raise ValueError(
            "namespace must be 1..64 chars of [A-Za-z0-9_.-] "
            "(rejects empty / whitespace / control chars / path separators)")
    if ".." in namespace or namespace.startswith(".") or namespace.endswith("."):
        raise ValueError("namespace must not contain path-traversal patterns")
    return namespace


def _sanitize_key(key: str) -> str:
    if not isinstance(key, str) or not _SAFE_TOKEN_RE.match(key):
        raise ValueError(
            "key must be 1..64 chars of [A-Za-z0-9_.-] "
            "(rejects empty / whitespace / control chars / path separators)")
    if ".." in key or key.startswith(".") or key.endswith("."):
        raise ValueError("key must not contain path-traversal patterns")
    return key


def _sanitize_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    if not value:
        raise ValueError("value must be non-empty")
    if len(value) > _MAX_VALUE_LEN:
        raise ValueError(f"value exceeds {_MAX_VALUE_LEN} chars")
    if _CONTROL_RE.search(value):
        raise ValueError("value contains disallowed control characters")
    return value


def _default_config_dir() -> Path:
    override = os.environ.get("BLUELOCK_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":  # pragma: no cover -- CI is POSIX
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Bluelock"
    return Path.home() / ".config" / "bluelock"


def _config_dir() -> Path:
    return _config_dir_override if _config_dir_override is not None else _default_config_dir()


def encrypted_file_path() -> Path:  # claim-exempt: internal path helper; no HTTP surface
    """Return the path to the encrypted-file fallback store."""
    return _config_dir() / "credentials.enc"


def _salt_path() -> Path:
    return _config_dir() / "credentials.salt"


def set_config_dir(path: Path | None) -> None:  # claim-exempt: test-only config override
    """Override the config dir. Passing None restores the default.

    Used by tests via a fixture; the wizard never calls this at runtime.
    """
    global _config_dir_override
    _config_dir_override = Path(path) if path is not None else None


def set_encrypted_file_passphrase(passphrase: str | None) -> None:  # claim-exempt: process-local secret setter, no HTTP surface
    """Set the per-process passphrase for the encrypted-file fallback.

    Passing None reverts to the ``BLUELOCK_PASSPHRASE`` env-var route.
    The passphrase itself is never stored on disk in plaintext -- only
    the PBKDF2-derived Fernet key is used, and even that is only held
    in memory.
    """
    global _process_passphrase
    _process_passphrase = passphrase


def _current_passphrase() -> str | None:
    if _process_passphrase is not None:
        return _process_passphrase
    return os.environ.get("BLUELOCK_PASSPHRASE")


def _load_or_create_salt() -> bytes:
    path = _salt_path()
    if path.is_file():
        try:
            return path.read_bytes()
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(_PBKDF2_SALT_BYTES)
    path.write_bytes(salt)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return salt


def _fernet_from_passphrase(passphrase: str) -> Fernet:
    salt = _load_or_create_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    return Fernet(key)


def _read_encrypted_bag(passphrase: str) -> dict:
    path = encrypted_file_path()
    if not path.is_file():
        return {}
    try:
        f = _fernet_from_passphrase(passphrase)
        raw = path.read_bytes()
        plain = f.decrypt(raw)
        return json.loads(plain.decode("utf-8"))
    except (InvalidToken, ValueError, OSError, json.JSONDecodeError):
        return {}


def _write_encrypted_bag(passphrase: str, bag: dict) -> bool:
    path = encrypted_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        f = _fernet_from_passphrase(passphrase)
        blob = f.encrypt(json.dumps(bag).encode("utf-8"))
        # A006: tmp-file + os.replace (same pattern as
        # risk_budget.save_config) so an interrupted write can never
        # leave a truncated -- hence undecryptable -- bag behind.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(blob)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        return True
    except (ValueError, OSError):
        return False


def _keyring_ready() -> bool:
    """Whether the OS keychain backend is usable in this process.

    Tests may force-flip via ``force_fallback(True)``.
    """
    if _FORCE_FALLBACK:
        return False
    if not _KEYRING_IMPORTED or keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
    except KeyringError:
        return False
    name = type(backend).__name__.lower()
    return "fail" not in name  # keyring's Fail backend indicates no OS store


def is_keyring_available() -> bool:  # claim-exempt: capability probe; no HTTP surface
    """Public probe: is the OS keychain usable right now?"""
    return _keyring_ready()


def force_fallback(enabled: bool) -> None:  # claim-exempt: test-only fallback override
    """Test helper -- force the encrypted-file path even if keychain works."""
    global _FORCE_FALLBACK
    _FORCE_FALLBACK = bool(enabled)


def _kr_service(namespace: str) -> str:
    """Deterministic service name for the keychain."""
    return f"bluelock.{namespace}"


_INDEX_KEY = "__index__"


def _keyring_index_read(namespace: str) -> list[str]:
    """Read the alias index stored inside the keychain under __index__."""
    if not _keyring_ready():
        return []
    try:
        raw = keyring.get_password(_kr_service(namespace), _INDEX_KEY)  # type: ignore[union-attr]
    except KeyringError:
        return []
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(x) for x in parsed if isinstance(x, str)]


def _keyring_index_write(namespace: str, keys: list[str]) -> None:
    if not _keyring_ready():
        return
    try:
        keyring.set_password(  # type: ignore[union-attr]
            _kr_service(namespace), _INDEX_KEY, json.dumps(sorted(set(keys))))
    except KeyringError:
        pass


def _keyring_index_add(namespace: str, key: str) -> None:
    idx = _keyring_index_read(namespace)
    if key not in idx:
        idx.append(key)
        _keyring_index_write(namespace, idx)


def _keyring_index_remove(namespace: str, key: str) -> None:
    idx = _keyring_index_read(namespace)
    if key in idx:
        idx = [x for x in idx if x != key]
        _keyring_index_write(namespace, idx)


def store_secret(namespace: str, key: str, value: str) -> bool:
    """Store ``value`` under ``namespace``/``key``.

    Tries the OS keychain first; on failure (or when tests forced the
    fallback), writes to the encrypted file. Returns True on success,
    False otherwise. The value itself never appears in a log line.

    Also maintains an alias index (a __index__ key in the same
    namespace) so :func:`list_keys` can enumerate stored aliases without
    any cross-platform keyring "list" API.
    """
    ns = _sanitize_namespace(namespace)
    k = _sanitize_key(key)
    v = _sanitize_value(value)
    if k == _INDEX_KEY:
        raise ValueError(f"key {_INDEX_KEY!r} is reserved")

    if _keyring_ready():
        try:
            keyring.set_password(_kr_service(ns), k, v)  # type: ignore[union-attr]
            _keyring_index_add(ns, k)
            logger.info("credentials.store_secret namespace=%s key=%s value=%s "
                        "backend=keyring outcome=ok", ns, k, _redact(v))
            return True
        except KeyringError as exc:
            logger.info("credentials.store_secret namespace=%s key=%s value=%s "
                        "backend=keyring outcome=fail exc=%s",
                        ns, k, _redact(v), exc.__class__.__name__)

    passphrase = _current_passphrase()
    if not passphrase:
        logger.info("credentials.store_secret namespace=%s key=%s value=%s "
                    "backend=fallback outcome=no_passphrase", ns, k, _redact(v))
        return False
    with _BAG_LOCK:
        bag = _read_encrypted_bag(passphrase)
        bag.setdefault(ns, {})[k] = v
        ok = _write_encrypted_bag(passphrase, bag)
    logger.info("credentials.store_secret namespace=%s key=%s value=%s "
                "backend=fallback outcome=%s", ns, k, _redact(v),
                "ok" if ok else "fail")
    return ok


def retrieve_secret(namespace: str, key: str) -> str | None:
    """Fetch a stored value. Returns None when missing / decrypt fails."""
    ns = _sanitize_namespace(namespace)
    k = _sanitize_key(key)

    if _keyring_ready():
        try:
            val = keyring.get_password(_kr_service(ns), k)  # type: ignore[union-attr]
            if val is not None:
                logger.info("credentials.retrieve_secret namespace=%s key=%s "
                            "backend=keyring outcome=hit value=%s",
                            ns, k, _redact(val))
                return val
        except KeyringError:
            pass

    passphrase = _current_passphrase()
    if not passphrase:
        logger.info("credentials.retrieve_secret namespace=%s key=%s "
                    "backend=fallback outcome=no_passphrase", ns, k)
        return None
    bag = _read_encrypted_bag(passphrase)
    val = bag.get(ns, {}).get(k)
    logger.info("credentials.retrieve_secret namespace=%s key=%s "
                "backend=fallback outcome=%s value=%s",
                ns, k, "hit" if val is not None else "miss", _redact(val))
    return val


def delete_secret(namespace: str, key: str) -> bool:
    """Remove a stored key from BOTH backends. Idempotent."""
    ns = _sanitize_namespace(namespace)
    k = _sanitize_key(key)
    if k == _INDEX_KEY:
        raise ValueError(f"key {_INDEX_KEY!r} is reserved")
    removed = False

    if _keyring_ready():
        try:
            keyring.delete_password(_kr_service(ns), k)  # type: ignore[union-attr]
            removed = True
        except KeyringError:
            pass
        _keyring_index_remove(ns, k)

    passphrase = _current_passphrase()
    if passphrase:
        with _BAG_LOCK:
            bag = _read_encrypted_bag(passphrase)
            if k in bag.get(ns, {}):
                del bag[ns][k]
                if not bag[ns]:
                    del bag[ns]
                _write_encrypted_bag(passphrase, bag)
                removed = True

    logger.info("credentials.delete_secret namespace=%s key=%s outcome=%s",
                ns, k, "ok" if removed else "miss")
    return removed


def list_keys(namespace: str) -> list[str]:
    """List known keys under ``namespace``. Values NEVER returned.

    Combines the keyring alias index (maintained by :func:`store_secret`)
    with the fallback bag's key set so a stored alias is visible
    regardless of which backend received the write.
    """
    ns = _sanitize_namespace(namespace)
    keys: set[str] = set()

    if _keyring_ready():
        keys.update(_keyring_index_read(ns))

    passphrase = _current_passphrase()
    if passphrase:
        bag = _read_encrypted_bag(passphrase)
        keys.update(bag.get(ns, {}).keys())

    return sorted(k for k in keys if k != _INDEX_KEY)


def _reset_state_for_tests() -> None:
    """Test helper -- reset module-level state between tests."""
    global _process_passphrase, _FORCE_FALLBACK, _config_dir_override
    _process_passphrase = None
    _FORCE_FALLBACK = False
    _config_dir_override = None
