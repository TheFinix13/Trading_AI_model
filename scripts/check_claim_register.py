#!/usr/bin/env python3
"""F010 -- claim-register audit.

Walks every ``agent/platform/*.py`` module and asserts that its public
surface is either mentioned in ``company/legal/claim_register.md`` or
explicitly opted out via a ``# claim-exempt: <reason>`` marker.

Exit codes:

- ``0``  clean (or clean + orphan warnings)
- ``1``  at least one unregistered public accessor or unregistered ``#
        claim: NAME`` marker
- ``2``  usage error (bad --root, missing register file)

The pre-commit hook installed by ``scripts/install_git_hooks.py`` runs
this in silent mode; the CI-equivalent test at
``tests/platform/test_claim_register_audit.py`` calls ``run_audit()``
programmatically so misses fail the suite even without the hook.

Design contract (see ``company/sprints/sprint-2-real-trading/F010-*``):

- **Audited modules**: those that appear in a ``### F0##`` heading in
  the register naming an ``agent/platform/<file>.py`` file. Modules not
  mentioned in the register are considered infra glue and skipped
  (they may still emit ``# claim: NAME`` markers, which are audited
  regardless).
- **Public accessor**: a top-level ``def`` / ``async def`` / ``class``
  whose name does not start with ``_``.
- **Registration test**: the accessor's bare name must appear as a
  backticked token anywhere in the register (the parser strips a
  trailing ``()`` and any leading module-dotted prefix so both
  ``performance.get_state`` and ``get_state`` match).
- **Exemption**: an in-line ``# claim-exempt: reason`` comment on the
  ``def`` / ``class`` line (or the immediately preceding line) suppresses
  the check. The reason is echoed by ``--json``.
- **Explicit markers**: any ``# claim: NAME`` comment anywhere in
  ``agent/platform/*.py`` is treated as a claim and must be registered,
  regardless of the enclosing module.

This module has NO runtime dependencies -- stdlib only. The script must
run cleanly on a fresh checkout before ``pip install``.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent
DEFAULT_PLATFORM_DIR = "agent/platform"
DEFAULT_REGISTER_PATH = "company/legal/claim_register.md"

_BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")
_LEADING_IDENT_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)")
_FILE_EXTENSION_TAILS: frozenset[str] = frozenset({
    "py", "md", "json", "jsonl", "toml", "yaml", "yml", "txt", "log",
})
_MODULE_HEADING_RE = re.compile(
    r"^###\s+F\d{3}\s+[\u2014\-].*`agent/platform/([A-Za-z_][\w]*)\.py`",
    re.MULTILINE,
)
_CLAIM_MARKER_RE = re.compile(r"#\s*claim\s*:\s*([A-Za-z_][\w]*)")
_CLAIM_EXEMPT_RE = re.compile(r"#\s*claim-exempt\s*:\s*(.+?)\s*$")


@dataclass
class UnregisteredEntry:
    """One unregistered claim -- ``kind`` is either 'accessor' or 'marker'."""

    module: str
    name: str
    kind: str
    line: int
    file: str


@dataclass
class ExemptEntry:
    module: str
    name: str
    reason: str
    line: int
    file: str


@dataclass
class OrphanEntry:
    """Register-side token with no matching code accessor (warn only)."""

    module: str
    name: str


@dataclass
class AuditResult:
    unregistered: list[UnregisteredEntry] = field(default_factory=list)
    orphaned: list[OrphanEntry] = field(default_factory=list)
    exempted: list[ExemptEntry] = field(default_factory=list)
    audited_modules: list[str] = field(default_factory=list)
    skipped_modules: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unregistered

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "unregistered": [asdict(e) for e in self.unregistered],
            "orphaned": [asdict(e) for e in self.orphaned],
            "exempted": [asdict(e) for e in self.exempted],
            "audited_modules": list(self.audited_modules),
            "skipped_modules": list(self.skipped_modules),
        }


def _extract_module_headings(text: str) -> set[str]:
    """Return the set of `agent/platform/<file>.py` filenames that
    appear as an audited module in the register (based on ``### F0##``
    headings)."""
    return set(_MODULE_HEADING_RE.findall(text))


def _extract_register_tokens(text: str) -> set[str]:
    """Return the set of identifiers backticked in the register.

    The register uses backticks around both bare names (``\u0060fn\u0060``) and
    full signatures (``\u0060fn(arg) -> type\u0060``); this extractor takes
    the identifier at the START of every backticked span, so both work.
    Dotted forms register their tail too (``performance.get_state`` →
    also registers ``get_state``).
    """
    out: set[str] = set()
    for span in _BACKTICK_SPAN_RE.findall(text):
        head = _LEADING_IDENT_RE.match(span)
        if not head:
            continue
        tok = head.group(1)
        out.add(tok)
        if "." in tok:
            tail = tok.rsplit(".", 1)[-1]
            if tail not in _FILE_EXTENSION_TAILS:
                out.add(tail)
    return out


def _register_tokens_per_module(text: str) -> dict[str, set[str]]:
    """Split the register on ``### `` headings and, for each heading that
    names an ``agent/platform/<file>.py`` module, collect the DOTTED
    ``module.accessor`` identifiers backticked inside that section.

    Used for orphan detection: ``file → {module.accessor tokens}``.
    Only fully-dotted forms are tracked (bare identifiers inside a
    section are often field names / status strings / type names, not
    accessors -- too many false positives).
    """
    sections: dict[str, set[str]] = {}
    heading_hits = list(re.finditer(
        r"^###\s+.*$",
        text,
        re.MULTILINE,
    ))
    for i, hit in enumerate(heading_hits):
        heading = hit.group(0)
        match = re.search(
            r"`agent/platform/([A-Za-z_][\w]*)\.py`", heading)
        if not match:
            continue
        module_name = match.group(1)
        start = hit.end()
        end = heading_hits[i + 1].start() if i + 1 < len(heading_hits) else len(text)
        section = text[start:end]
        tokens: set[str] = set()
        for span in _BACKTICK_SPAN_RE.findall(section):
            head = _LEADING_IDENT_RE.match(span)
            if not head:
                continue
            tok = head.group(1)
            if "." not in tok:
                continue
            prefix, tail = tok.rsplit(".", 1)
            if prefix != module_name:
                continue
            if tail.startswith("_"):
                continue
            if tail in _FILE_EXTENSION_TAILS:
                continue
            tokens.add(tail)
        sections.setdefault(module_name, set()).update(tokens)
    return sections


def _iter_platform_modules(platform_dir: Path) -> Iterable[Path]:
    for path in sorted(platform_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        yield path


def _line_exempts(source_lines: list[str], line_no: int) -> str | None:
    """Return the exempt reason if the ``def``/``class`` at ``line_no``
    or the line immediately above carries a ``# claim-exempt: reason``
    comment; None otherwise."""
    for candidate_idx in (line_no - 1, line_no - 2):
        if 0 <= candidate_idx < len(source_lines):
            m = _CLAIM_EXEMPT_RE.search(source_lines[candidate_idx])
            if m:
                return m.group(1).strip()
    return None


def _module_public_accessors(
    source: str,
) -> list[tuple[str, int]]:
    """Return ``[(name, line_no), ...]`` for every top-level ``def``,
    ``async def``, or ``class`` whose name does not start with ``_``."""
    out: list[tuple[str, int]] = []
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            if not node.name.startswith("_"):
                out.append((node.name, node.lineno))
    return out


def _find_claim_markers(source: str) -> list[tuple[str, int]]:
    """Return ``[(name, line_no), ...]`` for every ``# claim: NAME``
    comment in ``source`` (found via ``tokenize`` so backtick-strings
    and shebangs don't false-positive)."""
    out: list[tuple[str, int]] = []
    try:
        tokens = tokenize.generate_tokens(iter(source.splitlines(True)).__next__)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            match = _CLAIM_MARKER_RE.search(tok.string)
            if match:
                out.append((match.group(1), tok.start[0]))
    except tokenize.TokenizeError:
        for line_no, line in enumerate(source.splitlines(), start=1):
            match = _CLAIM_MARKER_RE.search(line)
            if match:
                out.append((match.group(1), line_no))
    return out


def run_audit(
    *,
    root: Path | None = None,
    platform_subdir: str = DEFAULT_PLATFORM_DIR,
    register_subpath: str = DEFAULT_REGISTER_PATH,
) -> AuditResult:
    """Run the audit and return an :class:`AuditResult`.

    ``root`` defaults to the repo root; the two subpaths default to the
    standard locations. The function makes no side effects other than
    reading files.
    """
    base = Path(root) if root is not None else REPO_ROOT_DEFAULT
    platform_dir = base / platform_subdir
    register_path = base / register_subpath

    if not platform_dir.is_dir():
        raise FileNotFoundError(f"platform dir not found: {platform_dir}")
    if not register_path.is_file():
        raise FileNotFoundError(f"claim register not found: {register_path}")

    register_text = register_path.read_text(encoding="utf-8")
    audited_files = _extract_module_headings(register_text)
    register_tokens = _extract_register_tokens(register_text)
    per_module_tokens = _register_tokens_per_module(register_text)

    result = AuditResult()

    per_module_accessors_seen: dict[str, set[str]] = {}

    for module_path in _iter_platform_modules(platform_dir):
        module_name = module_path.stem
        source = module_path.read_text(encoding="utf-8")
        source_lines = source.splitlines()

        markers = _find_claim_markers(source)
        for name, line_no in markers:
            if name not in register_tokens:
                result.unregistered.append(UnregisteredEntry(
                    module=module_name,
                    name=name,
                    kind="marker",
                    line=line_no,
                    file=str(module_path.relative_to(base)),
                ))

        if module_name not in audited_files:
            result.skipped_modules.append(module_name)
            continue

        result.audited_modules.append(module_name)
        seen = per_module_accessors_seen.setdefault(module_name, set())
        try:
            accessors = _module_public_accessors(source)
        except SyntaxError as exc:
            result.unregistered.append(UnregisteredEntry(
                module=module_name,
                name=f"__parse_error__: {exc.msg}",
                kind="accessor",
                line=exc.lineno or 0,
                file=str(module_path.relative_to(base)),
            ))
            continue

        for name, line_no in accessors:
            seen.add(name)
            exempt_reason = _line_exempts(source_lines, line_no)
            if exempt_reason is not None:
                result.exempted.append(ExemptEntry(
                    module=module_name,
                    name=name,
                    reason=exempt_reason,
                    line=line_no,
                    file=str(module_path.relative_to(base)),
                ))
                continue
            if name not in register_tokens:
                result.unregistered.append(UnregisteredEntry(
                    module=module_name,
                    name=name,
                    kind="accessor",
                    line=line_no,
                    file=str(module_path.relative_to(base)),
                ))

    for module_name, tokens in per_module_tokens.items():
        seen = per_module_accessors_seen.get(module_name, set())
        for token in tokens:
            if not token.isidentifier():
                continue
            if token in seen:
                continue
            result.orphaned.append(OrphanEntry(module=module_name, name=token))

    result.audited_modules.sort()
    result.skipped_modules.sort()
    result.unregistered.sort(key=lambda e: (e.module, e.line, e.name))
    result.exempted.sort(key=lambda e: (e.module, e.line, e.name))
    result.orphaned.sort(key=lambda e: (e.module, e.name))
    return result


def _format_human(result: AuditResult) -> str:
    lines: list[str] = []
    lines.append(
        f"Audited {len(result.audited_modules)} module(s), "
        f"skipped {len(result.skipped_modules)} (no register heading)."
    )
    if result.exempted:
        lines.append(f"Exempted: {len(result.exempted)} accessor(s).")
    if result.unregistered:
        lines.append("")
        lines.append("UNREGISTERED CLAIMS:")
        for entry in result.unregistered:
            lines.append(
                f"  {entry.file}:{entry.line}  {entry.kind}  {entry.module}.{entry.name}"
            )
        lines.append("")
        lines.append(
            "Fix: register each name in company/legal/claim_register.md under the "
            "matching module heading, or mark the accessor '# claim-exempt: <reason>'."
        )
    if result.orphaned:
        lines.append("")
        lines.append("WARNING -- register entries with no matching code:")
        for entry in result.orphaned:
            lines.append(f"  {entry.module}.{entry.name}")
        lines.append(
            "This is a warning (exit 0). Legal owns the register text -- remove "
            "or add '# claim-exempt' to acknowledge."
        )
    if result.ok and not result.orphaned:
        lines.append("OK -- claim register is in sync.")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        default=None,
        help="Repo root (default: parent of this script).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout instead of human text.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress human output on success. Overridden by --json.",
    )
    parser.add_argument(
        "--fail-on-orphan",
        action="store_true",
        help="Escalate orphan warnings to exit 1 (default: warn only).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root).resolve() if args.root else REPO_ROOT_DEFAULT
    try:
        result = run_audit(root=root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        json.dump(result.as_dict(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        if result.ok and not result.orphaned and args.quiet:
            pass
        else:
            print(_format_human(result))
    if not result.ok:
        return 1
    if args.fail_on_orphan and result.orphaned:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
