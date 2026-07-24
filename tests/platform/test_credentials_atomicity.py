"""A006 (2026-07-24 audit) -- encrypted-bag write atomicity + locked
read-modify-write.

Pins: (a) `_write_encrypted_bag` goes through tmp-file + os.replace so
an interrupted write never corrupts the existing bag; (b) concurrent
`store_secret` calls from multiple threads never drop an alias.
"""
from __future__ import annotations

import secrets as _secrets
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.platform import credentials  # noqa: E402


@pytest.fixture(autouse=True)
def _fallback_store(tmp_path: Path):
    credentials._reset_state_for_tests()
    credentials.set_config_dir(tmp_path)
    # Randomly generated per test: the bag lives in tmp_path and is
    # discarded after the test, so no fixed literal is needed (and a
    # literal here trips secret scanners -- GitGuardian #35143401).
    credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))
    credentials.force_fallback(True)
    yield
    credentials._reset_state_for_tests()


class TestAtomicWrite:
    def test_interrupted_write_preserves_existing_bag(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert credentials.store_secret("ns", "alias1", "secret-1") is True

        # Simulate a crash mid-replace: the tmp file is written but
        # the swap never happens.
        import agent.platform.credentials as mod

        def _boom(src, dst):
            raise OSError("simulated crash before replace")

        monkeypatch.setattr(mod.os, "replace", _boom)
        assert credentials.store_secret("ns", "alias2", "secret-2") is False
        monkeypatch.undo()

        # The original bag is untouched and still decrypts.
        assert credentials.retrieve_secret("ns", "alias1") == "secret-1"
        assert credentials.retrieve_secret("ns", "alias2") is None
        assert credentials.list_keys("ns") == ["alias1"]

    def test_interrupted_tmp_write_preserves_existing_bag(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert credentials.store_secret("ns", "alias1", "secret-1") is True

        original = Path.write_bytes

        def _boom(self, data):
            if str(self).endswith(".tmp"):
                raise OSError("simulated disk-full during tmp write")
            return original(self, data)

        monkeypatch.setattr(Path, "write_bytes", _boom)
        assert credentials.store_secret("ns", "alias2", "secret-2") is False
        monkeypatch.undo()

        assert credentials.retrieve_secret("ns", "alias1") == "secret-1"

    def test_no_stray_tmp_file_after_successful_write(self) -> None:
        assert credentials.store_secret("ns", "alias1", "secret-1") is True
        enc = credentials.encrypted_file_path()
        assert enc.is_file()
        assert not enc.with_suffix(enc.suffix + ".tmp").exists()


class TestConcurrentStore:
    def test_two_threads_storing_do_not_lose_an_alias(self) -> None:
        n_threads = 8
        n_each = 5
        errors: list[Exception] = []

        def _worker(idx: int) -> None:
            try:
                for j in range(n_each):
                    assert credentials.store_secret(
                        "ns", f"alias-{idx}-{j}", f"value-{idx}-{j}") is True
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,))
                   for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        keys = credentials.list_keys("ns")
        assert len(keys) == n_threads * n_each
        for i in range(n_threads):
            for j in range(n_each):
                assert credentials.retrieve_secret(
                    "ns", f"alias-{i}-{j}") == f"value-{i}-{j}"

    def test_concurrent_store_and_delete_consistent(self) -> None:
        for j in range(10):
            assert credentials.store_secret(
                "ns", f"keep-{j}", "v") is True
            assert credentials.store_secret(
                "ns", f"drop-{j}", "v") is True

        def _deleter() -> None:
            for j in range(10):
                credentials.delete_secret("ns", f"drop-{j}")

        def _adder() -> None:
            for j in range(10):
                credentials.store_secret("ns", f"new-{j}", "v")

        t1 = threading.Thread(target=_deleter)
        t2 = threading.Thread(target=_adder)
        t1.start(); t2.start()
        t1.join(); t2.join()

        keys = set(credentials.list_keys("ns"))
        for j in range(10):
            assert f"keep-{j}" in keys
            assert f"new-{j}" in keys
            assert f"drop-{j}" not in keys
