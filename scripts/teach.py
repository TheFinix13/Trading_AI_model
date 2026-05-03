"""Ingest free-form trading paragraphs into the journal as structured lessons.

Usage:

    # interactive (default) — paste a paragraph, confirm, save:
    python scripts/teach.py

    # ingest from a file (one trade per --- separator):
    python scripts/teach.py --file my_week.txt

    # ingest from stdin (e.g. from `pbpaste`):
    pbpaste | python scripts/teach.py --stdin

    # voice mode (requires `whisper-cpp` or `openai-whisper` available):
    python scripts/teach.py --voice

    # mock mode (no Ollama needed — for testing the pipeline):
    python scripts/teach.py --mock --file fixtures/sample_lessons.txt

Each lesson is:
  1. Sent to the LLM extractor (qwen2.5:14b-instruct by default) -> TradeLesson JSON
  2. Shown back to you in a compact CLI panel for confirmation/edit
  3. Logged to ``human_lessons``
  4. Replayed against the agent at the same timestamp -> ``agent_disagreements``

The diff is printed inline so you can see the moment we save what the agent
would have done versus what you did. That's the human-vs-agent feedback loop.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.config import load_config
from agent.conversation.replay import ReplayDiffer
from agent.journal.db import Journal
from agent.llm.extractor import LessonExtractor, TradeLesson
from agent.llm.ollama import OllamaUnavailable

log = logging.getLogger(__name__)


# ---------- mock extractor for offline testing -------------------------------

def _mock_extract(text: str) -> TradeLesson:
    """Deterministic skeleton-extractor when Ollama is unavailable.
    Doesn't really 'extract' — it scaffolds an empty lesson the user can fill in
    by editing the YAML the script offers. Useful for tests and when Ollama
    isn't running yet."""
    return TradeLesson(
        symbol="EURUSD",
        trade_date=date.today(),
        direction="long",
        entry_price=1.0,
        outcome="open",
        notes="MOCK extraction — please edit this lesson before saving.",
        raw_text=text.strip(),
    )


# ---------- pretty-print helpers ---------------------------------------------

def _hr(width: int = 78) -> str:
    return "-" * width


def _render_lesson(lesson: TradeLesson) -> str:
    confs = "\n".join(
        f"  - {c.tf:>3s}  {c.type:<22s}  {c.detail}" for c in lesson.confluences
    ) or "  (none)"
    return (
        f"{_hr()}\n"
        f"  date     : {lesson.trade_date}     symbol: {lesson.symbol}\n"
        f"  direction: {lesson.direction:<5s}    outcome: {lesson.outcome}\n"
        f"  entry    : {lesson.entry_price:.5f}    stop: "
        f"{(lesson.stop_price if lesson.stop_price is not None else '—'):>7}    "
        f"tp: {(lesson.tp_price if lesson.tp_price is not None else '—'):>7}\n"
        f"  P&L      : {(lesson.pnl_pips if lesson.pnl_pips is not None else 0):+.1f} pips    "
        f"${(lesson.pnl_usd if lesson.pnl_usd is not None else 0):+.2f}\n"
        f"  session  : {lesson.session or '—'}    emotion: {lesson.emotion}\n"
        f"  bias     : {lesson.daily_bias or '—'}\n"
        f"  confluences:\n{confs}\n"
        f"  notes    : {lesson.notes or '—'}\n"
        f"{_hr()}"
    )


def _render_diff(diff) -> str:
    return (
        f"  AGENT DIFF\n"
        f"  agreement: {diff.agreement}\n"
        f"  {diff.diff_summary}"
    )


# ---------- input modes -------------------------------------------------------

def _read_interactive() -> str:
    print("\nPaste your paragraph about ONE trade. End with a blank line:")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            else:
                continue
        lines.append(line)
    return "\n".join(lines).strip()


def _read_file(path: Path) -> list[str]:
    """Split file by `---` separators (one trade per chunk). Empty chunks dropped."""
    text = path.read_text()
    chunks = [c.strip() for c in text.split("\n---\n")]
    return [c for c in chunks if c]


def _read_stdin() -> str:
    return sys.stdin.read().strip()


