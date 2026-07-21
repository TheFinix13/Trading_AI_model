# Brand copy library

Canonical user-facing strings for the platform. Every prominent piece
of copy on `/`, `/v1`, `/v2`, `/hq`, `/performance`, `/players`,
`/research` traces back to a line here. New copy needs Brand review
before it ships; inline exceptions get a `[persona-decision]` bullet
in `company/ledger/decisions_log.md`.

Tone rules (D008):

- **Stranger-friendly.** A reader who has never touched a chart
  understands the sentence.
- **No "ensemble", no "aggregator".** Founding charter's banned words
  in user-visible copy. Say "the squad", "the striker who won the
  pass", "the referee (Sentinel)".
- **Warm, not lawyer-ily.** Even disclaimers read as "here is what
  this actually is", not "we hereby indemnify".
- **Every number is honest.** No number rounds up in our favour, no
  metric is defined post-hoc to make a chart look better.

## One-liner (charter)

> The first AI trading platform that trades like a football team.

## Sub-headline (hub / performance)

> Watch our striker squad find setups on real markets — every
> decision explained, every trade justified, every risk gated.

## Section headings

### `/performance` page

- **Page title:** "How we're doing"
- **Preamble (~2 sentences):** "This is the demo-account P&L for our
  live zones agent and the paper equity curve for the striker squad,
  updated bar-by-bar. Every number here is a real number the platform
  wrote to disk — no back-tests, no cherry-picks."
- **KPI tile labels:**
  - "Days live"
  - "Net pips"
  - "Worst drawdown"
  - "Win rate"
  - "Sharpe"  (shows "n/a — need N more days" until ≥30 daily returns)
- **Per-pair table header:** "By pair"
- **Column labels:** "Pair · Trades · Wins · Net pips · Avg pips ·
  Best trade · Worst trade"

### `/players` index

- **Page title:** "The squad"
- **Preamble:** "Ten characters, each with a distinct playstyle. The
  squad reads the same market bars our production agent reads and
  proposes trades every 4 hours — no real money, no live orders."
- **Status pills:**
  - `active` — "on the pitch right now"
  - `standby` — "warmed up, off by default (kept for the roster
    record)"
  - `retired` — "hung up the boots; the reason and date are on the
    bio"

### `/players/:id`

- **Sub-header pattern:** "<name> · <playstyle tag>"
- **Section headings (all bios):** "Playstyle", "Signature setup",
  "Career stats", "Evolution history", "Recent activity"
- **Empty-state (no recent activity):** "No trades on the tape for
  this striker yet — see 'Playstyle' for how they read a market."

### `/research` page

- **Page title:** "What we tried, and what we found"
- **Preamble (~4 sentences, Marketing-authored — the anti-marketing
  marketing framing):**
  > Every campaign below is a hypothesis about how markets work. We
  > pre-register the test before we run it, we cap the false-discovery
  > rate across every experiment in a family, and we publish the
  > verdict whether it helps our product or not. This page is the
  > receipt trail. If more of these verdicts said "alive" than "dead"
  > you should be more skeptical of us, not less.
- **Verdict pill labels:**
  - `combined_alive` — "green — alive"
  - `pass_thin` — "green — thin edge, kept"
  - `stopped_at_stage_1` — "grey — stopped early, no follow-up"
  - `parked_low_yield` — "grey — parked (too little signal)"
  - `dead` / `FAIL` — "red — dead"
  - (unknown / unmatched) — "grey — no verdict yet"

### `/hq` — internal dashboard

- **Page title:** "Blue Lock Trading Co. — HQ"
- **Reserved for the ledger; see `company/README.md` charter for
  headline copy.**

## Micro-copy

### Nav pills (top of every page)

- `Hub`, `v1 · Zones agent`, `v2 · Squad pitch`, `HQ`,
  `Performance`, `Squad`, `Research`

Ordering rule: existing three pills first (Hub / v1 / v2), then HQ,
then the three Sprint-0 additions (Performance / Squad / Research)
right-aligned. Only one is active at a time (matches the `.here`
class in `_NAV`).

### Buttons

- Retry a failed fetch: **"Try again"**  (NOT "Retry")
- Dismiss an inline error: **"Got it"**  (NOT "Dismiss")
- Expand a `<details>`: label the summary, not the button (browser
  handles it)
- Load more entries: **"Older entries"**

## Numbers formatting

- Pips: 1 decimal for singles ("+12.4 pips"), 0 decimals for totals
  ("+1,240 pips").
- Percent: 1 decimal ("58.4 %"), always a space before `%`.
- Money: "+$120.40", "-$45.20" — sign always shown.
- Dates: ISO 8601 short ("2026-07-21"), never American ("07/21/26").
- Time: 24-hour UTC, never AM/PM.
- Currency pair: uppercase 6 letters, no slash ("EURUSD").

