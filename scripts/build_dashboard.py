"""Build the static progress dashboard (reports/dashboard.html).

Generates a SELF-CONTAINED dark-theme HTML page summarising:

* LIVE AGENT — what the ``main``-branch VM agent actually trades (deployed
  router cells, risk settings, roadmap, ai_context header, test status).
* RESEARCH PROGRAM — headline results read (read-only) from the sibling
  ``finance-research-experiments`` repo's M001 verdict artifacts and the
  E-series experiment registry.
* VALIDATED vs SIM-ONLY — the separation panel: what is trading vs what is
  simulation-only research.

Hard rules honoured here:

* stdlib only (json / pathlib / html / datetime / re / subprocess / argparse).
  Importing this repo's own ``agent.config`` / ``agent.alphas.zone_routing``
  is allowed; importing ANY code from the research repo is NOT — only its
  .md/.json artifacts are read.
* Never prints secret VALUES from .env — key names only.
* Missing/renamed research artifacts degrade to "artifact not found" panels
  instead of crashing.

Regenerate anytime (from repo root):

    ./.venv/bin/python scripts/build_dashboard.py && open reports/dashboard.html

Options:

    --skip-tests    skip the pytest run (test panel shows "not run")
    --output PATH   write somewhere other than reports/dashboard.html
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_ROOT = REPO_ROOT.parent / "finance-research-experiments"
M001_REVIEWS = RESEARCH_ROOT / "programs" / "M001_multi_agent_ensemble" / "reviews"

sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def esc(text: object) -> str:
    return html.escape(str(text))


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def missing_panel(label: str, path: Path) -> str:
    return (
        f'<div class="missing">artifact not found: <code>{esc(label)}</code>'
        f'<br><span class="dim">{esc(path)}</span></div>'
    )


# ---------------------------------------------------------------------------
# LIVE AGENT panel data
# ---------------------------------------------------------------------------

def collect_router_rows() -> list[dict] | None:
    """Deployed cells straight from this repo's routing table."""
    try:
        from agent.alphas.zone_routing import survivors
    except Exception:
        return None
    rows = []
    for symbol, tf, session, entry in survivors():
        ev = entry.evidence
        rows.append({
            "symbol": symbol, "tf": tf, "session": session,
            "mode": entry.mode, "risk_scale": entry.risk_scale,
            "source": ev.source if ev else "?",
            "oos_expectancy": ev.oos_expectancy if ev else None,
        })
    return rows


def collect_risk_settings() -> dict | None:
    """Risk defaults from agent.config (this repo's own code — allowed).

    Uses the pydantic class defaults, NOT load_config(), so nothing from
    .env is pulled in and no secret ever reaches this page.
    """
    try:
        from agent.config import RiskConfig
    except Exception:
        return None
    r = RiskConfig()
    return {
        "Per-trade risk target": f"{r.pct_target:.1%} of balance (conviction band 0.5–2%)",
        "Daily drawdown halt": f"{r.daily_dd_halt_pct:.0%} (emergency close + halt)",
        "Max open positions / symbol": r.max_open_positions,
        "Portfolio open-risk ceiling": f"{r.portfolio_max_open_risk_pct:.0%} of balance across ALL symbols",
        "Lot hard cap (< $300 acct)": r.lot_hard_cap_under_300,
        "Lot hard cap (< $1000 acct)": r.lot_hard_cap_under_1000,
    }


def collect_env_key_names() -> list[str]:
    """Key NAMES only from .env — values are never read into the page."""
    env = read_text(REPO_ROOT / ".env")
    if env is None:
        return []
    names = []
    for line in env.splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            names.append(m.group(1))
    return names


def collect_roadmap() -> list[str] | None:
    text = read_text(REPO_ROOT / "docs" / "ROADMAP.md")
    if text is None:
        return None
    # Grab the "### 1.1 title" / "### Level 0 — today" style headings.
    return re.findall(r"^###\s+(.+)$", text, flags=re.MULTILINE)


def collect_ai_context_header() -> dict | None:
    text = read_text(REPO_ROOT / "ai_context.md")
    if text is None:
        return None
    lines = text.splitlines()
    header = lines[0] if lines else ""
    # First "> vX.Y — **headline**" block gives the latest change.
    m = re.search(r"^> (v[\d.]+) — \*\*(.+?)\*\*", text, flags=re.MULTILINE)
    latest = f"{m.group(1)}: {m.group(2)}" if m else ""
    return {"header": header.lstrip("# "), "latest": latest}


