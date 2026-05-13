# Trading Partner Mode

This is the new conversation + teaching layer introduced on **2026-05-03**. It
turns the agent from a backtesting black-box into a **co-trader you teach and
talk to**.

There are three pillars:

1. **Learns from its own mistakes** — auto-replay + weekly retrospective.
2. **Learns from your teachings** — `scripts/teach.py` ingests free-form
   trade analysis, the LLM extracts structured lessons, the agent replays
   itself at the same moment and stores the diff.
3. **You can talk to it** — both a CLI (`scripts/ask.py`) and a dashboard
   `/chat` page, both backed by a local LLM via Ollama.

Everything below runs **on your laptop only**. No data leaves the machine;
no API keys required.

---

## One-time setup

```bash
brew install ollama
brew services start ollama

# extraction model (~9 GB, used for teach.py + retrospectives)
ollama pull qwen2.5:14b-instruct

# chat model (~5 GB, used for ask.py + dashboard /chat)
ollama pull qwen2.5:7b-instruct
```

Verify:

```bash
ollama list                                # both models present
curl -s http://localhost:11434/api/tags    # daemon healthy
```

If the daemon is offline, the dashboard chat shows a yellow banner with the
exact command to start it, and `teach.py` falls back to a deterministic
skeleton mode (you fill in the lesson manually).

---

## Daily workflow

### 1. Teach the agent your trades

After the close, dump a paragraph per trade into `teach.py`. Free-form is
fine — the LLM understands "I went short M15 from 1.17328 because the daily
was bearish and London swept PDH at 8:15 NY." style language.

```bash
# interactive — paste each paragraph, blank line to submit
python scripts/teach.py

# from a file (separate trades with --- on its own line)
python scripts/teach.py --file fixtures/sample_week.txt --yes

# voice (requires `pip install sounddevice scipy openai-whisper`)
python scripts/teach.py --voice
```

For each lesson the script:

1. Sends your paragraph to qwen2.5:14b-instruct in JSON mode.
2. Validates the result against the `TradeLesson` schema
   (`agent/llm/extractor.py`).
3. Stores it in the `human_lessons` table.
4. **Replays the agent at the same timestamp** (uses cached EURUSD bars),
   compares your read with what the rule engine would have done, and writes
   the diff into `agent_disagreements`.

Browse what you've taught at `http://127.0.0.1:8000/lessons`.

### 2. Ask the agent anything

```bash
# REPL
python scripts/ask.py

# one-shot
python scripts/ask.py "what was my best trade this week?"

# stream tokens as they come
python scripts/ask.py --stream "explain trade 9"
```

Or open `http://127.0.0.1:8000/chat` for the dashboard chat (mobile-friendly).
Both use the same backend (`agent/conversation/context.py`) so they share
context-injection logic — every turn the agent receives a tight CONTEXT block
with relevant trades, today's bias, and recent lessons.

The chat understands references like `trade #42` or `lesson 7` and pulls the
full record automatically. It also knows your TF preferences (D1/H4 bias-only,
M15/H1 entries) and refuses to invent levels it can't see.

### 3. Generate the weekly retrospective (Friday close)

```bash
python scripts/retrospective.py                 # current week
python scripts/retrospective.py --week 2026-04-27   # any week
python scripts/retrospective.py --no-llm        # deterministic template
```

Clusters losing lessons by failure mode (`no_setup_at_all`,
`agent_disagreed`, `agent_weak_agree`, `both_wrong`) and asks the LLM for a
5-bullet review tagged WIN PATTERN / LOSS PATTERN / AGENT GAP / NEXT WEEK
FOCUS / RISK NOTE. Saved to `weekly_retrospectives` for cross-week
comparison.

---

## New ICT-style detectors (used by both agent and teach replay)

| Detector                              | Module                                  | What it tags                                                       |
|---------------------------------------|-----------------------------------------|---------------------------------------------------------------------|
| **Sessions** (Asia/London/NY/overlap) | `agent/detectors/sessions.py`           | `session_<label>` confluence (kill zones only count toward min_conf) |
| **Daily levels** (PDH/PDL/PDM/PWH/PWL)| `agent/detectors/daily_levels.py`       | `near_PDH` / `near_PDL` / `near_PDM` / `near_PWH` / `near_PWL`      |
| **Liquidity sweep** (tagged)          | `agent/detectors/liquidity_sweep.py`    | `sweep_PDH` / `sweep_swing_high` / `sweep_equal_lows` ...           |
| **Range phase** (PO3)                 | `agent/detectors/range_phase.py`        | `phase_distribution` (counted) + `phase_manipulation` (advisory)    |

These are wired into `agent/rules/engine.py` automatically — every new
backtest will surface them as confluences with proper TF attribution
(e.g. `near_PDH (D1)` so you know which chart to verify on).

---

## Database schema (new tables)

| Table                    | Purpose                                                     |
|--------------------------|-------------------------------------------------------------|
| `human_lessons`          | Your discretionary trades + reasoning (extracted by LLM)    |
| `agent_disagreements`    | Per-lesson side-by-side diff vs. what the agent would do    |
| `weekly_retrospectives`  | Friday auto-summary + failure-mode clusters                 |
| `chat_sessions`          | Conversation containers                                     |
| `chat_messages`          | Individual chat turns + injected context                    |

All idempotent — running `Journal(path)` on an old DB migrates in place.

---

## Privacy & resource notes

* Every model + every byte of journal data lives on your laptop.
* qwen2.5:14b runs at ~25–30 tok/s on M4 Mac (acceptable for batch teach).
* qwen2.5:7b runs at ~50–60 tok/s on M4 Mac (interactive feel for chat).
* Ollama is happy to share GPU with other apps — peak RSS is ~10 GB combined.

---

## Next-up roadmap items (after partner mode)

* Vision: drop a chart screenshot into `/chat`, agent extracts levels via a
  vision-capable Ollama model (e.g. `llava` or `qwen2.5-vl`).
* Voice round-trip: pair Whisper (input) with `edge-tts` (output) for a
  hands-free chart-watching mode.
* Real-time MT5 co-pilot: agent watches live ticks while you trade and
  pings you when its read disagrees with your plan.
