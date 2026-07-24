"""I014 follow-up QoL: the startup banner prints a ready-to-paste
launch URL so the operator never assembles host + port + ?token= by
hand (the assembly step is where the VM cutover friction came from).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.serve_platform import launch_url  # noqa: E402


class TestLaunchUrl:
    def test_localhost_no_token(self) -> None:
        assert launch_url("127.0.0.1", 8787) == "http://127.0.0.1:8787/"

    def test_token_appended_as_query(self) -> None:
        assert (launch_url("192.168.1.20", 8787, "abc123")
                == "http://192.168.1.20:8787/?token=abc123")

    def test_wildcard_bind_shown_as_loopback(self) -> None:
        """0.0.0.0 is a bind address, not a dialable one -- the printed
        URL must be what a browser on the box itself should open."""
        assert (launch_url("0.0.0.0", 8787, "t0k")
                == "http://127.0.0.1:8787/?token=t0k")

    def test_ipv6_wildcard_shown_as_loopback(self) -> None:
        assert launch_url("::", 9000) == "http://127.0.0.1:9000/"
