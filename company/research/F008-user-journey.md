# F008 -- User journey: first-time setup

_Sprint 1, Onboarding UX lane, 2026-07-21._

## Target user segment

Same as F006 / F007: a single retail forex trader on their own
machine. They just cloned the repo, installed the requirements,
and ran `serve_platform.py`. The very first thing they see is the
Blue Lock hub -- except they haven't connected a broker yet, so it
would be dead weight. We short-circuit that by redirecting them
straight into onboarding.

## Jobs to be done

1. **Tell them what Blue Lock is (and isn't) up front.** Hobbyist,
   single-user, not a regulated adviser. Get the framing right on
   step 1 before we ask for any input.
2. **Handle the OS keychain vs. encrypted-file question honestly.**
   On macOS the keychain works, so we let the user skip the
   passphrase and move on. On a headless Linux install, we ask
   for a >= 12-char passphrase. The wizard adapts.
3. **Send them to the broker wizard, then bring them back.** We
   don't try to embed F007's flow inline -- we open it in a new
   tab and let the user return here when it's saved.
4. **Give them a working default.** Pick EURUSD out of the box.
   They can add GBPUSD / USDCAD without leaving the step.
5. **End with a recap they can double-check.** Passphrase state,
   broker state, default pairs -- three fields, one screen, one
   button.

## Non-jobs

- **Multi-user account provisioning.** D052 defers.
- **Native mobile onboarding.** Not this sprint.
- **Broker onboarding UI beyond a link.** F007 owns that experience.
- **Any subscription / payment / license step.** No commerce today.

## The five-step walk-through

1. **Welcome (`welcome`)** -- one paragraph brand copy, one Legal
   pass-through paragraph (verbatim from
   `company/legal/F008-onboarding-agreement.md`), one Continue button.
2. **Passphrase (`passphrase`)** -- one password field, one "skip
   because I have a keychain" checkbox. Server-side validation
   returns a friendly failure message if the passphrase is too
   short OR the checkbox was ticked when no keychain exists.
3. **Broker (`broker`)** -- link to `/settings/broker` opens in a
   new tab. Continue button re-checks broker state on click; won't
   advance until at least one alias is saved.
4. **Pairs (`pairs`)** -- three checkboxes (EURUSD pre-checked).
   At least one required. Server-side stored via `set_default_pairs`.
5. **Confirm (`confirm`)** -- recap card showing passphrase state
   ("set" / "skipped (keychain)"), broker state, pair list.
   Finish button calls `POST /api/onboarding/complete` and
   redirects to `/` after 1.2 s.

## Accessibility notes

- Stepper is `role="progressbar"` with `aria-label`.
- Every button is keyboard-focusable and has a visible focus outline
  via the shared `_BASE_CSS` styles.
- Password field uses `autocomplete="new-password"` so 1Password
  and Chrome's password manager surface the "generate strong
  passphrase" affordance without pre-filling.
- All step transitions scroll the viewport to top so users on
  short screens don't miss the new heading.

## Success criteria for this journey

- A cold install can go from `/` (302 to `/onboarding`) → finish →
  `/` (200) in < 5 minutes without external docs.
- `/settings/reset-install` returns the user to a clean state and
  restarts the journey; no leftover state anywhere.
- Every step renders correctly at 375 px wide.
- The Legal agreement text is visible on step 1 without scrolling
  past the fold (verified in the design mock's mobile column).
- No plaintext passphrase, install token, or broker password
  crosses the network except during the two `/api/onboarding/passphrase`
  and F007 `/api/broker/save` POSTs.
