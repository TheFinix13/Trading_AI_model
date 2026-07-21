# F008 -- UI mocks: first-time setup wizard

_Sprint 1, Onboarding UX lane, 2026-07-21._

Wizard lives at `/onboarding`. Renders the top nav (no active pill --
`onboarding` is not a permanent top-level route) plus a 640 px column
containing a five-pill progress stepper and one active step card.

## Visual system

- Reuses `_BASE_CSS` (dark theme tokens).
- Reuses `_SKELETON_CSS` for potential in-flight state on step
  transitions.
- Additive primitives under `_ONBOARDING_CSS`:
  - `.onb` (640 px column)
  - `.onb-stepper` (five-pill progress bar)
  - `.onb-step` (card container)
  - `.onb-form` (labelled inputs)
  - `.onb-check` (checkbox + label row)
  - `.onb-actions` (button row, right-aligned)
  - `.onb-btn` / `.onb-btn.secondary`
  - `.onb-agreement` (blue-tinted Legal callout)
  - `.onb-recap` (final-step recap card)
  - `.onb-result.ok` / `.onb-result.fail`

Nothing bumps `_BASE_CSS_VERSION`.

## Progress stepper (top of every step)

```
[1. Welcome] [2. Passphrase] [3. Broker] [4. Pairs] [5. Confirm]
   done         current         upcoming    upcoming    upcoming
```

- `.done` (green underline), `.current` (accent underline + bold),
  neutral otherwise.

## Step 1 -- Welcome

```
+-------------------------------------------+
| Welcome                                   |
| Blue Lock is a single-user hobbyist       |
| trading platform. You install it on your  |
| machine. It doesn't send your data        |
| anywhere.                                 |
|                                           |
| [Blue callout, .onb-agreement]            |
|  By continuing you agree that Blue Lock   |
|  Trading Co. is not a regulated broker or |
|  investment adviser, that nothing this    |
|  platform outputs is financial advice,    |
|  and that any losses incurred through     |
|  connected broker accounts are your       |
|  responsibility.                          |
|                                           |
|                    [ Continue -> ]        |
+-------------------------------------------+
```

- Agreement text is verbatim from
  `company/legal/F008-onboarding-agreement.md`.

## Step 2 -- Passphrase

```
+-------------------------------------------+
| Set your fallback passphrase              |
| Blue Lock stores your broker credentials  |
| in your OS keychain when it can. If a     |
| keychain isn't available on this machine, |
| we fall back to an encrypted file         |
| protected by this passphrase. Leave empty |
| if your keychain works and you want to    |
| skip the fallback.                        |
|                                           |
| Passphrase                                |
| [ ******************             ]        |
|                                           |
| [ ] Skip passphrase (my OS keychain is    |
|     available).                           |
|                                           |
|  [ Result callout, green or red ]         |
|                                           |
|   [ <- Back ]           [ Continue -> ]   |
+-------------------------------------------+
```

- `type="password"`, `autocomplete="new-password"`, `spellcheck="false"`.
- Skip checkbox is only honoured when the server confirms keychain is
  available; the endpoint returns a failure message if not.

## Step 3 -- Broker

```
+-------------------------------------------+
| Connect a broker                          |
| Blue Lock trades on MT5. You'll open the  |
| broker wizard, connect a demo (or live)   |
| account, then return here to finish       |
| setup.                                    |
|                                           |
|   [ <- Back ]                             |
|   [ Open broker wizard -> ] (new tab)     |
|   [ I've connected a broker -> ]          |
|                                           |
|  [ Result row: "Broker connection         |
|    detected." OR "No broker connected     |
|    yet." ]                                |
+-------------------------------------------+
```

- The Open button is an `<a target="_blank">` to `/settings/broker`.
- Continue re-checks `broker_connected` before advancing.

## Step 4 -- Pairs

```
+-------------------------------------------+
| Choose default pairs                      |
| Which FX pairs should the squad watch     |
| first? You can change this later on the   |
| /players page.                            |
|                                           |
| [x] EURUSD (default)                      |
| [ ] GBPUSD                                |
| [ ] USDCAD                                |
|                                           |
|   [ <- Back ]           [ Continue -> ]   |
+-------------------------------------------+
```

- EURUSD pre-checked.
- Continue rejects zero-selection at the client (alert()) and again
  server-side (400 with a friendly message).

## Step 5 -- Confirm

```
+-------------------------------------------+
| Ready to go                               |
| Here's your setup:                        |
|                                           |
|  [ Recap card, .onb-recap ]               |
|    Passphrase: set (or "skipped (keychain)")
|    Broker: connected                      |
|    Default pairs: EURUSD, GBPUSD          |
|                                           |
|   [ <- Back ]         [ Finish setup ]    |
|                                           |
|  [ Result row: "Setup complete. Taking    |
|    you to the hub." ]                     |
+-------------------------------------------+
```

- Finish calls `POST /api/onboarding/complete`; on success, redirects
  to `/` after 1.2 s.

## Reset-install page (`/settings/reset-install`)

```
+---------------------------------------------------+
| Reset your Blue Lock install                      |
| This clears your install token and saved broker   |
| connections, then sends you back through setup.   |
|                                                   |
|  Warning. This deletes every saved broker alias,  |
|  your install token, and the passphrase-fallback  |
|  file (if any). It cannot be undone. Nothing is   |
|  sent anywhere -- the keys are simply removed     |
|  from your keychain / config file.                |
|                                                   |
|  [ <- Cancel ]  [ Reset install ]                 |
+---------------------------------------------------+
```

- Reset button uses `--red` for `background`, deliberately visually
  distinct from primary CTAs.
- Confirmation via JS `confirm()` before the POST fires; then a
  200 flips the user back to `/onboarding` after 1 s.

## Mobile (375 px viewport)

- `.onb` column drops to full width with `padding: 0 4px`.
- Stepper text drops one point size.
- Every button remains full-width in the action row (wraps).
- All input fields remain single-column; no side-by-side rows to
  break. Verified via the `@media (max-width: 700px)` block in
  `_ONBOARDING_CSS`.

## Copy tokens

Owned by `company/brand/copy.md` §F008. UI never inlines strings that
Brand owns. The Legal agreement is the exception: it is owned by
Legal and cited verbatim from
`company/legal/F008-onboarding-agreement.md`.
