# F011 — user journey · panic-mode operator

## Persona

**Ren, 32, semi-professional trader.** Runs the platform on a demo MT5
connection. Not a developer. Uses the /hq dashboard daily. Has never
touched a keyring flag file, never SSH'd into a VM.

## Scenario 1 · Broker flash-wide spread on EURUSD only

**Trigger.** Ren notices EURUSD spread jump from 0.9 to 6 pips at
14:03 UTC. GBPUSD and the other pairs look normal. She wants to halt
EURUSD *only* — the other pairs are still tradeable.

**Journey (target).**

1. From /hq nav, Ren clicks *Kill switches* (or types `/settings/kill-switches`).
2. Grid shows six cells: `[Global (all pairs)] [EURUSD] [GBPUSD]
   [USDCAD] [USDJPY] [USDCHF]`. All inert.
3. She types `spread jump — broker glitch?` into the reason textarea.
4. Clicks *Activate kill* under **EURUSD**. Cell turns red, state
   flips to *ACTIVE — spread jump…*. The button becomes *Clear*.
5. Recent-events panel below the grid shows the new entry:
   `2026-07-22T14:03:17Z  ACTIVATE  EURUSD — spread jump — broker
   glitch?  by user`.

**Confidence checks.**
- The reason is visible in the cell state so a colleague looking
  over her shoulder sees WHY the kill is on.
- The activate button is red-tinted (matches _BASE_CSS `--red`) so
  it reads as "this is a safety action, not a routine setting".
- The reason textarea is required before *Activate kill* is accepted
  (JS refuses on empty). Clicks with empty reason surface an inline
  status: "Reason is required when activating."

**Recovery.**
- Ten minutes later the spread normalises. Ren returns to /settings/kill-switches.
  She clicks *Clear* on the EURUSD cell (no reason required for a clear).
- Cell flips back to inert. Recent events panel appends a
  `CLEAR EURUSD` entry.

## Scenario 2 · Global halt

**Trigger.** Ren sees the M001 squad's league table cratering across
every pair simultaneously (screenshot of the /hq page shows red on
five out of five). She doesn't yet know why. Wants to halt everything.

**Journey.**

1. /settings/kill-switches.
2. Reason: `all pairs collapsing — investigate before restart`.
3. Click *Activate kill* on **Global (all pairs)**.
4. Every symbol cell renders as ACTIVE (the JS reads the state
   response and honours the global-masks-all invariant).

**Latency guarantee.** The read path (`is_killed()`) stat-checks the
directory mtime on every call. Any future live-order integration
polling `is_killed()` at open sees the kill within one tick of the
button press. The `/settings/kill-switches` page itself reloads state
after each mutation.

## Scenario 3 · Reboot / recovery

**Trigger.** VM reboots overnight while a kill is active. Ren wants
to know the kill is still in effect on the fresh process.

**Journey.**

1. Load /settings/kill-switches after reboot.
2. Grid renders the *same* red cells as before — the flag files
   persist on disk and the module reads them on first call. No re-
   activation needed.

## Scenario 4 · Operator handoff (single-user product, but journals matter)

**Trigger.** Ren has to hand the terminal off to a partner mid-day.

**Journey.**

- The recent-events panel is the audit trail. Every activate / clear
  is logged with a UTC timestamp and the reason string. The partner
  sees WHY the kill was activated even without a conversation. This
  matters legally (F013's live-mode warning references the audit log
  as the "why we halted" record of truth).

## Non-goals for Sprint 2

- **Time-based auto-expire** (e.g. "kill EURUSD for 30 minutes"). Not
  in scope; F013's approval queue is the primary way to gate order
  flow, and the kill is deliberately manual-only. If future ops want
  auto-expire they file a Sprint-3 feature.
- **Notifications on kill trip.** F014 will fire a Telegram alert on
  `kill_switch_trip`. Not this feature's job.
- **Wiring into any live-order pathway.** D065 hard invariant. The
  activate button in Sprint 2 does nothing to actual orders — it
  just files a flag the future integration will honour.
