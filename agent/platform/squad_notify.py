"""Telegram notifications for the v2 squad paper loop — DEDICATED bot.

The squad gets its OWN bot (separate token + chat) so match commentary
never mixes with the v1 trading bot's pages. Configuration comes from
two places, per key, in this precedence order:

1. ``[telegram]`` table in ``platform.toml`` (bot_token / chat_id /
   summary_every) — wins when set;
2. ``SQUAD_TELEGRAM_BOT_TOKEN`` / ``SQUAD_TELEGRAM_CHAT_ID`` env vars
   (``.env`` is loaded by the entry scripts).

Unconfigured (no token or no chat id from either source) means every
notify call is a silent no-op — the paper loop must never notice.

Transport is REUSED from v1: :class:`agent.notifications.telegram.
TelegramNotifier` (fail-open, multi-chat fan-out, injectable client).
This module adds only squad-flavored pure ``build_*`` formatters and a
small stateful router with rate limiting:

* kickoff / full-time / halt — always sent (one-offs);
* GOAL (winning close) and misses — always sent (trades are rare);
* proposals / rejections — never sent (paging noise);
* league-table summary — every ``summary_every`` closed trades and at
  full-time / halt.
"""
from __future__ import annotations

import logging
import os

from agent.notifications.telegram import TelegramConfig, TelegramNotifier
from agent.platform.squad_events import ROSTER

log = logging.getLogger(__name__)

ENV_BOT_TOKEN = "SQUAD_TELEGRAM_BOT_TOKEN"
ENV_CHAT_ID = "SQUAD_TELEGRAM_CHAT_ID"
DEFAULT_SUMMARY_EVERY = 10  # closed trades between league-table posts


def resolve_config(toml_telegram: dict | None = None,
                   env: dict | None = None,
                   *, dry_run: bool = False) -> tuple[TelegramConfig, int]:
    """(TelegramConfig, summary_every) merged per key: toml wins over env."""
    toml_telegram = toml_telegram or {}
    env = os.environ if env is None else env
    token = str(toml_telegram.get("bot_token") or
                env.get(ENV_BOT_TOKEN, "") or "")
    chat = str(toml_telegram.get("chat_id") or
               env.get(ENV_CHAT_ID, "") or "")
    try:
        summary_every = int(toml_telegram.get("summary_every")
                            or DEFAULT_SUMMARY_EVERY)
    except (TypeError, ValueError):
        summary_every = DEFAULT_SUMMARY_EVERY
    return (TelegramConfig(bot_token=token, chat_id=chat, dry_run=dry_run),
            max(1, summary_every))


# ---------------------------------------------------------------------------
# Pure formatters — no I/O, tested in isolation. Same phone-first rules as
# the v1 builders: symbol-first header line, compact, Markdown.
# ---------------------------------------------------------------------------


def _player(agent_id: str) -> str:
    """'Isagi #11' from a roster id; unknown ids pass through verbatim."""
    info = ROSTER.get(agent_id)
    if not info:
        return str(agent_id)
    return f"{info['name']} #{info['num']}"


def _fmt_pips(pips: float) -> str:
    sign = "+" if pips >= 0 else ""
    return f"{sign}{pips:.1f}p"


def build_squad_kickoff(*, source_label: str, n_rows: int,
                        out_dir: str) -> str:
    return (
        f"*SQUAD | KICKOFF*\n"
        f"Paper loop started — replaying `{source_label}`\n"
        f"{n_rows} rows queued | stream: `{out_dir}`\n"
        f"Shadow-only: no broker orders, ever."
    )


def build_squad_goal(*, agent_id: str, symbol: str, pips: float,
                     tqs: float | None = None,
                     r_multiple: float | None = None,
                     exit_reason: str = "") -> str:
    lines = [f"*{symbol} | GOAL — {_player(agent_id)}*"]
    stat_bits = [f"`{_fmt_pips(pips)}`"]
    if r_multiple is not None:
        stat_bits.append(f"`{r_multiple:+.2f}R`")
    if tqs is not None:
        stat_bits.append(f"TQS `{tqs:.2f}`")
    lines.append(" | ".join(stat_bits))
    if exit_reason:
        lines.append(f"Exit: {exit_reason}")
    return "\n".join(lines)


def build_squad_miss(*, agent_id: str, symbol: str, pips: float,
                     r_multiple: float | None = None,
                     exit_reason: str = "") -> str:
    lines = [f"*{symbol} | Shot MISSED — {_player(agent_id)}*"]
    stat_bits = [f"`{_fmt_pips(pips)}`"]
    if r_multiple is not None:
        stat_bits.append(f"`{r_multiple:+.2f}R`")
    lines.append(" | ".join(stat_bits))
    if exit_reason:
        lines.append(f"Exit: {exit_reason}")
    return "\n".join(lines)


def build_squad_halt(*, reason: str) -> str:
    return (
        f"*SQUAD | MATCH HALTED*\n"
        f"kill.txt: `{(reason or 'killed')[:200]}`\n"
        f"Restart resumes from state.json."
    )


def build_squad_full_time(*, outcome: str) -> str:
    words = {
        "done": "replay exhausted — every row emitted",
        "max_steps": "step budget reached — restart resumes from state.json",
    }
    return (
        f"*SQUAD | FULL TIME*\n"
        f"{words.get(outcome, outcome)}"
    )