## Character-name spellings

Canonical spellings for the 10 strikers. Bios and F002 pages must
match exactly:

- Isagi (full: Yoichi Isagi)
- Bachira (full: Meguru Bachira)
- Rin (full: Itoshi Rin)
- Chigiri (full: Hyoma Chigiri)
- Reo (full: Reo Mikage)
- Nagi (full: Seishiro Nagi)
- Barou (full: Shoei Barou)
- Karasu (full: Karasu Tabito)
- Sae (full: Itoshi Sae)
- Kunigami (full: Rensuke Kunigami)

Playstyle taglines are set per-bio in `company/roster/players/*.md`
and referenced by the /players page renderer, not duplicated here.

## §F006 — Security & auth strings (Sprint 1)

Every user-visible string on any auth surface picks from this list.
Bracketed placeholders (`<fingerprint>`) get replaced at render time.

### Install fingerprint chip

- Label prefix: `Install fingerprint`
- Configured state: `🔒 <fingerprint>` where `<fingerprint>` is
  `first8…last8` (from `auth.install_token_fingerprint`).
- Unconfigured state: `⚠ Not configured yet — visit /onboarding`
- Error state: `Auth status unavailable`
- Reassurance line on /hq (below the chip):
  `Your install token is stored securely on your device.`

### `/onboarding` welcome (bundled into F008)

Auth-related welcome step copy also lives in this section for
easy Legal review of the whole security narrative:

- Header: `Welcome to Blue Lock Trading`
- Subhead: `Let's set up your install in five short steps.`
- Reassurance: `Your credentials never leave your machine.`

### Passphrase step (F008 step 2)

- Prompt: `Set an install passphrase`
- Explanation: `We use it as a backup lock when your system keychain
  isn't available.`
- Reveal toggle: `Show / Hide passphrase`
- Strength warning:
  - `Enter at least 12 characters.` — when < 12.
  - `Your system keychain is available; the passphrase is optional but
    recommended.` — when the OS keychain is usable.
- Persistence disclaimer: `Passphrase is never stored on disk in
  plaintext.`

### Reset install flow (F008 `/settings/reset-install`)

- Title: `Reset this install?`
- Warning: `This clears your install token and saved broker
  credentials. You'll go through onboarding again.`
- Confirm button: `Yes — reset this install`
- Cancel button: `Keep this install`
- Success message: `Install reset. Redirecting to onboarding.`

### Errors (auth-related)

- 401 body: `Install token required.` (never echo the token in
  responses.)
- Malformed token: `That token doesn't look right — check the copy.`
- Post-reset load: `Install reset — nothing was leaked.`

## §F007 — Broker connection wizard strings (Sprint 1)

- Header: `Connect your broker`
- Choose account type: `Which account are we connecting?`
  - Radio: `Demo / Sandbox account (recommended)` — default
  - Radio: `Live account (real money)`
- Server dropdown label: `MT5 server`
- Login label: `Login (numeric MT5 login)`
- Password label: `Password`
- Test connection button: `Test connection`
- Loading label: `Testing connection…` (uses F005 withStates)
- Success message: `Connected to <server> — account #<login> in
  <currency>.`
- Save button: `Save this connection`
- Alias label: `Save this as`
- Delete confirm: `Remove <alias>? The stored password is deleted.`

### Live account confirmation

- Warning header: `You picked a live account`
- Warning body: (from `company/legal/live-broker-warning.md`, injected
  verbatim — Brand does not paraphrase Legal text).
- Confirmation checkbox: `I understand this uses real money.`
- Confirmation typed field: `Type LIVE to continue:`
- Wrong-typed error: `Type LIVE (uppercase, no quotes) to continue.`

### Errors (broker)

- Rate-limited: `Too many attempts — wait a minute before retrying.`
- Bad server: `That server isn't on the approved list. Pick from the
  dropdown.`
- Connection failed: `We couldn't connect. Double-check the login and
  server, then try again.` (Never leaks the password in the message.)

## §F008 — Onboarding strings (Sprint 1)

- Step 1 (welcome): see §F006 welcome above.
- Step 2 (passphrase): see §F006 passphrase step above.
- Step 3 (broker): embedded F007 flow.
- Step 4 (default pairs):
  - Prompt: `Which pairs should the squad watch first?`
  - Note: `You can change this later on the /players page.`
  - Options: `EURUSD` (default on), `GBPUSD`, `USDCAD`
- Step 5 (confirm):
  - Header: `Ready to go`
  - Recap intro: `Here's your setup:`
  - Complete button: `Finish setup`
  - Post-finish redirect message: `Setup complete. Taking you to the
    hub.`

