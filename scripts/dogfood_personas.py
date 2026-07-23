"""Dogfood harness — drive the platform through the test-persona cast.

Reads the persona roster from ``company/rd/personas/`` and walks a REAL
platform server (the exact handler stack ``scripts/serve_platform.py``
serves) through each persona's journeys: onboarding, broker-wizard
failure paths, kill-switch round-trip, approval queue via the
internal-token seam, alerts test event, and page smoke checks. Every
friction point (unexpected status, missing copy, dead end) is printed
as a CANDIDATE INTAKE item for the User Advocate and written to the
dogfood report.

Safety design (why the server runs IN-PROCESS, not as a subprocess):

- ``agent.platform.credentials`` prefers the OS keychain and only
  exposes ``force_fallback()`` as an in-process seam. A subprocess
  ``serve_platform.py`` would write dogfood secrets into — and
  ``/api/onboarding/reset`` could DELETE real secrets from — the
  operator's actual keychain. Starting the same ``make_handler``
  stack in-process lets us pin ``force_fallback(True)`` plus an
  isolated temp config dir, so no dogfood run can touch real state.
- All credentials used are obviously fake; live mode is never touched
  (there is deliberately no journey step for ``/api/live-mode/enable``).
- ``/api/approvals/submit`` reads its internal token from
  ``<repo>/platform.toml`` (gitignored). When that file is absent we
  create a temporary one with a random token and remove it afterwards;
  when it exists we NEVER modify it — we reuse its token if set, else
  run the fail-closed 401 check only.

Usage::

    .venv/bin/python scripts/dogfood_personas.py            # full run
    .venv/bin/python scripts/dogfood_personas.py --out /tmp/dogfood
"""
from __future__ import annotations

import argparse
import json
import platform as _platform_mod
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PERSONAS_DIR = REPO_ROOT / "company" / "rd" / "personas"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "dogfood"
PLATFORM_TOML = REPO_ROOT / "platform.toml"

# Obviously-fake material only. Never real credentials, never live mode.
DOGFOOD_PASSPHRASE = "dogfood-only-passphrase-2026"
FAKE_LOGIN = "12345678"
FAKE_PASSWORD = "dogfood-fake-password-NOT-REAL"  # noqa: S105 -- deliberate fake
FAKE_SERVER = "MetaQuotes-Demo"

_REQUIRED_PERSONA_FIELDS = ("id", "name", "archetype", "goals",
                            "risk_tolerance", "devices", "tests")

_KNOWN_SURFACES = ("onboarding", "broker", "kill_switch", "approvals",
                   "alerts", "research", "hq_org", "pages")

_SMOKE_PAGES = ("/", "/onboarding", "/settings/kill-switches",
                "/settings/broker", "/settings/live-mode", "/risk",
                "/approvals", "/alerts", "/hq", "/performance",
                "/research")


# ---------------------------------------------------------------------------
# Pure logic: front-matter parsing + persona loading (unit-tested)
# ---------------------------------------------------------------------------

