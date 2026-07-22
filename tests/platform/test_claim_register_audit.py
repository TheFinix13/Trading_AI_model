"""F010 -- claim-register audit tests.

Runs the audit programmatically so an unregistered public accessor
fails the suite even without the git-hook installed. Also validates
the installer against a temp git repo.

Tests:

1. ``test_audit_current_repo_passes``          audit on the real repo
   exits 0 (clean, or clean + warnings).
2. ``test_marker_registered_passes``           temp module + temp register:
   registered marker → ok.
3. ``test_unregistered_marker_fails``          same setup, marker not in
   register → exit 1 with a diagnostic.
4. ``test_unregistered_accessor_fails``        heading exists, def foo(),
   foo not in register → exit 1.
5. ``test_exempt_marker_suppresses``           # claim-exempt: reason on
   def line → passes.
6. ``test_orphan_register_entry_warns``        register mentions
   ``mod.zzz`` but no accessor → ok=True but orphan reported.
7. ``test_json_output_shape``                  --json output matches
   ``AuditResult.as_dict()``.
8. ``test_install_hook_idempotent``            installer + reinstall +
   uninstall on a temp git repo is idempotent and correctly backs up.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "check_claim_register.py"
INSTALLER_SCRIPT = REPO_ROOT / "scripts" / "install_git_hooks.py"
HOOK_TEMPLATE = REPO_ROOT / "scripts" / "git-hooks" / "pre-commit"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_claim_register as audit_module  # noqa: E402  -- after sys.path tweak
import install_git_hooks as installer_module  # noqa: E402


def _write_temp_repo(
    tmp_path: Path,
    *,
    platform_files: dict[str, str],
    register_body: str,
) -> Path:
    """Create a fake repo at ``tmp_path`` with ``agent/platform/*.py``
    and ``company/legal/claim_register.md``. Returns the repo root."""
    root = tmp_path
    (root / "agent" / "platform").mkdir(parents=True)
    (root / "company" / "legal").mkdir(parents=True)
    (root / "agent" / "platform" / "__init__.py").write_text("")
    for name, body in platform_files.items():
        (root / "agent" / "platform" / name).write_text(body)
    (root / "company" / "legal" / "claim_register.md").write_text(register_body)
    return root


def test_audit_current_repo_passes() -> None:
    """The real repo must audit clean at all times -- F010 acceptance."""
    result = audit_module.run_audit(root=REPO_ROOT)
    assert result.ok, (
        "Unregistered claims in agent/platform. Fix by registering in "
        "company/legal/claim_register.md or adding '# claim-exempt: <reason>':\n"
        + "\n".join(
            f"  {e.file}:{e.line} {e.kind} {e.module}.{e.name}"
            for e in result.unregistered
        )
    )


def test_marker_registered_passes(tmp_path: Path) -> None:
    root = _write_temp_repo(
        tmp_path,
        platform_files={
            "sample.py": (
                "def emitter():\n"
                "    # claim: OK_CLAIM\n"
                "    return {'OK_CLAIM': 1}\n"
            )
        },
        register_body=(
            "# Legal claim register\n\n"
            "### F999 — `agent/platform/sample.py`\n\n"
            "Public accessors: `sample.emitter`.\n\n"
            "| Field | Human meaning | Code path | Disclaimer required? |\n"
            "|---|---|---|---|\n"
            "| `OK_CLAIM` | Sample field. | `sample.emitter`. | None. |\n"
        ),
    )
    result = audit_module.run_audit(root=root)
    assert result.ok is True
    assert result.unregistered == []
    assert "sample" in result.audited_modules


def test_unregistered_marker_fails(tmp_path: Path) -> None:
    root = _write_temp_repo(
        tmp_path,
        platform_files={
            "sample.py": (
                "def emitter():\n"
                "    # claim: SPARE_CLAIM\n"
                "    return {'SPARE_CLAIM': 1}\n"
            )
        },
        register_body=(
            "# Legal claim register\n\n"
            "### F999 — `agent/platform/sample.py`\n\n"
            "Public accessors: `sample.emitter`.\n\n"
        ),
    )
    result = audit_module.run_audit(root=root)
    assert result.ok is False
    marker_hits = [e for e in result.unregistered if e.kind == "marker"]
    assert len(marker_hits) == 1
    entry = marker_hits[0]
    assert entry.name == "SPARE_CLAIM"
    assert entry.module == "sample"
    assert entry.file.endswith("agent/platform/sample.py")
    assert entry.line == 2


def test_unregistered_accessor_fails(tmp_path: Path) -> None:
    root = _write_temp_repo(
        tmp_path,
        platform_files={
            "sample.py": (
                "def registered_one():\n"
                "    return 1\n\n"
                "def unregistered_one():\n"
                "    return 2\n"
            )
        },
        register_body=(
            "# Legal claim register\n\n"
            "### F999 — `agent/platform/sample.py`\n\n"
            "Public accessors: `sample.registered_one`.\n\n"
        ),
    )
    result = audit_module.run_audit(root=root)
    assert result.ok is False
    accessor_misses = [e for e in result.unregistered if e.kind == "accessor"]
    assert len(accessor_misses) == 1
    assert accessor_misses[0].name == "unregistered_one"
    assert accessor_misses[0].module == "sample"


def test_exempt_marker_suppresses(tmp_path: Path) -> None:
    root = _write_temp_repo(
        tmp_path,
        platform_files={
            "sample.py": (
                "def registered_one():\n"
                "    return 1\n\n"
                "def helper():  # claim-exempt: internal test helper\n"
                "    return 2\n"
            )
        },
        register_body=(
            "# Legal claim register\n\n"
            "### F999 — `agent/platform/sample.py`\n\n"
            "Public accessors: `sample.registered_one`.\n\n"
        ),
    )
    result = audit_module.run_audit(root=root)
    assert result.ok is True
    assert result.unregistered == []
    exempts = [e for e in result.exempted if e.name == "helper"]
    assert len(exempts) == 1
    assert exempts[0].reason == "internal test helper"


def test_orphan_register_entry_warns(tmp_path: Path) -> None:
    root = _write_temp_repo(
        tmp_path,
        platform_files={
            "sample.py": (
                "def emitter():\n"
                "    return {}\n"
            )
        },
        register_body=(
            "# Legal claim register\n\n"
            "### F999 — `agent/platform/sample.py`\n\n"
            "Public accessors: `sample.emitter`, `sample.zzz_no_code`.\n\n"
        ),
    )
    result = audit_module.run_audit(root=root)
    assert result.ok is True  # orphan is warn-only
    orphan_names = {o.name for o in result.orphaned}
    assert "zzz_no_code" in orphan_names


def test_json_output_shape(tmp_path: Path) -> None:
    root = _write_temp_repo(
        tmp_path,
        platform_files={
            "sample.py": "def rogue():\n    return 0\n",
        },
        register_body=(
            "# Legal claim register\n\n"
            "### F999 — `agent/platform/sample.py`\n\n"
            "No accessors listed yet.\n\n"
        ),
    )
    proc = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--root", str(root), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert isinstance(payload["unregistered"], list)
    assert any(e["name"] == "rogue" for e in payload["unregistered"])
    assert set(payload.keys()) >= {
        "ok", "unregistered", "orphaned", "exempted",
        "audited_modules", "skipped_modules",
    }


def _init_git(root: Path) -> None:
    """Initialise a bare-minimum git repo at ``root``."""
    subprocess.run(
        ["git", "init", "-q", str(root)],
        check=True,
        capture_output=True,
    )


def test_install_hook_idempotent(tmp_path: Path) -> None:
    """Installer: install → reinstall (idempotent) → back up unrelated hook
    → uninstall respects ownership."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_git(root)
    (root / "scripts" / "git-hooks").mkdir(parents=True)
    (root / "scripts").joinpath("check_claim_register.py").write_text("print('ok')\n")
    (root / "scripts" / "git-hooks" / "pre-commit").write_text(
        HOOK_TEMPLATE.read_text()
    )

    report1 = installer_module.install(root)
    assert report1["ok"] is True
    assert report1["action"] == "install"
    hook = root / ".git" / "hooks" / "pre-commit"
    assert hook.is_file()
    assert installer_module.MARKER in hook.read_text()

    report2 = installer_module.install(root)
    assert report2["ok"] is True
    assert report2["action"] == "update"  # marker present -> update path
    assert not (root / ".git" / "hooks" / "pre-commit.bak").exists()

    report_uninstall = installer_module.uninstall(root)
    assert report_uninstall["ok"] is True
    assert report_uninstall["action"] == "uninstall"
    assert not hook.exists()

    hook.write_text("#!/bin/sh\necho unrelated\n")
    report_conflict = installer_module.install(root)
    assert report_conflict["ok"] is True
    assert report_conflict["action"] == "install-with-backup"
    backup = root / ".git" / "hooks" / "pre-commit.bak"
    assert backup.is_file()
    assert "unrelated" in backup.read_text()
    assert installer_module.MARKER in hook.read_text()

    report_reject = installer_module.uninstall(
        root
    )  # marker owned by us -> allowed
    assert report_reject["ok"] is True
    hook.write_text("#!/bin/sh\necho foreign\n")
    report_foreign = installer_module.uninstall(root)
    assert report_foreign["ok"] is False
    assert report_foreign["action"] == "refused"


@pytest.mark.parametrize("cli_flag", ["--dry-run"])
def test_installer_dry_run_no_write(tmp_path: Path, cli_flag: str) -> None:
    """Bonus coverage: --dry-run doesn't write to disk."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_git(root)
    (root / "scripts" / "git-hooks").mkdir(parents=True)
    (root / "scripts" / "git-hooks" / "pre-commit").write_text(
        HOOK_TEMPLATE.read_text()
    )
    report = installer_module.install(root, dry_run=True)
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert not (root / ".git" / "hooks" / "pre-commit").exists()
