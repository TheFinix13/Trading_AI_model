# F006 — Secrets-at-rest disclaimer

- **Sprint:** sprint-1-access
- **Feature:** F006 (encrypted credential storage + install-scoped auth)
- **Author:** Legal
- **Date:** 2026-07-21
- **Status:** approved for verbatim rendering on the /onboarding flow
  and the /hq install-fingerprint chip.

## User-facing text (verbatim)

Two disclaimers ship in this feature. Both render exactly as below —
personas do not paraphrase.

### 1. Encrypted-at-rest reassurance

> **Your credentials are stored on your device.** When your system
> supports it (macOS Keychain, Windows Credential Manager, or the
> Linux Secret Service), Blue Lock uses that store directly. When it
> doesn't, we fall back to an AES-encrypted file (`credentials.enc`)
> derived from your setup passphrase. Blue Lock's server never
> receives your credentials in plaintext except momentarily during a
> connection test.

### 2. Reset warning

> **Resetting this install clears your token AND your saved broker
> credentials.** You'll go through onboarding again. Nothing is sent
> anywhere — the reset is local to this device.

## Compliance notes

- The word "encryption" is used in the technical sense (Fernet =
  AES-128-CBC + HMAC-SHA256). If a future feature relaxes this to
  something weaker, Legal must re-review the copy.
- We DO NOT claim "military grade", "zero-knowledge", or "end-to-end"
  — none apply to a single-user local install and Legal has flagged
  these phrases as banned in `company/brand/copy.md` §Banned phrases.
- We DO NOT collect or transmit the passphrase. This is a hard product
  invariant — if a future feature adds a passphrase-transmission
  path, Legal + Security review it before Brand touches the copy.

## Threat model summary (from Security)

| Threat | Mitigation |
|---|---|
| Attacker reads `credentials.enc` off disk | Fernet-encrypted; PBKDF2-SHA256 200k iter; salt is per-install and stored beside the file (attacker still needs the passphrase to decrypt). |
| Attacker snoops OS keychain | OS-provided access control (keychain, credential manager). |
| Log-scraper harvests secrets from stdout | `RedactingFilter` scrubs `password=`, `token=`, and >=24-char URL-safe blobs before any log line lands. |
| CSRF / XSS on `/settings/broker` | `POST` endpoints; `SameSite=Strict` cookie; no user-generated HTML; `X-Bluelock-Token` header preferred over cookies. |
| Path traversal via namespace / key | Regex-enforced allowed chars + explicit ".." check. |
| Empty / control-char DoS | Fixed 8k value cap + control-char reject. |

## Claim-register entries

Every accessor in `agent/platform/{credentials,auth}.py` is listed in
`company/legal/claim_register.md` §F006. If Sprint 2+ changes the
public surface, Legal re-reviews.

## Verdict

**pass** — copy is verbatim-ready; disclaimers cover the honest
security posture for a single-user install without over-claiming;
threat model exercised by the tests in `tests/security/`.
