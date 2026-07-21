# F007 -- UI mocks: broker connection wizard

_Sprint 1, Broker Integrations lane, 2026-07-21._

The wizard lives at `/settings/broker`. It carries the site nav (no
active pill -- `broker` is not a permanent top-level route) and a
five-step form column capped at 640 px wide, centred.

## Visual system

- Reuses `_BASE_CSS` (dark theme, `--bg` `#0d1117`, `--panel` `#161b22`,
  `--accent` `#58a6ff`, `--amber` `#d29922`, `--red` `#f85149`).
- Reuses `_SKELETON_CSS` for the `withStates()` in-flight spinner on
  the Test connection step.
- Introduces additive primitives under `_BROKER_CSS`:
  - `.wiz` (640 px column)
  - `.wiz-step` (card container)
  - `.wiz-radio-card` (Demo / Live choice)
  - `.wiz-form` (labelled inputs)
  - `.wiz-actions` (button row)
  - `.wiz-warn` (amber inline warning)
  - `.wiz-result.ok` / `.wiz-result.fail` (green / red)
  - `.wiz-alias-row` (saved connection row)
  - `.wiz-alias-badge.demo` / `.wiz-alias-badge.live`

None break `_BASE_CSS_VERSION`; they're purely additive.

## Step 1 -- Account type

```
+---------------------------------------------------+
| 1. Which account are we connecting?               |
| Pick sandbox / demo unless you know you need the  |
| live one. You can always change this later.      |
|                                                   |
| [ Demo / Sandbox account (recommended)   ]        |
|   No real money at risk. Perfect for evaluating.  |
|                                                   |
| [ Live account (real money)              ]        |
|   Requires typed confirmation on the next screen. |
|                                                   |
| [ Next -> ]                                       |
+---------------------------------------------------+
```

- Demo card ships with `.wiz-radio-card selected` and
  `aria-checked="true"`.
- Live card is `.wiz-radio-card` with `aria-checked="false"`.
- `tabindex="0"` + `role="radio"`; Space / Enter re-checks.

## Step 2 -- Credentials

```
+---------------------------------------------------+
| 2. Enter your MT5 credentials                     |
| Your password lives on your device only. The      |
| platform server sees it only during test-connect. |
|                                                   |
| MT5 server (exact name from broker)               |
| [ Exness-MT5Trial7                       ] datalist
|                                                   |
| Login (numeric MT5 login)                         |
| [ 12345678                               ]        |
|                                                   |
| Password                                          |
| [ ******************                     ]        |
|                                                   |
| [ <- Back ]  [ Next -> ]                          |
+---------------------------------------------------+
```

- Server input is `<input list="server-suggestions">`; the datalist
  only carries values from `ALLOWED_SERVERS` prefixes.
- Login: `inputmode="numeric"`, `pattern="\d{1,20}"`, `autocomplete="off"`.
- Password: `type="password"`, `autocomplete="off"`, `spellcheck="false"`,
  never shipped with a `value=` attribute.

## Step 2.5 -- Live confirmation (conditional)

```
+---------------------------------------------------+
| You picked a live account                         |
|                                                   |
|  Warning. You are about to connect a LIVE ...     |
|  [Warning body from /api/broker/live-warning]     |
|                                                   |
|  [ ] I understand this uses real money.           |
|  Type LIVE to continue:  [ LIVE ]                 |
|                                                   |
| [ <- Back ]  [ Continue -> (disabled) ]           |
+---------------------------------------------------+
```

- Warning body loaded from `/api/broker/live-warning` (which reads
  `company/legal/live-broker-warning.md` on the server side).
- Continue button unlocks only when both:
  - `#in-live-ack` is checked, and
  - `#in-live-typed` value trims to exactly `LIVE`.
- Amber warning styling (`.wiz-warn`) draws the eye without going full red.

## Step 3 -- Test connection

```
+---------------------------------------------------+
| 3. Test the connection                            |
| We call your broker with the credentials above    |
| and read back the account type + currency.        |
|                                                   |
| [ <- Back ]  [ Test connection ]                  |
|                                                   |
| [Skeleton spinner while in-flight]                |
|                                                   |
| Result:                                           |
|   OK  -> Connected. Account #12345678 on          |
|          Exness-MT5Trial7 -- demo (USD)           |
|   FAIL -> Not connected. <error message>          |
+---------------------------------------------------+
```

- The Test button toggles into a `withStates()` loading state during
  the fetch; the skeleton reuses `_SKELETON_CSS`.
- On success the Test button disables and Step 4 auto-expands.
- On failure the button stays clickable so the user can retry after
  fixing the credentials.

## Step 4 -- Save

```
+---------------------------------------------------+
| 4. Save the connection                            |
|                                                   |
| Save this as                                      |
| [ primary                                ]        |
|                                                   |
| [ <- Back ]  [ Save connection ]                  |
|                                                   |
| Result:                                           |
|   OK  -> Saved. Your password is encrypted at rest.
|   FAIL -> Save failed. <error>                    |
+---------------------------------------------------+
```

- Alias default: `primary`. Uses same allow-list regex as
  `_validate_alias` in broker_connection.py.

## Saved-connections table (always visible)

```
+---------------------------------------------------+
| Saved connections                                 |
| Passwords are never displayed here -- stored      |
| encrypted in your OS keychain.                    |
|                                                   |
| primary  [demo]                        [Remove]   |
|   Exness-MT5Trial7 -- login 12345678              |
| ---                                                |
| aggressive-live  [live]                [Remove]   |
|   Exness-MT5Real1 -- login 87654321               |
+---------------------------------------------------+
```

- Rendered by `refreshAliases()`; hits `/api/broker/list`.
- Remove button asks for `confirm()` before firing DELETE.

## Mobile (375 px viewport)

- The `.wiz` column drops to full width with `padding: 0 4px`.
- Steps become full-width cards, buttons wrap.
- All inputs remain single-column; no side-by-side rows to break.
- Verified via the `@media (max-width: 700px)` block in `_BROKER_CSS`.

## Copy tokens

Owned by `company/brand/copy.md` under the F007 section: step titles,
lead paragraphs, warning strings, error messages. UI never inlines
strings that Brand owns.
