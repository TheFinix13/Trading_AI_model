# Runbook — Dual MT5 terminals (v1 account + V2 Platform account)

**Why this exists (incident, 2026-07-24).** The machine had ONE MT5
terminal. When the V2 broker wizard probed the new "V2 Platform" demo
account, `mt5.initialize(login=...)` switched that single terminal's
logged-in account. The v1 zones agent — reading the same terminal —
suddenly saw its equity drop from ~$969 to the new account's $500,
concluded catastrophe, wrote `kill.txt`, and tried to emergency-close
positions that no longer existed on the newly connected account. The
safety layer worked as designed; the architecture (one terminal, two
accounts) was the bug.

**The fix.** Two terminal installs, one per account, permanently:

| Terminal | Install | Account | Used by |
|---|---|---|---|
| A (existing) | default MT5 install | v1's original demo account | v1 zones agent (orders) + v2 squad bar feed (read-only, logs in with v1's own creds so it re-asserts, never switches) |
| B (new, portable) | e.g. `C:\MT5-V2\` | "V2 Platform" (login 436983644, Exness-MT5Trial9) | /settings/broker probe + F018 demo-order executor — everything platform-side |

The platform pins its MT5 sessions to terminal B via `[broker]
terminal_path` in `platform.toml`. When that key is unset the platform
falls back to the old single-terminal behaviour — so setting it is the
whole switch.

## One-time setup (Windows VM)

1. **Install the second terminal.** Download the MT5 installer from
   Exness (or copy the existing install directory) into a NEW folder,
   e.g. `C:\MT5-V2\`. Don't reuse the default install path.
2. **Make it portable.** Create a shortcut to `C:\MT5-V2\terminal64.exe`
   with the `/portable` argument (Target:
   `"C:\MT5-V2\terminal64.exe" /portable`). Portable mode keeps its
   config/data inside `C:\MT5-V2\` instead of sharing
   `%APPDATA%` with terminal A.
3. **Log terminal B into the V2 account.** Launch via the portable
   shortcut → File → Login to Trade Account → login `436983644`,
   server `Exness-MT5Trial9`. Tick "save password". Leave it running.
4. **Confirm terminal A is on the v1 account.** Launch the default
   terminal → check the account number in the title bar / Navigator.
   If the wizard probe left it on the V2 account, log it back into the
   v1 account (File → Login to Trade Account).
5. **Pin the platform to terminal B.** In `platform.toml` at the repo
   root on the VM, add:

   ```toml
   [broker]
   terminal_path = "C:/MT5-V2/terminal64.exe"
   portable = true
   ```

6. **Restart the platform server** (`serve_platform.py`). The squad
   runtime (`run_squad_live.py`) does not need the key — its feed
   logs in with v1's own credentials read-only against terminal A.

## Recovering v1 after the incident

v1 halted itself correctly; un-halting is manual by design.

1. Complete steps 1–6 above FIRST — otherwise the next platform probe
   will yank the account again.
2. Verify in terminal A (GUI) that the v1 account is logged in and its
   open positions are visible again with the expected equity.
3. Delete `kill.txt` from the v1 log root
   (`<log_root>/kill.txt`, default
   `Documents\TradingAgentLogs\kill.txt`).
4. Restart the v1 agent process per `docs/runbooks/vmware-windows.md`.
5. Watch the first heartbeat in the v1 dashboard: balance/equity must
   match terminal A's numbers, not $500.

## Verifying the separation

- Run a broker-wizard "Test connection" from `/settings/broker`:
  terminal B's window flashes/logs in; terminal A's account number in
  its title bar must NOT change.
- `/` (hub): the v1 card and v2 card report different balances and
  never swap.

## Invariants going forward

- Terminal A is v1's. Nothing platform-side may initialize it with
  login kwargs. Any new MT5 call site in `agent/platform/*` MUST route
  through `broker_connection.terminal_launch_args()`.
- Terminal B is the platform's. v1 never touches it.
- If either terminal is reinstalled/moved, update `terminal_path` and
  restart the server before doing anything else.
