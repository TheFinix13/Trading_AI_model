# F010 — QA verdict

- **Feature:** F010 claim-register audit (pre-commit hook + CI-equivalent test)
- **Timestamp:** 2026-07-22T01:25:00Z
- **Verdict:** **pass**

## Evidence

| Artifact | Result |
|---|---|
| `.venv/bin/python -m pytest tests/platform/test_claim_register_audit.py -v` | 9 passed, 0 failed |
| `.venv/bin/python scripts/check_claim_register.py` | exit 0, "OK -- claim register is in sync" |
| `.venv/bin/python -m pytest -q` (full suite) | 1295 passed, 1 skipped (playwright cache, pre-existing) |

## Acceptance criteria (from spec)

- [x] All 8 tests pass (delivered 9)
- [x] Full suite green
- [x] Audit exits 0 on current repo with F009+ entries registered
- [x] Adding a fake `SPARE_CLAIM` constant fails the audit (`test_unregistered_marker_fails`, `test_unregistered_accessor_fails`)
- [x] Pre-commit hook template installs cleanly (`test_install_hook_idempotent`)
- [x] Installer is idempotent (marker-based)
- [x] Installer refuses to clobber a foreign hook without a `.bak`

## Risk notes

- No user-visible surface; no Legal / Security stages fire.
- Cross-repo edits are documentation-only (register table rows, exempt markers).
- Zero runtime behaviour change — the audit runs offline; the hook only fires if the user opts in.
- No secrets, no network I/O, no MT5.

## Sign

- QA: **pass** → CPO signoff on behalf of CEO (F010 is infra, no CEO letter required).