def run_test_suite(skip: bool) -> dict:
    if skip:
        return {"status": "not run", "summary": "pytest skipped (--skip-tests)"}
    py = REPO_ROOT / ".venv" / "bin" / "python"
    cmd = [str(py) if py.exists() else sys.executable, "-m", "pytest", "-q", "--no-header"]
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "error", "summary": f"pytest could not run: {e}"}
    tail = (proc.stdout.strip().splitlines() or ["(no output)"])[-1]
    status = "green" if proc.returncode == 0 else "red"
    return {"status": status, "summary": tail}


# ---------------------------------------------------------------------------
# RESEARCH PROGRAM panel data (read-only artifact reads)
# ---------------------------------------------------------------------------

def collect_research() -> dict:
    out: dict = {}

    role_path = M001_REVIEWS / "g7_role_registry_verdict_phi5-arm4.json"
    role = read_json(role_path)
    out["role_path"] = role_path
    if role:
        roster = []
        for agent_id, rec in role.get("role_registry", {}).items():
            base = role.get("baseline_stats", {}).get(agent_id, {})
            roster.append({
                "agent": agent_id,
                "trades": int(base.get("n_trades", 0)),
                "mean_tqs": base.get("mean_tqs"),
                "roles": rec.get("role_labels", []),
                "retained": rec.get("retained"),
                "reason": rec.get("retention_reason", ""),
            })
        roster.sort(key=lambda r: -r["trades"])
        out["roster"] = roster

    lo1_path = M001_REVIEWS / "g7_leave_one_out_verdict_phi5-arm4.json"
    lo1 = read_json(lo1_path)
    out["lo1_path"] = lo1_path
    if lo1:
        chem = []
        for agent_id, rec in lo1.get("c2_c3", {}).items():
            chem.append({
                "agent": agent_id,
                "c2": rec.get("c2_pass"),
                "c3": rec.get("c3_pass"),
                "c3_reason": rec.get("c3_reason", ""),
            })
        out["chemistry"] = chem

    resim_path = M001_REVIEWS / "phi5_resim_verdict.json"
    resim = read_json(resim_path)
    out["resim_path"] = resim_path
    if resim:
        arm4 = resim.get("arms", {}).get("arm4", {})
        stats = arm4.get("cross_statistics", {})
        out["arm4"] = {
            "tag": arm4.get("tag", "?"),
            "n_trades": stats.get("n_trades"),
            "median_tqs": arm4.get("median_window_mean_tqs"),
            "hit_rate": stats.get("hit_rate"),
            "verdict": arm4.get("verdict", "?"),
            "delta_vs_control": arm4.get("delta_vs_control"),
        }

    ctx_path = RESEARCH_ROOT / "ai_context.md"
    ctx = read_text(ctx_path)
    out["ctx_path"] = ctx_path
    if ctx:
        out["ctx_header"] = ctx.splitlines()[0].lstrip("# ")

    exp_path = RESEARCH_ROOT / "EXPERIMENTS.md"
    exp = read_text(exp_path)
    out["exp_path"] = exp_path
    if exp:
        experiments = []
        # Markdown table rows whose first cell is an E-number.
        for m in re.finditer(r"^\|\s*(E\d{3})\s*\|([^|]+)\|[^|]+\|"
                             r"\s*(?:\*\*)?([^|*]+?)(?:\*\*)?\s*\|", exp,
                             flags=re.MULTILINE):
            eid, name, third = m.group(1), m.group(2).strip(), m.group(3).strip()
            experiments.append({"id": eid, "name": name,
                                "status": third or "planned"})
        out["experiments"] = experiments
    return out


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: #0d1117; --panel: #161b22; --border: #30363d;
  --fg: #e6edf3; --dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --amber: #d29922; --purple: #bc8cff;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 24px 64px;
  background: var(--bg); color: var(--fg);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
