# F019 — Broker-wizard recovery path + missing-broker chip (+ internal-token config seam)

- **Sprint:** sprint-3-stickiness
- **Priority:** P0 (in-sprint) · Size **S**
- **Source:** I003 (P1, dogfood — P002/P005 journeys) + I004 (P3,
  bundled per D113 while this spec stays small)
- **Consumes:** F007 broker wizard (`broker_connection.py`), F008
  onboarding state, F013 internal-token gate (`config.load_config`)
- **Consumed by:** dogfood cast (F016) re-run is the acceptance check
- **Feature flags:** `legal_relevant: true` (new user-facing copy on a
  public first-run surface; Brand pre-review of the strings),
  `security_relevant: false` expected — no auth logic changes, only
  where a config file is *read from* (CTO confirms at architecture)
- **Claims introduced:** NONE (no numbers; copy + state chip only)

## User story

Ada (P002, cautious first-timer) sets up on her Mac. The broker test
fails because MT5 is Windows-only. Today she gets a dead-end sentence
and an onboarding flow that "completes" anyway. After F019 she reads
what the constraint is, what her options are, finishes setup knowing
the broker is still pending, and every later screen reminds her until
it's connected.

## Scope (in)

1. **Failure copy with a recovery path** (`broker_connection.py`
   message surface + wizard page): states the Windows-only constraint
   AND the next actions — run the platform on a Windows machine/VM
   (link to the setup doc section), or finish setup now and connect
   later from Settings → Broker. No jargon; "MT5" explained in one
   clause.
2. **Missing-broker state chip**: when `broker_connected` is false
   after onboarding completes, the onboarding completion screen and
   the `/` hub carry a visible "broker not connected yet" chip
   linking to the wizard. Rendered via the existing `withStates()`
   pattern; empty/error states unchanged.
3. **I004 seam** (bundled): `[internal] token` resolves through
   `BLUELOCK_CONFIG_DIR` first (`<config_dir>/platform.toml`), falling
   back to the repo-root `platform.toml`. Fail-closed-when-unset
   behaviour byte-for-byte unchanged. Dogfood harness drops its
   repo-root temp-file workaround.

## Scope (out)

- Any change to credential storage, token comparison, or the auth
  gate itself (that's the D115 charter's territory).
- Windows-side wizard behaviour; MT5 probing logic.
- Support email / contact channel (sellability gap 5 — Sprint 4
  ride-along candidate, not this spec).

## Acceptance criteria

- Dogfood re-run: P002 and P005 broker journeys assert an actionable
  substring in the failure response (I003's registered measurement).
- Onboarding completion with `broker_connected: false` renders the
  chip on completion screen and `/` hub; connecting a broker clears it.
- Harness runs with zero repo-root writes (I004's measurement).
- Repo-root-only installs (the VM) behave identically.

## Test plan

- `tests/platform/test_broker_connection.py` (extend): non-Windows
  failure payload carries recovery copy + doc link.
- `tests/platform/test_onboarding.py` (extend): completion with no
  broker → chip present; with broker → absent.
- `tests/platform/test_config.py` (extend): token resolution order —
  config-dir wins, repo-root fallback, unset = fail-closed (pin the
  existing refusal).
- Dogfood cast smoke stays green.

## Files touched (expected)

Edited: `agent/platform/{broker_connection,onboarding,pages,config}.py`,
`scripts/serve_platform.py` (submit-gate config lookup),
`scripts/dogfood_personas.py` (drop workaround). No new modules.