def _read_voice() -> str:
    """Try whisper-cpp first, then openai-whisper, fall back to instructions."""
    print("\nVoice mode requested. The script will try to record 60s of audio "
          "and transcribe it.")
    try:
        import sounddevice as sd  # type: ignore
        import scipy.io.wavfile as wav  # type: ignore
    except ImportError:
        print("\nVoice mode needs: pip install sounddevice scipy openai-whisper")
        print("Skipping for now — paste the transcript manually below.")
        return _read_interactive()

    try:
        import whisper  # type: ignore
    except ImportError:
        print("\nNo `whisper` package. Install: pip install openai-whisper")
        return _read_interactive()

    print("Recording 60 seconds — speak now (Ctrl-C to stop early)...")
    fs = 16000
    try:
        audio = sd.rec(int(60 * fs), samplerate=fs, channels=1, dtype="int16")
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
    tmp = PROJECT_ROOT / ".cache" / "voice_in.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    wav.write(tmp, fs, audio)
    print("Transcribing with whisper (base model)... ")
    model = whisper.load_model("base")
    result = model.transcribe(str(tmp))
    text = (result.get("text") or "").strip()
    print(f"\n[VOICE TRANSCRIPT]\n{text}\n")
    return text


# ---------- main loop ---------------------------------------------------------

def _process_one(
    text: str,
    extractor: LessonExtractor | None,
    journal: Journal,
    differ: ReplayDiffer | None,
    auto_yes: bool,
    use_mock: bool,
) -> bool:
    if not text:
        return False
    print("\nExtracting...")
    try:
        if use_mock or extractor is None:
            lesson = _mock_extract(text)
        else:
            lesson = extractor.extract(text)
    except OllamaUnavailable as e:
        print(f"\nLLM unavailable ({e}). Falling back to mock skeleton — "
              f"please edit before saving.")
        lesson = _mock_extract(text)
    except ValueError as e:
        print(f"\nExtraction failed: {e}")
        return False

    print(_render_lesson(lesson))

    if not auto_yes:
        ans = input("Save this lesson? [Y/n/edit] ").strip().lower()
        if ans in ("n", "no"):
            print("Skipped.")
            return False
        if ans in ("e", "edit"):
            print("(Inline editing not implemented yet — re-run with the corrected paragraph.)")
            return False

    lesson_id = journal.log_human_lesson(lesson)
    print(f"\nSaved as lesson#{lesson_id}.")

    if differ is not None:
        try:
            diff = differ.diff_for_lesson(journal.get_lesson(lesson_id))
            print(_render_diff(diff))
            differ.write_diff(journal, lesson_id, diff)
        except Exception as e:
            print(f"  (replay diff failed: {e})")
    return True


def main():
    p = argparse.ArgumentParser(description="Ingest free-form trading paragraphs as journal lessons.")
    p.add_argument("--file", type=Path, help="Read trades from a file. Separate trades with a line containing only ---")
    p.add_argument("--stdin", action="store_true", help="Read a single trade from stdin")
    p.add_argument("--voice", action="store_true", help="Record + transcribe one trade via whisper")
    p.add_argument("--mock", action="store_true", help="Skip LLM extraction; use deterministic skeleton")
    p.add_argument("--no-replay", action="store_true", help="Skip the agent replay diff")
    p.add_argument("--yes", "-y", action="store_true", help="Don't prompt for confirmation")
    p.add_argument("--model", default=None, help="Override Ollama model (default: qwen2.5:14b-instruct)")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    cfg = load_config()
    journal = Journal(cfg.journal_db)

    extractor: LessonExtractor | None = None
    if not args.mock:
        kwargs = {"model": args.model} if args.model else {}
        extractor = LessonExtractor(**kwargs)
        if not extractor.is_available():
            print("Ollama not reachable / model not pulled. Run:")
            print("  brew install ollama && brew services start ollama")
            print(f"  ollama pull {args.model or 'qwen2.5:14b-instruct'}")
            print("\nFalling back to --mock mode for this run.\n")
            args.mock = True
            extractor = None

    differ = None if args.no_replay else ReplayDiffer(cfg=cfg)

    saved = 0
    if args.file:
        for chunk in _read_file(args.file):
            if _process_one(chunk, extractor, journal, differ, args.yes, args.mock):
                saved += 1
    elif args.stdin:
        if _process_one(_read_stdin(), extractor, journal, differ, args.yes, args.mock):
            saved += 1
    elif args.voice:
        if _process_one(_read_voice(), extractor, journal, differ, args.yes, args.mock):
            saved += 1
    else:
        # interactive loop
        while True:
            text = _read_interactive()
            if not text:
                break
            if _process_one(text, extractor, journal, differ, args.yes, args.mock):
                saved += 1
            again = input("\nAdd another? [y/N] ").strip().lower()
            if again not in ("y", "yes"):
                break

    journal.close()
    print(f"\nDone. {saved} lesson(s) saved to {cfg.journal_db}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
