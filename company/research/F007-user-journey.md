# F007 -- User journey: connect an MT5 broker

_Sprint 1, Broker Integrations lane, 2026-07-21._

## Target user segment

Same as F006: a single retail forex trader on their own machine. Their
mental model of "connecting a broker" is a login screen, not a wizard.
Our wizard has to justify each step or the user drops off.

## Jobs to be done

1. **Prove the connection works before saving.** A `Test connection`
   step is more important than any UX polish. A user who saves broken
   credentials only finds out at trade time -- unacceptable.
2. **Default to sandbox / demo.** The typical first session is
   "does this thing even work?" not "let me risk real money". The
   demo radio must be pre-selected, and the copy on the live radio
   must be honest ("real money") not marketing.
3. **Save under a memorable alias.** Multi-broker over time is not in
   scope for this sprint, but a nameable alias (`primary`, `trial7`)
   is the difference between one and many, so we build the shape now.
4. **Never see a password again.** Once stored, the wizard's saved-
   connections table shows the alias + server + login, never a
   masked-out password field the user might feel invited to edit.

## Non-jobs

- **Order placement / trade routing.** F007 stops at the login handshake.
  Live agents (`agent/live/*`, `agent/squad/*`) read the stored
  credentials via `credentials.retrieve_secret` -- their code is not
  affected by this feature.
- **Broker selection.** We only support MT5. Adding OANDA REST or CCXT
  is a Sprint 3+ conversation.
- **Live-broker regulatory compliance.** Legal's `live-broker-warning.md`
  frames Blue Lock as a hobbyist single-user platform. We do NOT try
  to become a regulated adviser.

## First-run walk-through (desktop + mobile)

1. **Step 1 -- Which account?** Two radio cards. Demo pre-selected.
   Live card copy: "Live account (real money)".
2. **Step 2 -- Credentials.** Server (allow-listed autocomplete),
   Login (numeric, `inputmode=numeric`), Password (`type=password`,
   `autocomplete=off`). No password strength UI: the user's broker
   already enforces that.
3. **Step 2.5 -- Confirm live.** Only shown if Step 1 was Live. Loads
   Legal's warning text from `/api/broker/live-warning`, requires
   both a checkbox and a typed `LIVE` before Next unlocks.
4. **Step 3 -- Test connection.** In-flight state uses F005
   `withStates()`. On macOS / Linux MT5 is unavailable -- the payload
   surfaces a friendly "MT5 SDK not present on this OS" message with
   the connection marked failed.
5. **Step 4 -- Save.** Alias input. Default placeholder `primary`.
   Save button surfaces success + immediately refreshes the saved-
   connections table below.
6. **Saved connections table.** Always visible at the bottom of the
   wizard. Rows carry a demo/live badge and a Remove button.

## Accessibility notes

- Radio cards are `role="radio"` with `aria-checked` toggled correctly
  and Space / Enter activate them.
- Numeric login uses `inputmode=numeric` (surfaces the number keypad
  on mobile) but not `type=number` -- avoids spinner artefacts on
  desktop.
- The live-account confirmation UI must not autoscroll away from the
  Continue button once the two gates pass. Verified in mobile mock.

## Success criteria for this journey

- New user can go from "empty wizard" to "saved demo connection" in
  < 60 seconds without reading any external doc.
- Live-account misclicks (accidental live-save) require at minimum
  two independent affirmative user actions before saving.
- No password is ever rendered into the DOM outside its `type=password`
  input, and no password crosses the network except during the two
  POSTs (`/api/broker/test-connection` and `/api/broker/save`).
