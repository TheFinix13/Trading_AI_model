# F010 — Claim-register audit pre-commit hook

- **Sprint:** sprint-2-real-trading
- **Priority:** P0
- **Lane:** Sprint 1 carry-over (D062) — closes the §6.3 automation
  gap flagged in D047.
- **Consumes:** `company/legal/claim_register.md` (Sprint 1 seed).
- **Consumed by:** F011, F012, F013, F014 — every new public field
  they add must pass the audit before commit.
- **Feature flags:** infra-only. No `security` / `legal` / `research`
  stages fire (no user-facing surface).

## Problem statement

Review-chain §6.3 registered the claim-register audit but Sprint 1
deferred the automation. Without automation, every new `agent/platform/`
public accessor is a Legal-review-by-vibes situation.

## Scope (in)

### `scripts/check_claim_register.py` (new)

Walks every `agent/platform/*.py` module (excluding `__init__.py`),
extracts every **public claim** (a top-level `def` or module-level
constant whose name does not start with `_`), and cross-references
`company/legal/claim_register.md`. Discovery is AST-based, not text-
based, so cosmetic doc drift never trips a false positive.

Discovery rules:

1. **Public module-level constants** — `NAME = ...` where `NAME` is
   uppercase or camelCase, does not start with `_`. Excluded:
   pattern regexes, logger, imports.
2. **Public functions** — `def foo(...):` where `foo` does not start
   with `_`. Return type is inspected for `dict` / `list[dict]`; the
   function's docstring is scanned for `# claim: <field>` markers so
   engineers can enumerate emitted fields explicitly.
3. **Public classes** — `class Foo:` where `Foo` does not start
   with `_`, and every public method / attribute is enumerated.

The register is read once as markdown, split by `### F0##` heading,
and each row's first column (module or accessor) matched.

Output modes:

- Default (called with no args): prints unregistered claims + registered
  entries with no matching code, exits `0` on clean, `1` on any
  unregistered claim, `0` (warning only) on registered-but-missing.
- `--json`: emits `{"unregistered": [...], "orphaned": [...]}`.
- `--fix`: NOT implemented in F010 (deliberately manual — Legal owns
  the register text).

### `scripts/git-hooks/pre-commit` (new)

Bash shim:

```bash
#!/usr/bin/env bash
set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
python3 "$REPO_ROOT/scripts/check_claim_register.py" >&2
```

### `scripts/install_git_hooks.py` (new)

User opts in explicitly:

```
python3 scripts/install_git_hooks.py
```

Copies `scripts/git-hooks/pre-commit` → `.git/hooks/pre-commit`,
sets executable, backs up any prior hook to `pre-commit.bak`.
Idempotent. Prints a friendly summary. **No auto-install.**

### CI-equivalent test

`tests/platform/test_claim_register_audit.py` (8 tests) runs the
audit programmatically. Even without the git-hook installed, an
unregistered claim fails the test suite → CI catches it.

Test list:
1. audit passes on the current repo (Sprint 1 state + new F009-F014
   entries added in each feature's commit).
2. Feature module without a matching heading → unregistered claim
   reported.
3. Register entry with no matching accessor → orphaned entry warning
   (not fail).
4. `# claim: FOO` marker in a docstring where `FOO` is not in the
   register → unregistered claim.
5. Private accessor (`_helper`) never surfaced.
6. JSON output shape.
7. Install-hook installer works idempotently on a tmp git repo.
8. Red-line: add a `SPARE_CLAIM` constant to a fixture module, run
   the audit, expect exit 1 with a diagnostic message.

## Scope (out)

- `--fix` mode (Legal owns register text).
- Auto-install (respecting user autonomy — an opt-in install script
  runs on demand).
- Scanning `agent/live/*`, `agent/risk/*`, `agent/squad/*` (D065
  invariant — those modules don't emit public product claims from
  Sprint 2's scope).

## Legal

None — F010 is infrastructure. Its output is what Legal reviews.

## UX

None — CLI script.

## Acceptance

- All 8 tests pass.
- Full suite green.
- `python3 scripts/check_claim_register.py` on the current repo exits
  0 (with F009+ entries registered).
- Adding a fake `SPARE_CLAIM` constant to a platform module and
  re-running exits 1.
- Pre-commit hook template installs cleanly and blocks a commit that
  would leak an unregistered field.

## Files touched

New:
- `scripts/check_claim_register.py`
- `scripts/git-hooks/pre-commit`
- `scripts/install_git_hooks.py`
- `tests/platform/test_claim_register_audit.py`
- `company/qa/F010-verdict.md`
- Handoffs.

Edited:
- `company/ledger/{company_state.json, decisions_log.md}`