def build_league_table(per_agent: dict[str, dict]) -> str:
    """League table from squad_events-style per-agent stats
    ({goals, trades, pips, ...} per agent id), sorted by pips."""
    rows = [(aid, d) for aid, d in per_agent.items() if d.get("trades")]
    rows.sort(key=lambda r: -r[1].get("pips", 0.0))
    lines = ["*SQUAD | League table*"]
    if not rows:
        lines.append("No shots on target yet.")
        return "\n".join(lines)
    for rank, (aid, d) in enumerate(rows, start=1):
        lines.append(
            f"{rank}. {_player(aid)} — {d.get('goals', 0)}G/"
            f"{d.get('trades', 0)}T `{_fmt_pips(d.get('pips', 0.0))}`"
        )
    total = sum(d.get("pips", 0.0) for _, d in rows)
    lines.append(f"Team total: `{_fmt_pips(total)}`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stateful router
# ---------------------------------------------------------------------------


class SquadNotifier:
    """Routes paper-loop rows to the dedicated squad Telegram bot.

    Silent no-op when unconfigured; NEVER raises out of a notify call
    (the paper loop must survive any Telegram failure). Only closed
    trades page; proposals/rejections only feed the periodic summary
    counters. A league table goes out every ``summary_every`` closes
    and once at full-time/halt.
    """

    def __init__(self, config: TelegramConfig,
                 summary_every: int = DEFAULT_SUMMARY_EVERY, *,
                 client=None) -> None:
        self.config = config
        self.summary_every = max(1, int(summary_every))
        self._notifier = TelegramNotifier(config, client=client)
        self._closes = 0
        self._per_agent: dict[str, dict] = {}

    @classmethod
    def from_sources(cls, toml_telegram: dict | None = None,
                     env: dict | None = None, *, dry_run: bool = False,
                     client=None) -> "SquadNotifier":
        config, summary_every = resolve_config(toml_telegram, env,
                                               dry_run=dry_run)
        return cls(config, summary_every, client=client)

    @property
    def configured(self) -> bool:
        return self.config.configured

    # -- lifecycle one-offs --------------------------------------------------

    def notify_kickoff(self, *, source_label: str, n_rows: int,
                       out_dir: str) -> None:
        self._safe_send(build_squad_kickoff(
            source_label=source_label, n_rows=n_rows, out_dir=out_dir))

    def notify_system(self, text: str) -> None:
        """One-line system warning (e.g. dead news feed).

        Rate limiting is the CALLER's concern -- follow the
        once-per-failure-streak pattern (send on streak==1 only),
        never per poll."""
        self._safe_send(f"*SQUAD | SYSTEM*\n{text}")

    def notify_stop(self, outcome: str, *, reason: str = "") -> None:
        """Full-time (done/max_steps) or halt (killed) + final table."""
        if outcome == "killed":
            self._safe_send(build_squad_halt(reason=reason))
        else:
            self._safe_send(build_squad_full_time(outcome=outcome))
        if self._closes:
            self._safe_send(build_league_table(self._per_agent))

    # -- per-row routing -----------------------------------------------------

    def notify_row(self, row: dict, source_file: str) -> None:
        """One paper-loop row. Only trades.jsonl rows produce messages."""
        if source_file != "trades.jsonl":
            return  # proposals / rejections: never page
        try:
            self._handle_trade(row)
        except Exception as e:  # fail-open, like the v1 notifier
            log.warning("Squad Telegram routing failed: %s", e)

    # -- internals -----------------------------------------------------------

    def _handle_trade(self, row: dict) -> None:
        agent_id = row.get("agent_id", "?")
        symbol = row.get("symbol", "?")
        pips = float(row.get("pnl_pips", 0.0) or 0.0)
        r_multiple = row.get("r_multiple")
        tqs = None
        tc = row.get("tqs_components")
        if isinstance(tc, dict) and tc.get("tqs") is not None:
            tqs = float(tc["tqs"])
        exit_reason = str(row.get("exit_reason", "") or "")

        stats = self._per_agent.setdefault(
            agent_id, {"goals": 0, "trades": 0, "pips": 0.0})
        stats["trades"] += 1
        stats["pips"] = round(stats["pips"] + pips, 1)
        if pips > 0:
            stats["goals"] += 1
            self._safe_send(build_squad_goal(
                agent_id=agent_id, symbol=symbol, pips=pips, tqs=tqs,
                r_multiple=r_multiple, exit_reason=exit_reason))
        else:
            self._safe_send(build_squad_miss(
                agent_id=agent_id, symbol=symbol, pips=pips,
                r_multiple=r_multiple, exit_reason=exit_reason))

        self._closes += 1
        if self._closes % self.summary_every == 0:
            self._safe_send(build_league_table(self._per_agent))

    def _safe_send(self, text: str) -> None:
        if not self.configured:
            return
        try:
            self._notifier.notify_text(text)
        except Exception as e:  # TelegramNotifier already fails open;
            log.warning("Squad Telegram send failed: %s", e)  # belt+braces


__all__ = [
    "ENV_BOT_TOKEN",
    "ENV_CHAT_ID",
    "DEFAULT_SUMMARY_EVERY",
    "resolve_config",
    "build_squad_kickoff",
    "build_squad_goal",
    "build_squad_miss",
    "build_squad_halt",
    "build_squad_full_time",
    "build_league_table",
    "SquadNotifier",
]
