#!/usr/bin/env python3
"""F010 -- opt-in installer for the pre-commit claim-register audit hook.

Behaviour:

- If ``.git/hooks/pre-commit`` does not exist, copy
  ``scripts/git-hooks/pre-commit`` in and set it executable.
- If it exists and already carries our marker
  (``blue-lock:claim-register-audit:v1``), rewrite it in place -- this
  is the idempotent update path.
- If it exists but does NOT carry our marker, back it up to
  ``.git/hooks/pre-commit.bak`` (unless that path already exists, in
  which case we refuse and let the user reconcile).
- ``--uninstall`` removes the hook if (and only if) it carries our
  marker.
- ``--dry-run`` prints what would happen without touching disk.

The hook itself is intentionally tiny: it shells out to
``scripts/check_claim_register.py``. Users are free to write their own
hook chain; the installer preserves any pre-existing hook via
``.bak``.
"""
from __future__ import annotations

import argparse
import shutil
import stat
import sys
from pathlib import Path

MARKER = "blue-lock:claim-register-audit:v1"
REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent
SOURCE_HOOK = "scripts/git-hooks/pre-commit"


def _git_hooks_dir(root: Path) -> Path:
    return root / ".git" / "hooks"


def _find_source(root: Path) -> Path:
    src = root / SOURCE_HOOK
    if not src.is_file():
        raise FileNotFoundError(
            f"hook template not found: {src} (expected relative to {root})"
        )
    return src


def _has_marker(path: Path) -> bool:
    try:
        return MARKER in path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return False


def install(root: Path, *, dry_run: bool = False) -> dict:
    """Install / update the hook. Returns a report dict."""
    src = _find_source(root)
    hooks_dir = _git_hooks_dir(root)
    if not hooks_dir.is_dir():
        raise FileNotFoundError(
            f".git/hooks/ not found at {hooks_dir}. Is this a git repo?"
        )
    dst = hooks_dir / "pre-commit"
    action = "install"
    backup: Path | None = None
    if dst.exists():
        if _has_marker(dst):
            action = "update"
        else:
            backup = hooks_dir / "pre-commit.bak"
            if backup.exists():
                return {
                    "ok": False,
                    "action": "refused",
                    "reason": (
                        f"An unrelated pre-commit hook exists at {dst} and a "
                        f"backup already exists at {backup}; refusing to "
                        "overwrite. Reconcile manually."
                    ),
                    "hook_path": str(dst),
                    "backup_path": str(backup),
                }
            action = "install-with-backup"
    report = {
        "ok": True,
        "action": action,
        "hook_path": str(dst),
        "backup_path": str(backup) if backup else None,
        "source": str(src),
        "dry_run": dry_run,
    }
    if dry_run:
        return report
    if backup is not None:
        shutil.copy2(dst, backup)
    shutil.copyfile(src, dst)
    mode = dst.stat().st_mode
    dst.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return report


def uninstall(root: Path, *, dry_run: bool = False) -> dict:
    """Uninstall only when the hook carries our marker."""
    hooks_dir = _git_hooks_dir(root)
    dst = hooks_dir / "pre-commit"
    if not dst.exists():
        return {"ok": True, "action": "noop", "hook_path": str(dst)}
    if not _has_marker(dst):
        return {
            "ok": False,
            "action": "refused",
            "reason": (
                f"pre-commit at {dst} does not carry the Blue Lock marker; "
                "refusing to remove someone else's hook."
            ),
            "hook_path": str(dst),
        }
    report = {"ok": True, "action": "uninstall", "hook_path": str(dst), "dry_run": dry_run}
    if not dry_run:
        dst.unlink()
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=None,
                        help="Repo root (default: parent of this script)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing to disk.")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove the hook (only if it carries the Blue Lock marker).")
    parser.add_argument("--quiet", action="store_true", help="Suppress human output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve() if args.root else REPO_ROOT_DEFAULT
    try:
        if args.uninstall:
            report = uninstall(root, dry_run=args.dry_run)
        else:
            report = install(root, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not args.quiet:
        if report.get("ok"):
            print(f"{report['action']}: {report['hook_path']}")
            if report.get("backup_path"):
                print(f"  backed up prior hook -> {report['backup_path']}")
            if report.get("dry_run"):
                print("  (dry-run; no changes on disk)")
        else:
            print(f"REFUSED: {report.get('reason')}", file=sys.stderr)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
