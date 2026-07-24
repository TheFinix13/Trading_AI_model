"""F006 module smoke -- `agent/platform/credentials.py`.

Complements the deep tests in tests/security/test_credentials.py with
lightweight import / signature / doc-string smoke checks that catch a
rename or a signature drift without exercising crypto.
"""
from __future__ import annotations

import inspect
import secrets as _secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import credentials  # noqa: E402


def test_public_api_signatures():
    """Contract with F007/F008 -- these signatures cannot silently drift."""
    assert list(inspect.signature(credentials.store_secret).parameters.keys()) \
        == ["namespace", "key", "value"]
    assert list(inspect.signature(credentials.retrieve_secret).parameters.keys()) \
        == ["namespace", "key"]
    assert list(inspect.signature(credentials.delete_secret).parameters.keys()) \
        == ["namespace", "key"]
    assert list(inspect.signature(credentials.list_keys).parameters.keys()) \
        == ["namespace"]


def test_module_docstring_mentions_disclaimer():
    ds = credentials.__doc__ or ""
    assert "keychain" in ds.lower() or "keyring" in ds.lower()


def test_encrypted_file_path_matches_config_dir(tmp_path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    assert credentials.encrypted_file_path().parent == tmp_path
    credentials._reset_state_for_tests()


def test_index_key_reserved(tmp_path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    with pytest.raises(ValueError):
        credentials.store_secret("ns", "__index__", "v")
    credentials._reset_state_for_tests()


def test_reset_state_helper_clears_module_state():
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    credentials._reset_state_for_tests()
    assert credentials._process_passphrase is None
    assert credentials._FORCE_FALLBACK is False


def test_is_keyring_available_returns_bool():
    result = credentials.is_keyring_available()
    assert isinstance(result, bool)
