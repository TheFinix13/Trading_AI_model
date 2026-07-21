# F006 — user-journey memo (research stage)

- **Feature:** F006 encrypted credential storage + install-scoped auth
- **Author:** UX Researcher
- **Date:** 2026-07-21
- **Handoff in:** `company/handoffs/F006-cpo-to-ux_researcher.json`

## Target user segment (revalidated for Sprint 1)

- **Retail forex trader** running the platform on their own machine
  (Mac dev, Windows VM in production).
- **One MT5 account** (Exness Demo by default, per D052) — no
  multi-tenancy yet.
- Willing to install a Python app on their own machine; NOT willing to
  hand their broker password to a hosted service.

## Job-to-be-done

> "I want to feel that my broker password is safe **before** I type it
> into a browser tab — even if that tab is the Blue Lock platform I
> just installed."

## Sub-jobs (ordered)

1. **Prove the platform doesn't hold my password in plaintext.** Users
   are past the "trust me, bro" phase — they want a claim that maps to
   a code path they can read. Enter the `claim_register.md` audit path
   (§6.3): every field emitted by `credentials.py` traces to a code
   path.
2. **Prove I can wipe my install if it breaks.** `/settings/reset-
   install` (bundled into F008 per spec) has to visibly clear the
   token, not just "log the user out".
3. **See at a glance that I'm authenticated.** Fingerprint on `/hq`
   (as a small chip in the top-right, not the whole token).

## Non-jobs (out of scope)

- SSO / OAuth. Sprint 5+.
- Team-based sharing. Sprint 5+.
- "Forgot passphrase" recovery. Deferred; we log the passphrase
  requirement in the wizard.

## Accessibility notes

- Fingerprint chip must survive colour-blind viewing (relies on
  monospace + ellipsis, not colour).
- Passphrase input in F008 must have `type="password"`,
  `autocomplete="new-password"`, and a "reveal" toggle for the sighted
  user who wants to sanity-check what they typed.
- Screen-reader label on the fingerprint: "Install fingerprint: eight
  characters, ellipsis, eight characters."

## Why single-user is right (per D052)

The audience for Sprint 1 is one user per install. Multi-user auth
introduces a threat model (privilege escalation, session hijack,
IDOR) that a single-user model doesn't have. Deferring lets us ship
the credential story cleanly in Sprint 1 without invalidating it in
Sprint 5 when multi-user lands as a genuine feature — the install
token graduates to a session token per user at that point.

## Handoff to UI Designer

- Mocks must include the fingerprint chip, its position on `/hq`, and
  the disabled state (before install is configured, chip reads "Not
  configured yet").
- Copy passes through Brand.
