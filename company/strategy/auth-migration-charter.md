# Auth migration charter — install-token → multi-user accounts

- **Date:** 2026-07-24 · **Decision:** D115 (adopted as planning
  baseline; implementation deferred to its own sprint)
- **Authors:** CTO (The Anri) + Security personas — design only.
  This charter contains ZERO implementation; no code changes ride it.
- **Predecessors:** D052 (Sprint 1 minimal-auth scope), F006/F009 (as
  shipped), `sellability-gaps.md` gap 1 ("PARTIALLY COVERED — needs
  its own charter" — this is that charter).

## 1. Motivation

Today one install = one user: F006 stores secrets in the OS keyring
(Fernet-file fallback), F009 layers rotation, session expiry and rate
limiting on a single install-scoped token, and localhost binds are
open by design (D052). That model cannot serve two customers: there
is no second identity to isolate, bill, support, or revoke. Every
commercial gap in the sellability memo (billing, support, GDPR
data-export/deletion) presupposes "a user" as a first-class object.
Selling to more than one customer therefore requires this migration —
and doing the design now, before Sprint 3 ships more public surface,
keeps later features from baking in single-user assumptions.

## 2. Target architecture (Phase 1 scope)

**Accounts.** A local account store: `account_id` (opaque),
`username`, credential hash (argon2id or equivalent memory-hard KDF —
final choice at spec time), `role`, `created_at`, `status`. No email
verification in Phase 1 (local installs have no mail path); recovery
is owner-mediated (see §5).

**Credential storage per user.** The F006 keyring/Fernet machinery is
retained and *namespaced*: secrets move from
`namespace="bluelock"` to `namespace="bluelock/<account_id>"`; each
user's broker credentials, tokens, and config state live under their
own namespace and (where file-backed) their own
`<config_dir>/users/<account_id>/` subtree. No cross-user read path
exists at any layer — enforced in the storage API, not in callers.

**Session model.** Login → server-issued opaque session token (same
`secrets.token_urlsafe` family as F009), bound to `account_id`,
expiring on the existing F009 session-expiry schedule; rotation and
rate limiting carry over per account instead of per install.
Localhost-open (D052) **ends** at this migration: with more than one
account on a box, localhost is no longer a trust boundary. A
single-account install may keep a compatibility toggle; multi-account
mode forces authentication on every bind.

**Role split.** Two roles only in Phase 1: **owner** (everything
today's user can do: broker credentials, kill switches, approvals,
live-mode ceremony, account administration) and **viewer** (read-only
surfaces: /performance, /players, /highlights, /leaderboard,
/research, /hq dashboards; no settings, no approvals, no execution
surface). No custom roles, no permission matrix — two hardcoded
roles keep the security review tractable.

## 3. The P0 invariant under multi-user

The live-mode-off invariant (pinned by
`tests/security/test_live_mode_off_invariant.py`, 23 cases) is
install-scoped today: one ceremony, one `live_mode_enabled` flag, one
approval queue. **The invariant extension this charter locks:**

> Live-mode enablement, order approval, and execution authority bind
> to an **owner account**, not to an install. Every gate in the
> four-gate composition (`live_mode_enabled AND not is_killed AND
> risk-budget AND approval`) evaluates in the context of the
> *account* that performed the ceremony; the F013 ceremony records
> `account_id`; the F018 executor refuses any approval whose
> approving account is not an owner in good standing at execution
> time (re-checked fresh, matching the existing
> re-run-`can_send_live_order`-before-send doctrine).

Consequences: viewers structurally cannot arm, approve, or execute
anything (role check inside the gates, not the UI); disabling an
owner account instantly de-authorises their pending approvals
(single-use entries die with the account); kill switches remain
GLOBAL — any owner can kill, killing requires no ceremony, and the
safety-direction-is-frictionless doctrine survives unchanged. The P0
test file is EXTENDED with account-scoped cases, never weakened —
same rule Sprints 2/2b followed.

## 4. Migration path for the existing single-user install

The VM deployment must not break. On first boot after the migration
ships: if no account store exists and F006 install-scoped secrets do,
the platform creates a **default owner account**, adopts the existing
keyring namespace and config-dir contents into that account's
namespace, and honours the existing install token as that owner's
credential until first login sets a password. Zero manual steps for
the current deployment; the runbook gains one section documenting the
adoption. Rollback: the adoption is additive (originals retained
until the owner confirms), so reverting the binary restores today's
behaviour.

## 5. Phasing

**Phase 1 — local multi-account (chartered here).** Everything in §2
on a single install. Owner-mediated recovery: a locked-out user asks
the owner to reset; the owner authenticates via keyring-held owner
credential. No network exposure change beyond ending localhost-open
in multi-account mode.

**Phase 2 — hosted multi-tenant (NOT chartered — flagged).** Serving
accounts over the public internet is a different risk class:
**Phase 2 requires external legal/compliance review (ToS, privacy
policy, GDPR/CCPA data-residency posture, financial-promotions rules)
AND the Sprint 5 external pen test BEFORE any commitment is made** —
matching sellability-gaps items 6 and 7 and `escalation.md`'s
money/brand/legal reservations. Nothing in Phase 1 may assume Phase 2
happens (no hosted-only abstractions).

## 6. Explicitly NOT decided by this charter

- **Hosting** — where/whether Phase 2 runs (VPS, cloud, on-prem
  installs only). CEO + Finance decision with real cost data.
- **Billing/licensing** — Sprint 6 territory; accounts are a
  prerequisite, not a billing design.
- **IdP choice** — whether Phase 2 uses local accounts, OAuth/OIDC
  (and which provider), or passkeys. Deliberately open; Phase 1's
  local store must not preclude any of them.
- **2FA mechanics** — Sprint 5 scope per the backlog; the account
  model must leave room (per-account secret slots exist), the method
  is not chosen here.
- **Team/organisation constructs** (shared squads, multi-owner
  installs beyond "several owners of one box") — no design until a
  customer shape demands it.

## 7. Sequencing + review chain

Implementation is its own sprint (candidate: Sprint 4/5 slot, after
Sprint 3 and ideally overlapping the shadow window). It enters the
standard review chain at `spec` with `auth: true`,
`credentials: true`, `security_relevant: true`, `legal_relevant:
true` — security AND legal stages fire; CEO signoff mandatory (P0).
The claim register gains no entries from this charter (no public
numbers); the spec-stage feature will register any account-related
UI claims it introduces. Until that sprint ships, every new feature
(Sprint 3 included) must avoid hard-coding install-scoped identity
assumptions in NEW code where an account seam is trivially available
— the CTO checks this at architecture review.

## 8. Success criteria for the eventual implementation sprint

- Two accounts on one install with disjoint credential namespaces;
  a viewer cannot reach any mutating endpoint (test-enforced).
- P0 invariant file extended to account scope; 23 existing cases
  untouched above the extension marker.
- Existing VM install upgrades with zero manual steps and no loss of
  broker credentials, kill-switch state, or approval history.
- Full suite green; claim audit green; security + legal reviews on
  tape.
