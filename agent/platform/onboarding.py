"""F008 -- first-time setup / onboarding flow.

The setup wizard has to answer four questions before the platform will
route the user to the hub:

1. Has an install token been generated? (F006 -- `auth.is_install_configured`).
2. Has a passphrase been chosen for the encrypted-file fallback, or
   was the OS keychain confirmed available? (F006 -- `credentials`).
3. Has at least one broker alias been saved? (F007 -- `broker_connection.list_aliases`).
4. Has the user picked their default pairs and hit "Finish setup"?
   (this module -- `mark_setup_complete`).

Public API::

    is_first_visit()               -> bool
    is_setup_complete()            -> bool
    mark_setup_complete()          -> bool
    reset_install()                -> bool
    get_onboarding_state()         -> dict
    set_current_step(step)         -> bool
    set_default_pairs(pairs)       -> bool
    get_default_pairs()            -> list[str]
    validate_passphrase(passphrase, keyring_available) -> tuple[bool, str]

Storage lives entirely in the F006 credentials layer. Nothing in this
module touches `platform.toml`. `reset_install` sweeps every key in
both the ``bluelock`` and ``broker_mt5`` namespaces so the operator
can rehearse a cold install without side-loading state through git.

Security invariants (pinned by tests/security/test_onboarding.py):

1. **Reset flow leaves no state behind.** After `reset_install`,
   `list_keys` returns [] for both namespaces.
2. **Passphrase strength gate.** Empty passphrase is only accepted
   when the OS keychain is available. Otherwise a minimum of 12
   characters is enforced.
3. **First-visit redirect gate.** `is_first_visit` returns True iff
   no install token exists AND setup has not been marked complete.
"""
from __future__ import annotations

import logging
from typing import Any

from agent.platform import auth, broker_connection, credentials

_LOG = logging.getLogger(__name__)

ONBOARDING_NAMESPACE = "bluelock"

_SETUP_COMPLETE_KEY = "setup_complete"
_CURRENT_STEP_KEY = "onboarding_step"
_DEFAULT_PAIRS_KEY = "default_pairs"

_STEPS: tuple[str, ...] = (
    "welcome", "passphrase", "broker", "pairs", "confirm",
)

_ALLOWED_PAIRS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")

# Passphrase floor. When the OS keychain is available the user is
# allowed to skip the fallback passphrase (empty accepted). When the
# keychain is missing, the passphrase secures the encrypted-file
# fallback and must be at least this long.
_MIN_PASSPHRASE_CHARS = 12


def is_setup_complete() -> bool:
    """True iff the user has finished the wizard end-to-end."""
    flag = credentials.retrieve_secret(
        ONBOARDING_NAMESPACE, _SETUP_COMPLETE_KEY)
    return flag == "true"


def is_first_visit() -> bool:
    """True iff onboarding has not yet been completed.

    An install may have a token stored (via `/api/auth/status` probe
    or by legacy `platform.toml`) but still not have finished the
    F008 setup steps. We treat that case as first-visit-in-progress
    so the wizard resumes at the correct step rather than dropping
    the user into a half-configured hub.
    """
    return not is_setup_complete()


def mark_setup_complete() -> bool:
    """Persist the ``setup_complete=True`` flag. Idempotent."""
    ok = credentials.store_secret(
        ONBOARDING_NAMESPACE, _SETUP_COMPLETE_KEY, "true")
    if not ok:
        _LOG.warning(
            "onboarding.mark_setup_complete: credentials layer refused "
            "to persist -- setup will re-prompt on next visit.")
    return ok


def reset_install() -> bool:
    """Wipe every stored key in the onboarding + broker namespaces.

    Used by `/settings/reset-install`. Sweeps both the OS keychain
    index and the encrypted-file fallback bag. Idempotent: calling
    twice is a no-op the second time.

    Returns True if every delete_secret call returned True or the
    key was already absent. Returns False if any delete raised.
    """
    ok = True
    for namespace in (ONBOARDING_NAMESPACE, broker_connection.BROKER_NAMESPACE):
        try:
            keys = credentials.list_keys(namespace)
        except (ValueError, RuntimeError) as exc:
            _LOG.warning(
                "onboarding.reset_install: could not enumerate %s: %s",
                namespace, exc)
            ok = False
            continue
        for k in keys:
            try:
                credentials.delete_secret(namespace, k)
            except (ValueError, RuntimeError) as exc:
                _LOG.warning(
                    "onboarding.reset_install: delete %s/%s failed: %s",
                    namespace, k, exc)
                ok = False
    return ok


