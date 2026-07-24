# Test-suite conventions

## No secret-shaped literals in tests — generate at runtime (D109)

This is a public repo monitored by GitGuardian. Password/token-shaped
string literals in test files get flagged as leaked secrets (incidents
#35143401, #35027049 were false positives on fixture passphrases and a
deliberately fake base64 blob) and every new incident emails the CEO.

Rules for any new or edited test (and non-test helpers like
`scripts/dogfood_personas.py`):

1. **Fixture passphrases**: `credentials.set_encrypted_file_passphrase(_secrets.token_hex(16))`
   — never a string literal. If the same passphrase must be reused later
   in the file (re-opening the credential bag), hoist one generated value
   to module level and use it in both places.
2. **Fake passwords / tokens / sentinels with leak assertions**
   (`assert pw not in output`): hoist ONE runtime-generated value
   (`"fixture-pw-" + _secrets.token_hex(6)`, `_secrets.token_urlsafe(26)`)
   and use the same variable on both sides. Never assert against a
   literal copy of the secret.
3. **Dummy passwords where only validity matters**: use obviously
   non-secret constructions like `"x" * 12` — scanners ignore repeated
   characters.
4. **High-entropy blobs** (base64 etc.): build them at runtime, e.g.
   `base64.b64encode(b"foobarbazqux" + b"doabc1234567").decode()`.
   Keep the length/charset preconditions the test relies on (e.g. the
   redaction filter's `URL_SAFE_TOKEN_RE` needs ≥ 24 url-safe chars) and
   assert them explicitly if they are load-bearing.
5. **Production code (`agent/`)** must never need this treatment: real
   secrets live in the OS keyring / encrypted bag, never in source. If
   you find a secret-shaped literal in production code, report it —
   don't silently patch it.

Verification sweep (should return nothing secret-shaped):

```bash
rg -n 'set_encrypted_file_passphrase\("[^"]+"\)' tests/ scripts/
rg -n 'password\s*=\s*"[^"]{6,}"' tests/ scripts/ --pcre2
rg -n '"[A-Za-z0-9+/=_-]{24,}"' tests/ scripts/   # residue = paths/identifiers only
```