def parse_front_matter(text: str) -> dict:
    """Parse the YAML-subset front-matter block of a persona doc.

    Supports scalars, flat lists (``- item``), and nested mappings by
    two-space indentation — exactly the shapes the persona template
    uses. Raises ValueError when the ``---`` fences are missing.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening --- front-matter fence")
    try:
        end = next(i for i in range(1, len(lines))
                   if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("missing closing --- front-matter fence")
    block = lines[1:end]
    parsed, _ = _parse_mapping(block, 0, 0)
    return parsed


def _strip_scalar(raw: str):
    val = raw.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    if val == "":
        return ""
    lowered = val.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return val


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_mapping(lines: list[str], start: int, indent: int):
    """Parse a mapping at ``indent`` starting from ``lines[start]``.
    Returns (dict, next_index)."""
    out: dict = {}
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        cur = _indent_of(line)
        if cur < indent:
            break
        if cur > indent:
            raise ValueError(f"unexpected indent at line: {line!r}")
        key, sep, rest = line.strip().partition(":")
        if not sep:
            raise ValueError(f"expected 'key:' at line: {line!r}")
        rest = rest.strip()
        if rest:
            out[key] = _strip_scalar(rest)
            i += 1
            continue
        # Block value: list or nested mapping (or empty → empty string).
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or _indent_of(lines[j]) <= cur:
            out[key] = ""
            i += 1
            continue
        child_indent = _indent_of(lines[j])
        if lines[j].lstrip().startswith("- "):
            items = []
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    j += 1
                    continue
                if _indent_of(nxt) < child_indent \
                        or not nxt.lstrip().startswith("- "):
                    break
                items.append(_strip_scalar(nxt.lstrip()[2:]))
                j += 1
            out[key] = items
            i = j
        else:
            child, j = _parse_mapping(lines, j, child_indent)
            out[key] = child
            i = j
    return out, i


@dataclass
class Persona:
    id: str
    name: str
    archetype: str
    goals: list
    risk_tolerance: str
    devices: list
    tests: list
    path: str
    extra: dict = field(default_factory=dict)


def load_personas(personas_dir: Path | None = None) -> list[Persona]:
    """Load every ``P*.md`` persona doc, validated and sorted by id."""
    directory = Path(personas_dir) if personas_dir else PERSONAS_DIR
    personas: list[Persona] = []
    seen: set[str] = set()
    for md in sorted(directory.glob("P*.md")):
        meta = parse_front_matter(md.read_text(encoding="utf-8"))
        missing = [k for k in _REQUIRED_PERSONA_FIELDS if not meta.get(k)]
        if missing:
            raise ValueError(f"{md.name}: missing front-matter "
                             f"fields {missing}")
        pid = str(meta["id"])
        if pid in seen:
            raise ValueError(f"duplicate persona id {pid} in {md.name}")
        seen.add(pid)
        unknown = [t for t in meta["tests"] if t not in _KNOWN_SURFACES]
        if unknown:
            raise ValueError(f"{md.name}: unknown test surfaces {unknown}")
        extra = {k: v for k, v in meta.items()
                 if k not in _REQUIRED_PERSONA_FIELDS}
        personas.append(Persona(
            id=pid, name=str(meta["name"]),
            archetype=str(meta["archetype"]), goals=list(meta["goals"]),
            risk_tolerance=str(meta["risk_tolerance"]),
            devices=list(meta["devices"]), tests=list(meta["tests"]),
            path=str(md), extra=extra))
    return personas


# ---------------------------------------------------------------------------
# Pure logic: journey assembly (unit-tested)
# ---------------------------------------------------------------------------
#
# A step is a plain dict:
#   label, method, path, payload (dict|None), headers (dict),
#   expect_status (tuple of ints), contains (list of substrings),
#   json_true / json_false / json_nonempty / json_empty (dotted paths),
#   save (json field -> context var), needs_internal_token (bool).
# Templates {internal_token} / {approval_id} are resolved at run time.

def _step(label, method, path, *, payload=None, headers=None,
          expect_status=(200,), contains=(), json_true=(),
          json_false=(), json_nonempty=(), json_empty=(),
          save=None, needs_internal_token=False) -> dict:
    return {
        "label": label, "method": method, "path": path,
        "payload": payload, "headers": dict(headers or {}),
        "expect_status": tuple(expect_status),
        "contains": list(contains),
        "json_true": list(json_true), "json_false": list(json_false),
        "json_nonempty": list(json_nonempty),
        "json_empty": list(json_empty),
        "save": save, "needs_internal_token": needs_internal_token,
    }


def _onboarding_journey() -> dict:
    return {"name": "onboarding", "pre": None, "steps": [
        _step("wizard state loads", "GET", "/api/onboarding/state"),
        _step("passphrase accepted", "POST", "/api/onboarding/passphrase",
              payload={"passphrase": DOGFOOD_PASSPHRASE}, json_true=["ok"]),
        _step("default pairs saved", "POST", "/api/onboarding/pairs",
              payload={"pairs": ["EURUSD", "GBPUSD", "USDCAD"]},
              json_true=["ok"]),
        _step("setup marked complete", "POST", "/api/onboarding/complete",
              json_true=["ok"]),
        _step("state shows completed", "GET", "/api/onboarding/state",
              json_true=["completed"]),
    ]}


def _broker_journey() -> dict:
    fake = {"login": FAKE_LOGIN, "password": FAKE_PASSWORD,
            "server": FAKE_SERVER}
    steps = [
        _step("fake creds fail with friendly copy", "POST",
              "/api/broker/test-connection", payload=dict(fake),
              json_false=["success"], json_nonempty=["error_message"]),
        _step("off-allow-list server rejected", "POST",
              "/api/broker/test-connection",
              payload={**fake, "server": "evil-broker"},
              json_false=["success"], contains=["allow-list"]),
    ]
    for n in range(2, 6):  # attempts 2..5 fill the 5/60s window
        steps.append(_step(f"retry attempt {n}", "POST",
                           "/api/broker/test-connection",
                           payload=dict(fake), json_false=["success"]))
    steps.append(_step("rate limiter engages on 6th attempt", "POST",
                       "/api/broker/test-connection", payload=dict(fake),
                       json_false=["success"],
                       contains=["Too many attempts"]))
    return {"name": "broker", "pre": "reset_broker_rate_limiter",
            "steps": steps}


def _kill_switch_journey(persona_id: str) -> dict:
    return {"name": "kill_switch", "pre": None, "steps": [
        _step("baseline: nothing killed", "GET",
              "/api/kill-switches/status", json_empty=["killed_scopes"]),
        _step("global kill activates", "POST",
              "/api/kill-switches/activate",
              payload={"symbol": "GLOBAL",
                       "reason": f"dogfood drill ({persona_id})",
                       "by": persona_id},
              json_true=["ok"]),
        _step("status shows the kill", "GET",
              "/api/kill-switches/status",
              json_nonempty=["killed_scopes"]),
        _step("global kill clears", "POST", "/api/kill-switches/clear",
              payload={"symbol": "GLOBAL"}, json_true=["ok"]),
        _step("status back to clean", "GET", "/api/kill-switches/status",
              json_empty=["killed_scopes"]),
    ]}


def _approval_entry(persona_id: str, rationale: str) -> dict:
    return {
        "symbol": "EURUSD", "side": "buy", "size": 0.01,
        "entry": 1.0850, "stop": 1.0800, "take_profit": 1.0950,
        "rationale": f"{rationale} (dogfood, {persona_id})",
        "source_agent": f"dogfood_{persona_id}",
        "risk_snapshot": {"worst_case_loss": 5.0},
    }


def _approvals_journey(persona_id: str) -> dict:
    return {"name": "approvals", "pre": None, "steps": [
        _step("submit without token fails closed", "POST",
              "/api/approvals/submit",
              payload=_approval_entry(persona_id, "no-token probe"),
              expect_status=(401,), contains=["internal-token required"]),
        _step("submit with internal token", "POST",
              "/api/approvals/submit",
              payload=_approval_entry(persona_id, "approve-path proposal"),
              headers={"X-Bluelock-Internal-Token": "{internal_token}"},
              json_true=["ok"], save=("id", "approval_id"),
              needs_internal_token=True),
        _step("queue lists the entry", "GET", "/api/approvals/list",
              json_nonempty=["entries"], needs_internal_token=True),
        _step("approve round-trip", "POST",
              "/api/approvals/{approval_id}/approve", json_true=["ok"],
              needs_internal_token=True),
        _step("second submit for reject path", "POST",
              "/api/approvals/submit",
              payload=_approval_entry(persona_id, "reject-path proposal"),
              headers={"X-Bluelock-Internal-Token": "{internal_token}"},
              json_true=["ok"], save=("id", "approval_id"),
              needs_internal_token=True),
        _step("reject round-trip", "POST",
              "/api/approvals/{approval_id}/reject",
              payload={"reason": "dogfood reject-path drill"},
              json_true=["ok"], needs_internal_token=True),
    ]}


def _alerts_journey() -> dict:
    return {"name": "alerts", "pre": None, "steps": [
        _step("synthetic test event publishes", "POST", "/api/alerts/test",
              json_true=["ok"], contains=["trade_fill"]),
        _step("recent feed shows the event", "GET", "/api/alerts/recent",
              json_nonempty=["events"], contains=["trade_fill"]),
    ]}


def _research_journey() -> dict:
    return {"name": "research", "pre": None, "steps": [
        _step("/research page renders", "GET", "/research",
              contains=["<html", "Research"]),
        _step("verdicts API answers", "GET", "/api/research/verdicts"),
    ]}


def _hq_org_journey() -> dict:
    return {"name": "hq_org", "pre": None, "steps": [
        _step("/hq shows Org & Flow", "GET", "/hq",
              contains=["Org &amp; Flow"]),
        _step("org API returns the three blocks", "GET", "/api/hq/org",
              json_nonempty=["tiers", "review_chain"]),
    ]}


def _pages_journey() -> dict:
    steps = [_step(f"page {p} loads", "GET", p,
                   contains=["<html"]) for p in _SMOKE_PAGES]
    return {"name": "pages", "pre": None, "steps": steps}


def build_journeys(persona: Persona) -> list[dict]:
    """Assemble the ordered journey list for one persona from its
    ``tests:`` surfaces. Pure — no I/O, no server."""
    builders = {
        "onboarding": _onboarding_journey,
        "broker": _broker_journey,
        "kill_switch": lambda: _kill_switch_journey(persona.id),
        "approvals": lambda: _approvals_journey(persona.id),
        "alerts": _alerts_journey,
        "research": _research_journey,
        "hq_org": _hq_org_journey,
        "pages": _pages_journey,
    }
    return [builders[surface]() for surface in persona.tests]


# ---------------------------------------------------------------------------
# Pure logic: friction classification + candidate intake (unit-tested)
# ---------------------------------------------------------------------------

def collect_frictions(results: list[dict]) -> list[dict]:
    """Pick out every failed step from run results."""
    return [r for r in results if not r["ok"] and not r.get("skipped")]


def format_candidate_intake(friction: dict) -> str:
    """Render one friction record as a CANDIDATE INTAKE block for the
    User Advocate to triage."""
    return "\n".join([
        "CANDIDATE INTAKE",
        f"  persona:  {friction['persona']} ({friction['persona_name']})",
        f"  journey:  {friction['journey']} / {friction['label']}",
        f"  request:  {friction['method']} {friction['path']}",
        f"  status:   {friction['status']} "
        f"(expected {list(friction['expect_status'])})",
        f"  problem:  {friction['problem']}",
        f"  evidence: {friction['body_excerpt']}",
    ])


# ---------------------------------------------------------------------------
# Harness: in-process server + HTTP runner
# ---------------------------------------------------------------------------

class DogfoodHarness:
    """Owns the temp config dir, the in-process server, and the
    internal-token lifecycle."""

    def __init__(self) -> None:
        self.tmp: Path | None = None
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.base_url: str = ""
        self.internal_token: str | None = None
        self._created_platform_toml = False

    def start(self) -> None:
        from agent.platform import credentials
        from scripts.serve_platform import make_handler

        self.tmp = Path(tempfile.mkdtemp(prefix="bluelock_dogfood_"))
        (self.tmp / "logs").mkdir()
        (self.tmp / "reviews").mkdir()
        credentials.set_config_dir(self.tmp / "config")
        credentials.force_fallback(True)  # never the real OS keychain
        credentials.set_encrypted_file_passphrase(DOGFOOD_PASSPHRASE)

        self._setup_internal_token()

        handler = make_handler(
            log_root=self.tmp / "logs",
            repo_root=REPO_ROOT,
            reviews_dir=self.tmp / "reviews",
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def _setup_internal_token(self) -> None:
        """The approvals submit gate reads ``<repo>/platform.toml``
        (gitignored). Absent → create a temp one with a random token
        and remove it on stop. Present → reuse its token if set, never
        modify the operator's file."""
        if PLATFORM_TOML.exists():
            import tomllib
            try:
                raw = tomllib.loads(
                    PLATFORM_TOML.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                raw = {}
            token = (raw.get("internal") or {}).get("token") or ""
            self.internal_token = token or None
            return
        token = "dogfood-" + secrets.token_hex(16)
        PLATFORM_TOML.write_text(
            "# TEMPORARY — written by scripts/dogfood_personas.py; "
            "deleted at the end of the run.\n"
            f'[internal]\ntoken = "{token}"\n', encoding="utf-8")
        self._created_platform_toml = True
        self.internal_token = token

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self._created_platform_toml and PLATFORM_TOML.exists():
            PLATFORM_TOML.unlink()
        from agent.platform import credentials
        credentials.set_config_dir(None)
        credentials.force_fallback(False)
        credentials.set_encrypted_file_passphrase(None)

    def cleanup_tmp(self) -> None:
        if self.tmp is not None and self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    # -- journey pre-hooks --------------------------------------------------

    def run_pre_hook(self, name: str | None) -> None:
        if name == "reset_broker_rate_limiter":
            from agent.platform import broker_connection
            broker_connection.reset_rate_limiter()


def _dotted_get(obj, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _http(base_url: str, method: str, path: str, payload: dict | None,
          headers: dict) -> tuple[int, str]:
    data = None
    req_headers = dict(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base_url + path, data=data,
                                 headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, f"(transport error: {exc})"


def run_step(base_url: str, step: dict, ctx: dict,
             persona: Persona, journey_name: str) -> dict:
    """Execute one step and evaluate all its checks."""
    path = step["path"].format(**{k: str(v) for k, v in ctx.items()})
    headers = {k: v.format(**{kk: str(vv) for kk, vv in ctx.items()})
               for k, v in step["headers"].items()}
    status, body = _http(base_url, step["method"], path,
                         step["payload"], headers)

    problems: list[str] = []
    if status not in step["expect_status"]:
        problems.append(f"unexpected HTTP status {status}")
    parsed = None
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        parsed = None
    for needle in step["contains"]:
        if needle not in body:
            problems.append(f"expected copy missing: {needle!r}")
    for fld in step["json_true"]:
        if not _dotted_get(parsed, fld):
            problems.append(f"expected truthy JSON field {fld!r}")
    for fld in step["json_false"]:
        if _dotted_get(parsed, fld):
            problems.append(f"expected falsy JSON field {fld!r}")
    for fld in step["json_nonempty"]:
        val = _dotted_get(parsed, fld)
        if not val:
            problems.append(f"expected non-empty JSON field {fld!r}")
    for fld in step["json_empty"]:
        val = _dotted_get(parsed, fld)
        if val:
            problems.append(f"expected empty JSON field {fld!r}, "
                            f"got {val!r}")
    if "Traceback (most recent call last)" in body:
        problems.append("stack trace leaked into the response body")

    if not problems and step["save"] and isinstance(parsed, dict):
        json_field, var = step["save"]
        val = _dotted_get(parsed, json_field)
        if val:
            ctx[var] = val
        else:
            problems.append(f"save field {json_field!r} absent")

    return {
        "persona": persona.id, "persona_name": persona.name,
        "journey": journey_name, "label": step["label"],
        "method": step["method"], "path": path, "status": status,
        "expect_status": list(step["expect_status"]),
        "ok": not problems, "skipped": False,
        "problem": "; ".join(problems),
        "body_excerpt": body[:220].replace("\n", " "),
    }


def run_persona(harness: DogfoodHarness, persona: Persona) -> list[dict]:
    results: list[dict] = []
    for journey in build_journeys(persona):
        harness.run_pre_hook(journey["pre"])
        ctx: dict = {"internal_token": harness.internal_token or ""}
        for step in journey["steps"]:
            if step["needs_internal_token"] and not harness.internal_token:
                results.append({
                    "persona": persona.id, "persona_name": persona.name,
                    "journey": journey["name"], "label": step["label"],
                    "method": step["method"], "path": step["path"],
                    "status": None, "expect_status":
                        list(step["expect_status"]),
                    "ok": True, "skipped": True,
                    "problem": "skipped: no internal token available "
                               "(existing platform.toml without one)",
                    "body_excerpt": "",
                })
                continue
            result = run_step(harness.base_url, step, ctx,
                              persona, journey["name"])
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(out_dir: Path, personas: list[Persona],
                 results: list[dict], frictions: list[dict],
                 started_at: str, elapsed_s: float) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ran = [r for r in results if not r["skipped"]]
    payload = {
        "started_at": started_at,
        "elapsed_seconds": round(elapsed_s, 2),
        "host_platform": _platform_mod.platform(),
        "personas": [p.id for p in personas],
        "steps_total": len(results),
        "steps_run": len(ran),
        "steps_passed": sum(1 for r in ran if r["ok"]),
        "steps_skipped": sum(1 for r in results if r["skipped"]),
        "frictions": frictions,
        "results": results,
    }
    json_path = out_dir / f"dogfood_{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n",
                         encoding="utf-8")

    lines = [
        f"# Dogfood report — {stamp}",
        "",
        f"- started: {started_at}  ({elapsed_s:.1f}s)",
        f"- host: {_platform_mod.platform()}",
        f"- personas: {', '.join(p.id for p in personas)}",
        f"- steps: {payload['steps_passed']}/{payload['steps_run']} "
        f"passed ({payload['steps_skipped']} skipped)",
        f"- frictions: {len(frictions)}",
        "",
        "| persona | journey | step | status | ok |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        mark = "skip" if r["skipped"] else ("PASS" if r["ok"] else "FAIL")
        lines.append(f"| {r['persona']} | {r['journey']} | {r['label']} "
                     f"| {r['status']} | {mark} |")
    if frictions:
        lines += ["", "## Candidate intake items", ""]
        for f in frictions:
            lines += ["```", format_candidate_intake(f), "```", ""]
    md_path = out_dir / f"dogfood_{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive the platform through the test-persona cast.")
    parser.add_argument("--personas-dir", type=Path, default=PERSONAS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                        help="report output dir (reports/ is gitignored)")
    parser.add_argument("--persona", action="append", default=None,
                        help="run only these persona ids (repeatable)")
    args = parser.parse_args(argv)

    personas = load_personas(args.personas_dir)
    if args.persona:
        wanted = set(args.persona)
        personas = [p for p in personas if p.id in wanted]
        if not personas:
            print(f"no personas matched {sorted(wanted)}", file=sys.stderr)
            return 2

    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    harness = DogfoodHarness()
    results: list[dict] = []
    try:
        harness.start()
        print(f"dogfood server up at {harness.base_url} "
              f"(config dir {harness.tmp})")
        for persona in personas:
            print(f"-- {persona.id} {persona.name} "
                  f"({persona.archetype}) --")
            persona_results = run_persona(harness, persona)
            results.extend(persona_results)
            for r in persona_results:
                mark = ("skip" if r["skipped"]
                        else ("ok  " if r["ok"] else "FAIL"))
                print(f"   [{mark}] {r['journey']:<12} {r['label']}")
    finally:
        harness.stop()
        harness.cleanup_tmp()

    frictions = collect_frictions(results)
    elapsed = time.monotonic() - t0
    json_path, md_path = write_report(args.out, personas, results,
                                      frictions, started_at, elapsed)

    ran = [r for r in results if not r["skipped"]]
    print(f"\n{sum(1 for r in ran if r['ok'])}/{len(ran)} steps passed, "
          f"{sum(1 for r in results if r['skipped'])} skipped, "
          f"{len(frictions)} friction(s).")
    print(f"report: {json_path}\nreport: {md_path}")
    for friction in frictions:
        print()
        print(format_candidate_intake(friction))
    return 1 if frictions else 0


if __name__ == "__main__":
    raise SystemExit(main())