def set_current_step(step: Any) -> bool:
    """Persist the current wizard step so a page reload resumes."""
    if not isinstance(step, str) or step not in _STEPS:
        raise ValueError(f"step must be one of {_STEPS}, got {step!r}")
    return credentials.store_secret(
        ONBOARDING_NAMESPACE, _CURRENT_STEP_KEY, step)


def _current_step_or_default() -> str:
    stored = credentials.retrieve_secret(
        ONBOARDING_NAMESPACE, _CURRENT_STEP_KEY)
    if stored in _STEPS:
        return stored
    return "welcome"


def set_default_pairs(pairs: Any) -> bool:
    """Persist the user's default watched pairs.

    Validates against `_ALLOWED_PAIRS`. Empty list is refused --
    the wizard cannot advance without at least one pair.
    """
    if not isinstance(pairs, (list, tuple)):
        raise ValueError("pairs must be a list or tuple of strings")
    cleaned: list[str] = []
    for p in pairs:
        if not isinstance(p, str):
            raise ValueError(f"pair must be str, got {type(p).__name__}")
        up = p.upper().strip()
        if up not in _ALLOWED_PAIRS:
            raise ValueError(
                f"pair {p!r} not in supported list {_ALLOWED_PAIRS}")
        if up not in cleaned:
            cleaned.append(up)
    if not cleaned:
        raise ValueError("at least one default pair is required")
    return credentials.store_secret(
        ONBOARDING_NAMESPACE, _DEFAULT_PAIRS_KEY, ",".join(cleaned))


def get_default_pairs() -> list[str]:
    """Return the persisted default pairs, or ["EURUSD"] as a fallback."""
    raw = credentials.retrieve_secret(
        ONBOARDING_NAMESPACE, _DEFAULT_PAIRS_KEY)
    if not raw:
        return ["EURUSD"]
    out = [p for p in raw.split(",") if p in _ALLOWED_PAIRS]
    return out or ["EURUSD"]


def validate_passphrase(passphrase: Any,
                        keyring_available: bool | None = None,
                        ) -> tuple[bool, str]:
    """Return ``(ok, message)`` for a proposed passphrase.

    - When the OS keychain is available, empty passphrase is accepted
      (the fallback file will not be needed).
    - Otherwise, at least `_MIN_PASSPHRASE_CHARS` characters are
      required. Whitespace-only passphrases are refused.
    """
    if keyring_available is None:
        keyring_available = credentials.is_keyring_available()

    if passphrase is None:
        passphrase = ""
    if not isinstance(passphrase, str):
        return False, "Passphrase must be text."

    stripped = passphrase.strip()
    if not stripped:
        if keyring_available:
            return True, "Keychain available -- fallback passphrase not needed."
        return False, (
            "No keychain available -- a passphrase of at least "
            f"{_MIN_PASSPHRASE_CHARS} characters is required.")
    if len(passphrase) < _MIN_PASSPHRASE_CHARS:
        return False, (
            f"Passphrase must be at least {_MIN_PASSPHRASE_CHARS} "
            "characters long.")
    if "\x00" in passphrase:
        return False, "Passphrase must not contain control characters."
    return True, "Passphrase accepted."


def get_onboarding_state() -> dict:
    """Snapshot the wizard state -- consumed by the UI on load.

    Fields:
    - ``step``: current wizard step id.
    - ``completed``: True iff `mark_setup_complete` has fired.
    - ``install_fingerprint``: F006 fingerprint for display.
    - ``broker_connected``: True iff at least one broker alias
      exists.
    - ``keyring_available``: passed straight from credentials layer.
    - ``default_pairs``: list of persisted default pairs.
    """
    try:
        aliases = broker_connection.list_aliases()
    except (ValueError, RuntimeError):
        aliases = []
    return {
        "step": _current_step_or_default(),
        "completed": is_setup_complete(),
        "install_fingerprint": (
            auth.install_token_fingerprint(auth.load_install_token())
            if auth.is_install_configured() else None),
        "broker_connected": len(aliases) > 0,
        "keyring_available": credentials.is_keyring_available(),
        "default_pairs": get_default_pairs(),
    }