.wrap { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 0 0 12px; display: flex; align-items: center; gap: 8px; }
.sub { color: var(--dim); margin-bottom: 28px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 20px; }
.panel {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px 22px;
}
.panel.full { grid-column: 1 / -1; }
.tag {
  display: inline-block; font-size: 11px; font-weight: 700;
  letter-spacing: .06em; text-transform: uppercase;
  padding: 2px 9px; border-radius: 999px;
}
.tag.live   { background: rgba(63,185,80,.15);  color: var(--green);  border: 1px solid rgba(63,185,80,.4); }
.tag.sim    { background: rgba(188,140,255,.12); color: var(--purple); border: 1px solid rgba(188,140,255,.4); }
.tag.warn   { background: rgba(210,153,34,.12);  color: var(--amber);  border: 1px solid rgba(210,153,34,.4); }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 8px 0 4px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); }
th { color: var(--dim); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
tr:last-child td { border-bottom: none; }
code { background: #21262d; padding: 1px 6px; border-radius: 5px; font-size: 12.5px; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 18px; font-size: 13.5px; }
.kv dt { color: var(--dim); } .kv dd { margin: 0; }
.ok  { color: var(--green); font-weight: 600; }
.bad { color: var(--red);   font-weight: 600; }
.dim { color: var(--dim); font-size: 12.5px; }
.big { font-size: 22px; font-weight: 700; }
.stats { display: flex; gap: 28px; flex-wrap: wrap; margin: 6px 0 14px; }
.stat .lbl { color: var(--dim); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.missing {
  border: 1px dashed var(--amber); border-radius: 8px;
  padding: 10px 14px; color: var(--amber); font-size: 13px; margin: 8px 0;
}
ul { margin: 6px 0; padding-left: 22px; } li { margin: 2px 0; }
.banner {
  border-left: 4px solid var(--accent); background: rgba(88,166,255,.08);
  padding: 12px 16px; border-radius: 6px; margin-bottom: 24px; font-size: 14px;
}
.sep { border-left: 4px solid var(--purple); background: rgba(188,140,255,.06); }
"""


def render_live_panel(router, risk, env_keys, roadmap, ctx, tests) -> str:
    parts = ['<div class="panel"><h2><span class="tag live">Live · main branch / VM</span> '
             'Zones agent (demo MT5)</h2>']

    if tests["status"] == "green":
        parts.append(f'<p>Test suite: <span class="ok">PASSING</span> — '
                     f'<code>{esc(tests["summary"])}</code></p>')
    elif tests["status"] == "red":
        parts.append(f'<p>Test suite: <span class="bad">FAILING</span> — '
                     f'<code>{esc(tests["summary"])}</code></p>')
    else:
        parts.append(f'<p class="dim">Test suite: {esc(tests["summary"])}</p>')

    if ctx:
        parts.append(f'<p class="dim">{esc(ctx["header"])}</p>')
        if ctx["latest"]:
            parts.append(f'<p>Latest change — {esc(ctx["latest"])}</p>')

    parts.append("<h3>Deployed cells (routing table)</h3>")
    if router is None:
        parts.append(missing_panel("agent.alphas.zone_routing", REPO_ROOT / "agent/alphas/zone_routing.py"))
    else:
        parts.append("<table><tr><th>Symbol</th><th>TF</th><th>Session</th>"
                     "<th>Mode</th><th>Risk scale</th><th>Evidence</th><th>OOS pips/trade</th></tr>")
        for r in router:
            exp = r["oos_expectancy"]
            exp_txt = "" if exp is None else f"+{exp:.2f}"
            parts.append(
                f"<tr><td><b>{esc(r['symbol'])}</b></td><td>{esc(r['tf'])}</td>"
                f"<td>{esc(r['session'])}</td><td>{esc(r['mode'])}</td>"
                f"<td>{r['risk_scale']:.1f}×</td><td>{esc(r['source'])}</td>"
                f"<td>{exp_txt}</td></tr>")
        parts.append("</table>")

    parts.append("<h3>Risk settings (config defaults)</h3>")
    if risk is None:
        parts.append(missing_panel("agent.config.RiskConfig", REPO_ROOT / "agent/config.py"))
    else:
        parts.append('<dl class="kv">')
        for k, v in risk.items():
            parts.append(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>")
        parts.append("</dl>")

    if env_keys:
        parts.append("<h3>.env keys configured (names only — values never shown)</h3><p>"
                     + " ".join(f"<code>{esc(k)}</code>" for k in env_keys) + "</p>")

    parts.append("<h3>Roadmap (parked items — docs/ROADMAP.md)</h3>")
    if roadmap is None:
        parts.append(missing_panel("docs/ROADMAP.md", REPO_ROOT / "docs/ROADMAP.md"))
    else:
        parts.append("<ul>" + "".join(f"<li>{esc(h)}</li>" for h in roadmap) + "</ul>")

    parts.append("</div>")
    return "".join(parts)


def render_research_panel(res: dict) -> str:
    parts = ['<div class="panel"><h2><span class="tag sim">Sim-only · research repo</span> '
             'M001 multi-agent ensemble</h2>']

    if "ctx_header" in res:
        parts.append(f'<p class="dim">{esc(res["ctx_header"])}</p>')
    else:
        parts.append(missing_panel("research ai_context.md", res["ctx_path"]))

    parts.append(
        '<div class="banner sep"><b>Headlines (2026-07-06):</b> 7-agent roster '
        '(Kunigami retired 2026-07-06) · Arm 4 multi-position aggregator '
        '<b>ADOPTED</b> as the G7-era default · Bachira→Barou cannibalisation '
        'improved 84% → 55.7% under Arm 4 (still the one open C3 flag) · '
        'squad median TQS <b>0.3643</b> over <b>7,273</b> walk-forward trades.</div>')

    arm4 = res.get("arm4")
    parts.append("<h3>Φ5 aggregator re-sim — Arm 4 (adopted)</h3>")
    if arm4:
        hit = f"{arm4['hit_rate']:.1%}" if arm4.get("hit_rate") is not None else "?"
        med = f"{arm4['median_tqs']:.4f}" if arm4.get("median_tqs") is not None else "?"
        delta = arm4.get("delta_vs_control")
        parts.append(
            f'<div class="stats">'
            f'<div class="stat"><div class="lbl">Trades</div><div class="big">{arm4["n_trades"]:,}</div></div>'
            f'<div class="stat"><div class="lbl">Median window TQS</div><div class="big">{med}</div></div>'
            f'<div class="stat"><div class="lbl">Hit rate</div><div class="big">{hit}</div></div>'
            f'<div class="stat"><div class="lbl">Δ vs control</div><div class="big">'
            f'{"" if delta is None else f"{delta:+.4f}"}</div></div>'
            f'</div>'
            f'<p class="dim">Verdict: <code>{esc(arm4["verdict"])}</code> — adoption was on '
            f'roster-health grounds (agents regain volume), not a TQS win.</p>')
    else:
        parts.append(missing_panel("phi5_resim_verdict.json", res["resim_path"]))

    parts.append("<h3>Roster — role registry (phi5-arm4 baseline)</h3>")
    roster = res.get("roster")
    if roster:
        parts.append("<table><tr><th>Agent</th><th>Trades</th><th>Mean TQS</th>"
                     "<th>Roles</th><th>Retained</th></tr>")
        for r in roster:
            tqs = f"{r['mean_tqs']:.4f}" if r["mean_tqs"] is not None else "—"
            trades = f"{r['trades']:,}" if r["trades"] else "0"
            kept = ('<span class="ok">yes</span>' if r["retained"]
                    else '<span class="bad">no</span>')
            roles = ", ".join(r["roles"]) or "—"
            parts.append(f"<tr><td><b>{esc(r['agent'])}</b></td><td>{trades}</td>"
                         f"<td>{tqs}</td><td>{esc(roles)}</td><td>{kept}</td></tr>")
        parts.append("</table>")
        parts.append('<p class="dim">Bachira "not retained" is a C3 cannibalisation FLAG, '
                     'not a removal — he carries 48.8% of squad trades and is Nagi\'s primary '
                     'lifter; the fix is routed to Phase W-barou v1.2 H2. Kunigami\'s row is a '
                     'retirement artefact (no leave-one-out cache by design).</p>')
    else:
        parts.append(missing_panel("g7_role_registry_verdict_phi5-arm4.json", res["role_path"]))

    parts.append("<h3>Chemistry gates (leave-one-out C2 / C3)</h3>")
    chem = res.get("chemistry")
    if chem:
        parts.append("<table><tr><th>Agent</th><th>C2 lifts a peer</th><th>C3 no cannibalisation</th></tr>")
        for c in chem:
            c2 = '<span class="ok">pass</span>' if c["c2"] else '<span class="bad">fail</span>'
            c3 = '<span class="ok">pass</span>' if c["c3"] else \
                 f'<span class="bad">fail</span> <span class="dim">{esc(c["c3_reason"])}</span>'
            parts.append(f"<tr><td><b>{esc(c['agent'])}</b></td><td>{c2}</td><td>{c3}</td></tr>")
        parts.append("</table>")
    else:
        parts.append(missing_panel("g7_leave_one_out_verdict_phi5-arm4.json", res["lo1_path"]))

    parts.append("<h3>E-series experiment registry</h3>")
    exps = res.get("experiments")
    if exps:
        parts.append("<table><tr><th>ID</th><th>Study</th><th>Status / verdict</th></tr>")
        for e in exps:
            parts.append(f"<tr><td><code>{esc(e['id'])}</code></td>"
                         f"<td>{esc(e['name'])}</td><td>{esc(e['status'])}</td></tr>")
        parts.append("</table>")
    else:
        parts.append(missing_panel("EXPERIMENTS.md", res["exp_path"]))

    parts.append("</div>")
    return "".join(parts)


def render_separation_panel() -> str:
    return """
<div class="panel full">
<h2><span class="tag warn">Read this first</span> Validated vs sim-only — what is actually trading</h2>
<table>
<tr><th>Track</th><th>Status</th><th>What it is</th></tr>
<tr><td><b>Zones strategy (<code>zone_d1_against</code>)</b></td>
    <td><span class="ok">LIVE on demo MT5</span></td>
    <td>The VM agent (<code>main</code> branch) trades this and ONLY this: H4 supply/demand
        zone touches faded against the D1 trend, on EURUSD (1.0×), GBPUSD (0.5×),
        USDCAD (0.5×), with the full safety layer (daily-DD halt, kill switch,
        portfolio 5% risk cap, wick-proof + BE stack).</td></tr>
<tr><td><b>Safety-layer posture</b></td>
    <td><span class="ok">VALIDATED (E013)</span></td>
    <td>E013 measured the safety layer's contribution: combined Δ +0.80 Sharpe
        (BH-reject). The EXISTING posture is validated; no change was needed.</td></tr>
<tr><td><b>M001 multi-agent ensemble</b></td>
    <td><span class="bad">SIM-ONLY — not trading</span></td>
    <td>Everything in the research panel (7-agent roster, TQS numbers, Arm 4
        aggregator, chemistry gates) runs in simulation inside
        <code>finance-research-experiments</code>. Zero lots at risk. Nothing from
        M001 ships to production until it passes a graduation gate and this repo's
        validation pipeline — a hard workspace rule.</td></tr>
<tr><td><b><code>next-gen</code> branch (this branch)</b></td>
    <td><span class="tag sim">platform line</span></td>
    <td>The next-generation platform line, kept fully separate from <code>main</code>
        (the VM agent's branch). Dashboards/runbooks/platform work land here; the
        intent is to graduate research-validated strategies here for heavier trading
        later. <code>main</code> stays untouched.</td></tr>
</table>
</div>"""


def build_page(skip_tests: bool) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tests = run_test_suite(skip_tests)
    live = render_live_panel(
        collect_router_rows(), collect_risk_settings(),
        collect_env_key_names(), collect_roadmap(),
        collect_ai_context_header(), tests,
    )
    research = render_research_panel(collect_research())
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading platform — progress dashboard</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<h1>Multi-pair trading platform — progress dashboard</h1>
<div class="sub">Generated {now} · branch line: <code>next-gen</code> ·
regenerate with <code>./.venv/bin/python scripts/build_dashboard.py</code></div>
{render_separation_panel()}
<div class="grid">
{live}
{research}
</div>
</div></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-tests", action="store_true",
                    help="skip the pytest run (faster; panel shows 'not run')")
    ap.add_argument("--output", type=Path,
                    default=REPO_ROOT / "reports" / "dashboard.html")
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_page(args.skip_tests), encoding="utf-8")
    print(f"Dashboard written to {args.output}")


if __name__ == "__main__":
    main()
