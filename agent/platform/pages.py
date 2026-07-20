"""Static HTML/JS pages for the platform server (hub, /v1, /v2).

All pages are self-contained strings (no CDN, no build step) so the
server runs on the VM with stdlib only. The v2 pitch page renders an
SVG football field and plays back the squad event timeline served by
``/api/v2/...`` (see ``squad_events.py`` for the event schema).
"""
from __future__ import annotations

_BASE_CSS = """
:root { --bg:#0d1117; --panel:#161b22; --border:#30363d; --fg:#e6edf3;
  --dim:#8b949e; --accent:#58a6ff; --green:#3fb950; --red:#f85149;
  --amber:#d29922; --purple:#bc8cff; --pitch:#123a1e; --line:#2e7d46; }
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
  font:14.5px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
h1{font-size:22px;margin:0 0 2px}
.sub{color:var(--dim);margin-bottom:20px;font-size:13px}
.nav{display:flex;gap:14px;margin-bottom:18px;font-size:13px}
.nav a{padding:4px 12px;border:1px solid var(--border);border-radius:999px}
.nav a.here{background:var(--panel);border-color:var(--accent)}
.badge{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 9px;border-radius:999px}
.badge.alive{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.4)}
.badge.stale{background:rgba(210,153,34,.15);color:var(--amber);border:1px solid rgba(210,153,34,.4)}
.badge.down,.badge.halt{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.4)}
.badge.no-data{background:rgba(139,148,158,.15);color:var(--dim);border:1px solid var(--border)}
.badge.sim{background:rgba(188,140,255,.12);color:var(--purple);border:1px solid rgba(188,140,255,.4)}
.dim{color:var(--dim)} .ok{color:var(--green)} .bad{color:var(--red)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px 18px}
"""

_NAV = """<div class="nav">
<a href="/" class="{hub}">Hub</a>
<a href="/v1" class="{v1}">v1 · Zones agent (live demo)</a>
<a href="/v2" class="{v2}">v2 · Squad pitch (sim)</a>
</div>"""


def nav(active: str) -> str:
    return _NAV.format(hub="here" if active == "hub" else "",
                       v1="here" if active == "v1" else "",
                       v2="here" if active == "v2" else "")


# The hub is rewritten from a static two-tile page into a live overview:
# a KPI strip fed by the platform's own API endpoints, a plain-english
# "what am I looking at?" explainer, a glossary <details>, and a recent-
# activity feed off /api/v2/live/events. Uses the raw-template
# __PLACEHOLDER__ substitution (same trick as _V2_TEMPLATE) to avoid
# f-string brace doubling in the JS/CSS.
_HUB_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading platform</title><style>__BASE_CSS__
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}
@media (max-width: 700px){.kpis{grid-template-columns:1fr}}
.kpi{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.kpi h3{margin:0 0 10px;font-size:12.5px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--dim);display:flex;align-items:center;justify-content:space-between;gap:8px}
.kpi .row{display:flex;justify-content:space-between;font-size:13.5px;padding:3px 0;gap:8px;
  align-items:baseline}
.kpi .row .k{color:var(--dim)} .kpi .row .v{font-variant-numeric:tabular-nums}
.kpi .foot{font-size:11.5px;color:var(--dim);margin-top:8px;padding-top:6px;
  border-top:1px solid var(--border);word-break:break-all}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;margin-bottom:18px}
.tile{background:var(--panel);border:1px solid var(--border);border-radius:12px;
  padding:22px 24px;display:block;color:var(--fg)}
.tile:hover{border-color:var(--accent);text-decoration:none}
.tile h2{margin:0 0 6px;font-size:18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.tile p{margin:6px 0 0;color:var(--dim);font-size:13.5px;line-height:1.55}
.tile p code, .tile strong{color:var(--fg)}
.tile .summary{margin-top:10px;font-size:12.5px;color:var(--dim);
  font-variant-numeric:tabular-nums}
.explainer{margin-bottom:18px}
.explainer h3{margin:0 0 8px;font-size:15px}
.explainer p{margin:8px 0;font-size:13.5px;line-height:1.6;color:var(--fg)}
.explainer strong{color:var(--fg)}
.explainer em{color:var(--accent);font-style:normal;font-weight:600}
.explainer code{background:#0d1117;padding:1px 6px;border-radius:4px;font-size:12px;color:var(--dim)}
details.glossary{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  padding:12px 16px;margin-bottom:18px;font-size:13px}
details.glossary summary{cursor:pointer;font-weight:600;color:var(--fg);padding:2px 0;
  outline:none;user-select:none;list-style:revert}
details.glossary summary:hover{color:var(--accent)}
details.glossary dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;
  margin:12px 0 4px;font-size:12.5px}
details.glossary dt{font-weight:700;color:var(--accent);white-space:nowrap}
details.glossary dd{margin:0;color:var(--fg)}
.activity{margin-bottom:18px}
.activity h3{margin:0 0 10px;font-size:15px;display:flex;justify-content:space-between;
  align-items:baseline;gap:8px;flex-wrap:wrap}
.activity h3 .aux{font-size:11.5px;color:var(--dim);font-weight:400}
.activity .ev{display:grid;grid-template-columns:max-content 68px max-content 1fr;gap:10px;
  font-size:12.5px;padding:5px 0;border-bottom:1px solid #1c2129;align-items:baseline}
.activity .ev:last-child{border-bottom:none}
.activity .ev .t{color:var(--dim);font-variant-numeric:tabular-nums;white-space:nowrap;font-size:11.5px}
.activity .ev .s{color:var(--accent);font-weight:600}
.activity .empty{color:var(--dim);font-style:italic;font-size:12.5px;padding:4px 0}
.chip{font-size:10px;font-weight:700;text-transform:uppercase;padding:1px 7px;border-radius:999px;
  letter-spacing:.04em;white-space:nowrap;background:rgba(139,148,158,.15);color:var(--dim);
  border:1px solid var(--border)}
.chip.goal{background:rgba(63,185,80,.15);color:var(--green);border-color:rgba(63,185,80,.4)}
.chip.miss,.chip.blocked{background:rgba(248,81,73,.12);color:var(--red);border-color:rgba(248,81,73,.4)}
.chip.proposal{background:rgba(88,166,255,.12);color:var(--accent);border-color:rgba(88,166,255,.4)}
.chip.open{background:rgba(188,140,255,.12);color:var(--purple);border-color:rgba(188,140,255,.4)}
.footer{margin-top:24px;padding-top:12px;border-top:1px solid var(--border);
  font-size:11.5px;color:var(--dim);text-align:center;line-height:1.7}
.footer code{background:#0d1117;padding:1px 6px;border-radius:4px;font-size:11px;color:var(--fg)}
#updated{position:fixed;top:14px;right:20px;font-size:12px;color:var(--dim)}
</style></head><body>
<h1>Multi-pair trading platform</h1>
<div class="sub">Two AI agents on Exness demo MT5 &mdash; v1 trades real demo orders,
v2 shadow-simulates alongside for research. Auto-refreshes every 15&nbsp;s.</div>
__NAV__
<div id="updated">loading&hellip;</div>

<div class="kpis">
  <div class="kpi" id="kpi-v1">
    <h3><span>v1 &middot; Zones agent</span>
        <span class="badge no-data" id="kpi-v1-badge">&hellip;</span></h3>
    <div class="row"><span class="k">pairs tracked</span>
        <span class="v" id="kpi-v1-pairs">&mdash;</span></div>
    <div class="row"><span class="k">open positions</span>
        <span class="v" id="kpi-v1-open">&mdash;</span></div>
    <div class="row"><span class="k">day PnL</span>
        <span class="v" id="kpi-v1-pnl">&mdash;</span></div>
    <div class="foot" id="kpi-v1-foot">&mdash;</div>
  </div>
  <div class="kpi" id="kpi-v2">
    <h3><span>v2 &middot; Squad pitch</span>
        <span class="badge no-data" id="kpi-v2-badge">&hellip;</span></h3>
    <div class="row"><span class="k">source</span>
        <span class="v" id="kpi-v2-src">&mdash;</span></div>
    <div class="row"><span class="k">last event</span>
        <span class="v" id="kpi-v2-lastev">&mdash;</span></div>
    <div class="row"><span class="k">poll heartbeat</span>
        <span class="v" id="kpi-v2-poll">&mdash;</span></div>
    <div class="foot" id="kpi-v2-foot">&mdash;</div>
  </div>
  <div class="kpi" id="kpi-sys">
    <h3><span>System</span>
        <span class="badge no-data" id="kpi-sys-badge">&hellip;</span></h3>
    <div class="row"><span class="k">platform</span>
        <span class="v" id="kpi-sys-ver">&mdash;</span></div>
    <div class="row"><span class="k">uptime</span>
        <span class="v" id="kpi-sys-uptime">&mdash;</span></div>
    <div class="row"><span class="k">UTC now</span>
        <span class="v" id="kpi-sys-clock">&mdash;</span></div>
    <div class="foot" id="kpi-sys-foot">&mdash;</div>
  </div>
</div>

<div class="tiles">
  <a class="tile" href="/v1">
    <h2>v1 &mdash; Zones agent
        <span class="badge no-data" id="tile-v1-badge">&hellip;</span></h2>
    <p>The H4 supply/demand zones agent running on the VM
    (<code>main</code> branch code). Places real orders on the Exness
    demo MT5 account. This page shows open positions, day PnL, per-pair
    kill switches, and a live decision feed of every signal it evaluated,
    blocked, or traded. Auto-refreshes every 10&nbsp;s.</p>
    <div class="summary" id="tile-v1-summary">&hellip;</div>
  </a>
  <a class="tile" href="/v2">
    <h2>v2 &mdash; Blue Lock squad
        <span class="badge no-data" id="tile-v2-badge">&hellip;</span></h2>
    <p>The M001 multi-agent ensemble as a football match: 7 characters
    from Blue Lock, each with a distinct trading playstyle. Currently
    running in <strong>live shadow-paper</strong> mode &mdash; reading
    real MT5 bars alongside v1 but NOT placing orders. Proposals show as
    passes, aggregator rejections as tackles, Sentinel R7 news blocks as
    a wall, winning trades as goals. Historical walk-forward replays
    also available on this page.</p>
    <div class="summary" id="tile-v2-summary">&hellip;</div>
  </a>
</div>

<div class="card explainer">
  <h3>What am I looking at?</h3>
  <p><strong>Two agents, one demo account.</strong> This platform runs
  two AI trading agents against an Exness demo MetaTrader&nbsp;5 account
  (paper money &mdash; no real capital at risk). The <strong>v1 zones
  agent</strong> is the current production strategy and places real
  orders on the demo account. The <strong>v2 squad</strong> is the
  next-generation research line: an ensemble of 7 characters styled
  after the anime <em>Blue Lock</em>, each embodying a different
  trading playstyle.</p>
  <p><strong>Why two agents?</strong> Safety hierarchy. v1 has passed
  evaluation and earns the right to send real orders on demo. v2 runs
  in <strong>shadow mode</strong>: it reads the same live market bars,
  its 7 characters propose trades every 4 hours, but nothing is ever
  sent to the broker. We watch v2's shadow performance for weeks or
  months before considering promotion &mdash; the goal is to catch
  failure modes BEFORE they trade money.</p>
  <p><strong>How to read the /v2 page.</strong> The squad is rendered
  as a football match. Every H4 bar close, each active character
  <em>observes</em> the market and may <em>propose</em> a trade (a
  pass). Other characters can <em>tackle</em> (invalidate) the
  proposal. Surviving proposals hit the <em>Sentinel wall</em>
  (risk-management gates: news blackouts, drawdown limits, position
  caps). Ones that pass become <em>shots</em> (paper broker fills).
  Wins are <em>goals</em>, losses are <em>misses</em>. Even bars with
  no proposals show as a subtle grey <code>tick_summary</code> row so
  you can see the squad breathe.</p>
</div>

<details class="glossary">
<summary>Glossary &mdash; show/hide</summary>
<dl>
  <dt>H4 / D1</dt><dd>4-hour and daily candlestick timeframes.</dd>
  <dt>Zones agent</dt><dd>Identifies supply/demand price zones and
      trades pullbacks to them.</dd>
  <dt>Blue Lock squad</dt><dd>7 characters, each with a distinct
      playstyle (Isagi, Bachira, Rin, Chigiri, Reo, Nagi, Barou).</dd>
  <dt>Karasu</dt><dd>News defender. Reads the economic calendar and
      publishes advisories that block or scale down proposals near
      high-impact events.</dd>
  <dt>Sae</dt><dd>Event specialist. Trades big scheduled news releases
      (currently disabled by default).</dd>
  <dt>Shadow paper</dt><dd>Simulated fills against real market prices;
      no real orders sent.</dd>
  <dt>Sentinel</dt><dd>Risk-management gate. Blocks proposals violating
      drawdown / news / position rules.</dd>
  <dt>Workspace</dt><dd>Shared "thought stream" where characters
      publish observations for peers to see (Nagi's confluence fuel).</dd>
  <dt>Aggregator</dt><dd>Combines all character proposals into at most
      one shot per bar (Phi&nbsp;4.1 aggregator).</dd>
  <dt>TQS</dt><dd>Trade Quality Score. A per-proposal quality metric
      (0&ndash;1) used for post-hoc evaluation.</dd>
  <dt>Proposal / Pass</dt><dd>A character's suggested trade before any
      risk gate.</dd>
  <dt>Tackle</dt><dd>When another character or the aggregator rejects
      a proposal.</dd>
  <dt>Shot</dt><dd>A proposal that survived all gates and became a
      paper broker order.</dd>
  <dt>Goal / Miss</dt><dd>Shot that hit take-profit / stop-loss.</dd>
  <dt>tick_summary</dt><dd>One row per (bar &times; symbol) proving the
      squad evaluated even when no one proposed.</dd>
</dl>
</details>

<div class="card activity">
<h3>Recent activity <span class="aux">last 5 events from the v2 squad
    &middot; refreshes with the page</span></h3>
<div id="activity"><div class="empty">loading&hellip;</div></div>
</div>

<div class="footer" id="footer">&hellip;</div>

<script>
function esc(x){ const d=document.createElement("div"); d.innerText=String(x); return d.innerHTML; }

function humanAge(sec){
  if(sec==null || isNaN(sec)) return "\u2014";
  const s = Math.round(Number(sec));
  if(s < 5) return "just now";
  if(s < 90) return s + " s ago";
  const m = Math.round(s/60);
  if(m < 90) return m + " min ago";
  const h = Math.round(m/60);
  if(h < 48) return h + " h ago";
  return Math.round(h/24) + " d ago";
}
function humanUptime(sec){
  if(sec==null || isNaN(sec)) return "\u2014";
  const s = Math.round(Number(sec));
  if(s < 60) return s + " s";
  const m = Math.floor(s/60);
  if(m < 60) return m + " m";
  const h = Math.floor(m/60);
  const rm = m - h*60;
  if(h < 24) return h + " h " + rm + " m";
  const d = Math.floor(h/24);
  const rh = h - d*24;
  return d + " d " + rh + " h";
}
function ageFromIso(iso){
  if(!iso) return null;
  const t = new Date(String(iso).replace(" ","T"));
  if(isNaN(t)) return null;
  return (Date.now() - t.getTime())/1000;
}
function fmtMoney(n){
  if(n==null || isNaN(n)) return "\u2014";
  const v = Number(n);
  const sign = v>=0 ? "+$" : "-$";
  return sign + Math.abs(v).toFixed(2);
}

async function fetchJson(url){
  try{
    const r = await fetch(url);
    if(r.status === 401) return {__auth__: true};
    if(!r.ok) return {__error__: "HTTP " + r.status};
    return await r.json();
  } catch(e){ return {__error__: String(e && e.message || e)}; }
}

function worstV1Status(symbols){
  // Rank so alive < stale < no-data < down; the KPI badge should mirror
  // the WORST symbol status so a single dead pair is visible immediately.
  const rank = {"alive":0, "stale":1, "no-data":2, "down":3};
  let worst = null;
  for(const s of (symbols||[])){
    const st = s.status || "no-data";
    if(worst === null || (rank[st]||0) > (rank[worst]||0)) worst = st;
  }
  return worst || "no-data";
}
function v2Badge(v2){
  if(!v2) return {cls:"no-data", text:"no data"};
  if(v2.__auth__) return {cls:"stale", text:"auth required"};
  if(v2.__error__) return {cls:"down", text:"api error"};
  if(!v2.exists) return {cls:"no-data", text:"no live dir"};
  const src = v2.source || "";
  if(v2.running && src.indexOf("live_market:") === 0)
    return {cls:"alive", text:"live shadow paper"};
  if(v2.running && src === "cache_replay")
    return {cls:"sim", text:"cache replay"};
  if(v2.running) return {cls:"alive", text:"live"};
  return {cls:"stale", text:"idle"};
}
function setBadge(id, cls, text){
  const el = document.getElementById(id);
  if(!el) return;
  el.className = "badge " + cls;
  el.innerText = text;
}

function renderV1Kpi(v1){
  if(v1.__auth__){
    setBadge("kpi-v1-badge","stale","auth required");
    document.getElementById("kpi-v1-pairs").innerText="\u2014";
    document.getElementById("kpi-v1-open").innerText="\u2014";
    document.getElementById("kpi-v1-pnl").innerText="\u2014";
    document.getElementById("kpi-v1-foot").innerText=
      "pass ?token= in the URL to unlock live data";
    setBadge("tile-v1-badge","stale","auth required");
    document.getElementById("tile-v1-summary").innerText=
      "live data locked \u2014 pass ?token= in URL";
    return;
  }
  if(v1.__error__){
    setBadge("kpi-v1-badge","down","api error");
    document.getElementById("kpi-v1-foot").innerText=
      "/api/v1/status: " + v1.__error__;
    setBadge("tile-v1-badge","down","api error");
    document.getElementById("tile-v1-summary").innerText=
      "status fetch failed \u2014 " + v1.__error__;
    return;
  }
  const symbols = v1.symbols || [];
  if(!symbols.length){
    setBadge("kpi-v1-badge","no-data","no v1 logs yet");
    setBadge("tile-v1-badge","no-data","no v1 logs yet");
    document.getElementById("kpi-v1-pairs").innerText="0";
    document.getElementById("kpi-v1-open").innerText="0";
    document.getElementById("kpi-v1-pnl").innerText="\u2014";
    document.getElementById("kpi-v1-foot").innerText=
      "log root: " + (v1.log_root || "unknown");
    document.getElementById("tile-v1-summary").innerText=
      "no pairs yet \u2014 waiting on first heartbeat";
    return;
  }
  const status = worstV1Status(symbols);
  setBadge("kpi-v1-badge", status, status);
  setBadge("tile-v1-badge", status, status);
  let nOpen = 0, dayPnl = 0, hasPnl = false;
  let balance = null, bestAge = Infinity;
  for(const s of symbols){
    if((s.positions || []).length) nOpen++;
    const r = s.risk || {};
    if(r.day_pnl != null){ dayPnl += Number(r.day_pnl); hasPnl = true; }
    // Freshest symbol's day_open_balance is our best-effort account
    // balance surrogate (live_status doesn't expose an equity field).
    if(r.day_open_balance != null && s.age_seconds != null &&
       s.age_seconds < bestAge){
      balance = Number(r.day_open_balance); bestAge = s.age_seconds;
    }
  }
  document.getElementById("kpi-v1-pairs").innerText = symbols.length;
  document.getElementById("kpi-v1-open").innerText = nOpen;
  const pnlEl = document.getElementById("kpi-v1-pnl");
  if(hasPnl){
    pnlEl.innerText = fmtMoney(dayPnl);
    pnlEl.className = "v " + (dayPnl >= 0 ? "ok" : "bad");
  } else { pnlEl.innerText = "\u2014"; pnlEl.className = "v"; }
  document.getElementById("kpi-v1-foot").innerText =
    balance != null
      ? ("day-open balance $" + balance.toFixed(2))
      : "no balance recorded yet";
  document.getElementById("tile-v1-summary").innerText =
    symbols.length + " pair" + (symbols.length === 1 ? "" : "s") +
    " \u00b7 " + nOpen + " open \u00b7 day PnL " +
    (hasPnl ? fmtMoney(dayPnl) : "\u2014");
}

function renderV2Kpi(v2, evsTotal){
  const b = v2Badge(v2);
  setBadge("kpi-v2-badge", b.cls, b.text);
  setBadge("tile-v2-badge", b.cls, b.text);
  if(v2.__auth__ || v2.__error__){
    document.getElementById("kpi-v2-src").innerText = "\u2014";
    document.getElementById("kpi-v2-lastev").innerText = "\u2014";
    document.getElementById("kpi-v2-poll").innerText = "\u2014";
    document.getElementById("kpi-v2-foot").innerText =
      v2.__auth__
        ? "pass ?token= in the URL to unlock live data"
        : ("/api/v2/live/status: " + v2.__error__);
    document.getElementById("tile-v2-summary").innerText =
      v2.__auth__ ? "live data locked \u2014 pass ?token= in URL"
                  : "status fetch failed \u2014 " + v2.__error__;
    return;
  }
  document.getElementById("kpi-v2-src").innerText = v2.source || "idle";
  document.getElementById("kpi-v2-lastev").innerText =
    humanAge(ageFromIso(v2.last_event_time));
  const poll = v2.poll_heartbeat_age_seconds;
  document.getElementById("kpi-v2-poll").innerText =
    poll == null ? "\u2014" : (Math.round(Number(poll)) + " s ago");
  document.getElementById("kpi-v2-foot").innerText =
    v2.kill ? ("KILL: " + v2.kill)
            : (v2.dir ? ("dir: " + v2.dir) : "no dir");
  const totalTxt = (evsTotal == null)
    ? ""
    : (" \u00b7 " + evsTotal + " event" + (evsTotal === 1 ? "" : "s") + " total");
  document.getElementById("tile-v2-summary").innerText =
    "source: " + (v2.source || "idle") +
    " \u00b7 last event: " + humanAge(ageFromIso(v2.last_event_time)) +
    totalTxt;
}

function renderSysKpi(health, v1){
  if(!health || health.__error__){
    setBadge("kpi-sys-badge","down","api error");
    document.getElementById("kpi-sys-ver").innerText = "\u2014";
    document.getElementById("kpi-sys-uptime").innerText = "\u2014";
    document.getElementById("kpi-sys-foot").innerText =
      "/healthz: " + (health && health.__error__ ? health.__error__ : "unavailable");
    return;
  }
  const kill = (v1 && !v1.__auth__ && !v1.__error__) ? v1.global_kill : null;
  if(kill){
    setBadge("kpi-sys-badge","down","GLOBAL KILL");
  } else {
    setBadge("kpi-sys-badge","alive","no kill");
  }
  document.getElementById("kpi-sys-ver").innerText = "v" + (health.version || "?");
  document.getElementById("kpi-sys-uptime").innerText = humanUptime(health.uptime_seconds);
  document.getElementById("kpi-sys-foot").innerText =
    kill ? ("kill switch: " + kill) : ("status: " + (health.status || "?"));
}

function chipCls(ev){
  if(ev.type === "close") return ev.goal ? "goal" : "miss";
  if(ev.type === "blocked") return "blocked";
  if(ev.type === "proposal") return "proposal";
  if(ev.type === "open") return "open";
  return "";
}
function shortMsg(ev){
  if(ev.type === "proposal"){
    const dir = (ev.dir || "?").toString().toUpperCase();
    return "proposal " + dir +
      (ev.conviction != null ? (" (conv " + ev.conviction + ")") : "");
  }
  if(ev.type === "blocked") return ev.rule
    ? ("blocked by Sentinel \u2014 " + (ev.reason || "?"))
    : ("tackled by " + (ev.by || "?"));
  if(ev.type === "open") return "shot " + (ev.dir || "?").toString().toUpperCase();
  if(ev.type === "close") return ev.goal
    ? ("GOAL +" + ev.pnl_pips + " pips (" + (ev.exit_reason || "tp") + ")")
    : ("miss " + ev.pnl_pips + " pips (" + (ev.exit_reason || "sl") + ")");
  if(ev.type === "thought") return "thought: " + String(ev.text || "").slice(0, 80);
  if(ev.type === "tick_summary"){
    const n = (ev.players_evaluated || []).length;
    const p = ev.proposal_count || 0;
    return "tick \u2014 " + n + " evaluated, " + p +
      " proposal" + (p === 1 ? "" : "s");
  }
  return ev.type;
}
function renderActivity(evsResp){
  const el = document.getElementById("activity");
  if(evsResp.__auth__){
    el.innerHTML =
      '<div class="empty">auth required \u2014 pass ?token= in URL to see events</div>';
    return;
  }
  // 404 = live dir not created yet; treat as "no events" not an error.
  if(evsResp.__error__ && evsResp.__error__ !== "HTTP 404"){
    el.innerHTML =
      '<div class="empty">events endpoint error: ' +
      esc(evsResp.__error__) + '</div>';
    return;
  }
  const events = (evsResp && evsResp.events) || [];
  if(!events.length){
    el.innerHTML =
      '<div class="empty">no v2 events yet \u2014 waiting on first H4 bar close</div>';
    return;
  }
  el.innerHTML = events.slice(-5).reverse().map(ev =>
    '<div class="ev">' +
      '<span class="t">' + esc(String(ev.t || "").slice(0, 16)) + '</span>' +
      '<span class="s">' + esc(ev.symbol || "\u2014") + '</span>' +
      '<span class="chip ' + chipCls(ev) + '">' + esc(ev.type) + '</span>' +
      '<span>' + esc(shortMsg(ev)) + '</span>' +
    '</div>').join("");
}

function renderFooter(health, v1){
  const ver = (health && !health.__error__) ? (health.version || "?") : "?";
  const logRoot = (v1 && !v1.__auth__ && !v1.__error__ && v1.log_root)
    ? v1.log_root : "(unknown)";
  document.getElementById("footer").innerHTML =
    "Platform v" + esc(ver) +
    " \u00b7 deployed on Exness VM (Windows 11 ARM)" +
    " \u00b7 logs in <code>" + esc(logRoot) + "</code>" +
    " \u00b7 code on <code>next-gen</code> branch";
}

async function refreshAll(){
  const [v1, v2, evs, health] = await Promise.all([
    fetchJson("/api/v1/status"),
    fetchJson("/api/v2/live/status"),
    fetchJson("/api/v2/live/events?cursor=0&limit=5"),
    fetchJson("/healthz"),
  ]);
  const evsTotal = (evs && !evs.__auth__ && !evs.__error__)
    ? (evs.total != null ? evs.total : (evs.events || []).length) : null;
  renderV1Kpi(v1);
  renderV2Kpi(v2, evsTotal);
  renderSysKpi(health, v1);
  renderActivity(evs);
  renderFooter(health, v1);
  document.getElementById("updated").innerText =
    "updated " + new Date().toLocaleTimeString();
}

function tickClock(){
  const el = document.getElementById("kpi-sys-clock");
  if(!el) return;
  const now = new Date();
  el.innerText = now.toISOString().slice(11, 19) + " UTC";
}

refreshAll();
setInterval(refreshAll, 15000);
tickClock();
setInterval(tickClock, 1000);
</script>
</body></html>"""

HUB_PAGE = (_HUB_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__NAV__", nav('hub')))


V1_PAGE = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zones agent — live (v1)</title>
<style>{_BASE_CSS}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;margin-bottom:20px}}
.card h2{{margin:0 0 10px;font-size:17px;display:flex;align-items:center;gap:10px}}
.kv{{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;font-size:13px;margin:8px 0}}
.kv dt{{color:var(--dim)}} .kv dd{{margin:0}}
.pos{{border:1px solid var(--border);border-radius:8px;padding:8px 12px;margin:8px 0;font-size:13px}}
.pos .dir-long{{color:var(--green);font-weight:700}} .pos .dir-short{{color:var(--red);font-weight:700}}
.flat{{color:var(--dim);font-size:13px;font-style:italic}}
.feed{{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px 18px}}
.feed h2{{margin:0 0 10px;font-size:17px}}
.ev{{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid #1c2129;font-size:12.8px;align-items:baseline}}
.ev:last-child{{border-bottom:none}}
.ev .t{{color:var(--dim);white-space:nowrap;font-variant-numeric:tabular-nums}}
.ev .s{{color:var(--accent);font-weight:600;white-space:nowrap}}
.chip{{font-size:10px;font-weight:700;text-transform:uppercase;padding:1px 7px;border-radius:999px;white-space:nowrap}}
.chip.trade{{background:rgba(63,185,80,.15);color:var(--green)}}
.chip.block{{background:rgba(248,81,73,.12);color:var(--red)}}
.chip.signal{{background:rgba(88,166,255,.12);color:var(--accent)}}
.chip.ladder{{background:rgba(188,140,255,.12);color:var(--purple)}}
.chip.halt{{background:rgba(248,81,73,.25);color:var(--red)}}
.chip.heartbeat{{background:rgba(139,148,158,.12);color:var(--dim)}}
.chip.info{{background:rgba(139,148,158,.12);color:var(--dim)}}
.warnbar{{border-left:4px solid var(--red);background:rgba(248,81,73,.08);
  padding:10px 14px;border-radius:6px;margin-bottom:16px;font-size:14px}}
#updated{{position:fixed;top:14px;right:20px;font-size:12px;color:var(--dim)}}
</style></head><body>
<h1>Zones agent — live dashboard <span class="dim">v1 · zone_d1_against · demo MT5</span></h1>
<div class="sub">Read-only view over the agent's own logs + state sidecars. Auto-refreshes every 10 s.</div>
{nav('v1')}
<div id="updated"></div>
<div id="killbar"></div>
<div class="cards" id="cards"></div>
<div class="feed"><h2>Decision feed <span class="dim" style="font-size:12px">— what the agent evaluated, blocked, and traded (newest first)</span></h2>
<div id="feed"></div></div>
<script>
function fmtAge(s){{ if(s==null) return "n/a";
  if(s<90) return Math.round(s)+"s ago";
  if(s<5400) return Math.round(s/60)+"m ago";
  return (s/3600).toFixed(1)+"h ago"; }}
function esc(x){{ const d=document.createElement("div"); d.innerText=String(x); return d.innerHTML; }}
function posHtml(p){{
  const dir=(p.direction||"?").toLowerCase();
  const bits=[];
  for(const k of ["entry","sl","soft_stop","tp","lots","lot_size","timeframe","alpha"]){{
    if(p[k]!=null) bits.push(k+"="+p[k]); }}
  let exc="";
  if(p.excursion) exc='<div class="dim">excursion: '+esc(JSON.stringify(p.excursion))+'</div>';
  return '<div class="pos"><span class="dir-'+dir+'">'+dir.toUpperCase()+
    '</span> ticket '+esc(p.ticket)+' — '+esc(bits.join("  "))+exc+'</div>'; }}
async function refresh(){{
  let data;
  try{{ data = await (await fetch("/api/v1/status")).json(); }}
  catch(e){{ document.getElementById("updated").innerText="fetch failed: "+e; return; }}
  document.getElementById("updated").innerText =
    "updated "+new Date().toLocaleTimeString();
  document.getElementById("killbar").innerHTML = data.global_kill ?
    '<div class="warnbar"><b>GLOBAL KILL SWITCH ACTIVE:</b> '+esc(data.global_kill)+'</div>' : "";
  const cards=[];
  const feed=[];
  for(const s of data.symbols){{
    let inner='<h2>'+esc(s.symbol)+' <span class="badge '+s.status+'">'+s.status+
      '</span> <span class="dim" style="font-size:12px">'+fmtAge(s.age_seconds)+'</span></h2>';
    if(s.kill_file) inner+='<div class="warnbar">kill.txt: '+esc(s.kill_file)+'</div>';
    if(s.positions.length) inner+=s.positions.map(posHtml).join("");
    else inner+='<div class="flat">flat — no open position</div>';
    inner+='<dl class="kv">';
    const r=s.risk, g=s.guard;
    if(r.day_pnl!=null) inner+='<dt>Day PnL</dt><dd class="'+(r.day_pnl>=0?"ok":"bad")+'">'+
      Number(r.day_pnl).toFixed(2)+'</dd>';
    if(r.halted_today) inner+='<dt>Daily-DD halt</dt><dd class="bad">HALTED TODAY</dd>';
    if(g.session_halted) inner+='<dt>Post-loss guard</dt><dd class="bad">session halted — '+
      esc(g.halt_reason||"")+'</dd>';
    else if(g.consecutive_losses) inner+='<dt>Loss streak</dt><dd>'+g.consecutive_losses+
      ' (size ×'+(g.size_multiplier??1)+')</dd>';
    if(g.cooldown_until) inner+='<dt>Cooldown until</dt><dd>'+esc(g.cooldown_until)+'</dd>';
    if(s.state_saved_at) inner+='<dt>State saved</dt><dd class="dim">'+esc(s.state_saved_at)+'</dd>';
    inner+='</dl>';
    cards.push('<div class="card">'+inner+'</div>');
    for(const ev of s.feed) feed.push(ev);
  }}
  document.getElementById("cards").innerHTML =
    cards.join("") || '<div class="card"><div class="flat">No symbol directories found under '+
    esc(data.log_root)+'</div></div>';
  feed.sort((a,b)=> (a.ts<b.ts?1:-1));
  document.getElementById("feed").innerHTML = feed.slice(0,120).map(ev=>
    '<div class="ev"><span class="t">'+esc(ev.ts)+'</span><span class="s">'+esc(ev.symbol)+
    '</span><span class="chip '+ev.cat+'">'+ev.cat+'</span><span>'+esc(ev.msg)+'</span></div>'
  ).join("") || '<div class="flat">No recent events in the daily logs.</div>';
}}
refresh(); setInterval(refresh, 10000);
</script></body></html>"""


# The v2 page's JS is large; a raw template with __PLACEHOLDER__
# substitution avoids both the brace-doubling tax of an f-string and
# Python eating JS unicode escapes like \u{1F4AD}.
_V2_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue Lock squad — pitch (v2)</title>
<style>__BASE_CSS__
.layout{display:grid;grid-template-columns:minmax(420px,1.4fr) minmax(320px,1fr);gap:16px}
@media (max-width: 900px){ .layout{grid-template-columns:1fr} }
#pitchwrap{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px}
#pitch{width:100%;height:auto;display:block;border-radius:8px}
.controls{display:flex;gap:10px;align-items:center;margin:10px 0 4px;flex-wrap:wrap}
.controls button{background:#21262d;color:var(--fg);border:1px solid var(--border);
  border-radius:8px;padding:6px 16px;font-size:13px;cursor:pointer}
.controls button:hover{border-color:var(--accent)}
.controls select,.controls input{background:#21262d;color:var(--fg);border:1px solid var(--border);
  border-radius:8px;padding:5px 10px;font-size:13px}
.controls label{font-size:12px;color:var(--dim);display:flex;gap:5px;align-items:center}
#clock{font-variant-numeric:tabular-nums;font-weight:700;font-size:15px}
#score{font-size:15px} #score b{color:var(--green)}
#seek{width:100%;margin:6px 0 2px;accent-color:var(--accent)}
.side .card{margin-bottom:14px}
.tkr{max-height:340px;overflow-y:auto}
.tk{display:flex;gap:8px;padding:3px 0;border-bottom:1px solid #1c2129;font-size:12.3px;
  align-items:baseline;cursor:pointer}
.tk:hover{background:rgba(88,166,255,.06)}
.tk:last-child{border-bottom:none}
.tk .t{color:var(--dim);white-space:nowrap;font-variant-numeric:tabular-nums;font-size:11px}
.tk .who{font-weight:700;white-space:nowrap}
/* Silent-tick summary rows: muted visual weight so they don't dominate
 * the ticker on quiet bars but still confirm the squad is evaluating.
 * Filter checkbox in the controls hides them for a noise-free view. */
.tk.tick-summary{color:var(--dim);font-size:11.5px;opacity:.72;
  cursor:default;font-style:italic}
.tk.tick-summary:hover{background:transparent}
.tk.tick-summary .who{font-weight:500;color:var(--dim)}
.tk.hidden{display:none}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--border)}
th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:none}
.gflash{position:fixed;left:50%;top:38%;transform:translate(-50%,-50%);
  font-size:54px;font-weight:900;color:var(--green);text-shadow:0 0 30px rgba(63,185,80,.8);
  opacity:0;pointer-events:none;transition:opacity .2s;z-index:50;letter-spacing:.1em}
#overlay{position:fixed;inset:0;background:rgba(1,4,9,.72);display:none;z-index:80;
  align-items:flex-start;justify-content:center;padding:60px 16px 16px;overflow-y:auto}
#overlay.open{display:flex}
#modal{background:var(--panel);border:1px solid var(--border);border-radius:12px;
  max-width:640px;width:100%;padding:20px 24px;position:relative}
#modal h2{margin:0 0 8px;font-size:17px}
#modal .x{position:absolute;top:10px;right:14px;background:none;border:none;color:var(--dim);
  font-size:20px;cursor:pointer}
#modal .x:hover{color:var(--fg)}
.kv2{display:grid;grid-template-columns:max-content 1fr;gap:3px 16px;font-size:13px;margin:10px 0}
.kv2 dt{color:var(--dim)} .kv2 dd{margin:0;word-break:break-word}
#modal pre{background:#0d1117;border:1px solid var(--border);border-radius:8px;padding:10px 12px;
  font-size:11.5px;overflow-x:auto;max-height:260px}
.spark{display:block;margin:8px 0}
.rt{font-size:12.3px}
.badge.live{background:rgba(248,81,73,.18);color:var(--red);border:1px solid rgba(248,81,73,.5)}
</style></head><body>
<h1>Blue Lock squad — the pitch <span class="dim">v2 · M001 ensemble</span>
 <span class="badge sim" id="modebadge">sim-only — not trading real lots</span></h1>
<div class="sub">Walk-forward replay played as a match: passes are proposals, tackles are
aggregator rejections, the wall is Sentinel, goals are winning trades. Click a player for
their profile; click a ticker row for the full event payload.</div>
__NAV__
<div class="layout">
<div id="pitchwrap">
  <div class="controls">
    <select id="match"></select>
    <button id="play">&#9654; Play</button>
    <select id="speed">
      <option value="2">2 ev/s</option><option value="8" selected>8 ev/s</option>
      <option value="30">30 ev/s</option><option value="120">120 ev/s</option>
    </select>
    <span id="clock">—</span>
    <span id="score">Goals <b id="goals">0</b> · Misses <span id="misses">0</span></span>
  </div>
  <input type="range" id="seek" min="0" max="0" value="0">
  <div class="controls" style="margin-top:2px">
    <select id="fagent"><option value="">all players</option></select>
    <select id="fsymbol"><option value="">all symbols</option></select>
    <select id="ftype"><option value="">all events</option>
      <option value="proposal">proposals</option><option value="blocked">blocked</option>
      <option value="open">opens</option><option value="close">closes</option>
      <option value="thought">thoughts</option>
      <option value="tick_summary">tick summaries</option></select>
    <input id="jumpdate" placeholder="jump to YYYY-MM-DD" size="18">
    <button id="jumpbtn">Go</button>
    <label><input type="checkbox" id="pausegoal"> pause on goal</label>
    <label><input type="checkbox" id="hidesilent"> hide silent ticks</label>
  </div>
  <svg id="pitch" viewBox="0 0 100 130" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="side">
  <div class="card"><h2 style="margin:0 0 8px;font-size:15px">Match ticker <span class="dim" style="font-size:11px">click a row for detail</span></h2><div class="tkr" id="ticker"></div></div>
  <div class="card"><h2 style="margin:0 0 8px;font-size:15px">League table (this match)</h2>
    <table id="league"><tr><th>Player</th><th>Props</th><th>Blocked</th><th>Trades</th><th>Goals</th><th>Win%</th><th>Pips</th><th>TQS</th></tr></table></div>
</div>
</div>
<div class="gflash" id="gflash">GOAL!</div>
<div id="overlay"><div id="modal"><button class="x" id="mclose">&times;</button><div id="mbody"></div></div></div>
<script>
const NS="http://www.w3.org/2000/svg";
let roster={}, events=[], filtered=[], pos=0, playing=false, timer=null, goals=0, misses=0;
let matchId=null, summaryData=null, liveTimer=null, livePolling=false;
function esc(x){ const d=document.createElement("div"); d.innerText=String(x); return d.innerHTML; }
function el(tag,attrs){ const e=document.createElementNS(NS,tag);
  for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }
function evDate(t){ return new Date((t||"").replace(" ","T")); }

function drawPitch(){
  const svg=document.getElementById("pitch"); svg.innerHTML="";
  svg.appendChild(el("rect",{x:0,y:0,width:100,height:130,fill:"var(--pitch)",rx:2}));
  const line={stroke:"var(--line)","stroke-width":0.5,fill:"none"};
  svg.appendChild(el("rect",{x:3,y:3,width:94,height:124,...line}));
  svg.appendChild(el("line",{x1:3,y1:65,x2:97,y2:65,...line}));
  svg.appendChild(el("circle",{cx:50,cy:65,r:10,...line}));
  svg.appendChild(el("rect",{x:30,y:3,width:40,height:14,...line}));   // opponent box (top)
  svg.appendChild(el("rect",{x:30,y:113,width:40,height:14,...line})); // own box
  svg.appendChild(el("rect",{x:40,y:1,width:20,height:2,fill:"#e6edf3",opacity:.85})); // goal
  const g=el("g",{id:"anim"}); svg.appendChild(g);
  const bub=el("g",{id:"bubbles"}); svg.appendChild(bub);
  for(const [aid,r] of Object.entries(roster)){
    const px=r.x, py=130-(r.y*1.2)-5;   // roster y grows toward goal; goal is at top
    const pg=el("g",{id:"pl_"+aid,transform:`translate(${px},${py})`,style:"cursor:pointer"});
    pg.appendChild(el("circle",{r:3.4,fill:r.color,stroke:"#0d1117","stroke-width":0.5}));
    const num=el("text",{y:1.2,"text-anchor":"middle","font-size":3,fill:"#0d1117","font-weight":"800"});
    num.textContent=r.num; pg.appendChild(num);
    const nm=el("text",{y:6.6,"text-anchor":"middle","font-size":2.6,fill:"#e6edf3"});
    nm.textContent=r.name; pg.appendChild(nm);
    const halo=el("circle",{r:3.4,fill:"none",stroke:r.color,"stroke-width":0,id:"halo_"+aid});
    pg.appendChild(halo);
    pg.addEventListener("click",()=>showProfile(aid));
    svg.appendChild(pg);
  }
}
function playerPos(aid){ const r=roster[aid];
  return r? [r.x, 130-(r.y*1.2)-5] : [50,65]; }
function pulse(aid,color){
  const h=document.getElementById("halo_"+aid); if(!h) return;
  h.setAttribute("stroke",color); h.setAttribute("stroke-width",1.4); h.setAttribute("r",3.4);
  let r=3.4; const iv=setInterval(()=>{ r+=0.9; h.setAttribute("r",r);
    h.setAttribute("stroke-width",Math.max(0,1.4-(r-3.4)*0.18));
    if(r>10){clearInterval(iv); h.setAttribute("stroke-width",0);} },30);
}
function ball(from,to,color,dashed){
  const g=document.querySelector("#anim");
  const ln=el("line",{x1:from[0],y1:from[1],x2:from[0],y2:from[1],stroke:color,
    "stroke-width":0.7,opacity:0.9,...(dashed?{"stroke-dasharray":"1.5 1.2"}:{})});
  g.appendChild(ln);
  const b=el("circle",{cx:from[0],cy:from[1],r:1.2,fill:"#fff",stroke:color,"stroke-width":0.5});
  g.appendChild(b);
  const steps=14; let i=0;
  const iv=setInterval(()=>{ i++;
    const x=from[0]+(to[0]-from[0])*i/steps, y=from[1]+(to[1]-from[1])*i/steps;
    b.setAttribute("cx",x); b.setAttribute("cy",y);
    ln.setAttribute("x2",x); ln.setAttribute("y2",y);
    if(i>=steps){ clearInterval(iv);
      setTimeout(()=>{b.remove(); ln.style.transition="opacity .6s"; ln.style.opacity=0;
        setTimeout(()=>ln.remove(),700);},150); } },22);
}
function speechBubble(aid,text){
  const g=document.getElementById("bubbles"); if(!g) return;
  const [px,py]=playerPos(aid);
  const short=String(text).slice(0,42)+(String(text).length>42?"…":"");
  const w=Math.min(46,short.length*1.55+4);
  const bx=Math.max(4,Math.min(96-w,px-w/2)), by=Math.max(4,py-13);
  const grp=el("g",{opacity:"0.96"});
  grp.appendChild(el("rect",{x:bx,y:by,width:w,height:6.4,rx:2,fill:"#e6edf3",
    stroke:"#8b949e","stroke-width":0.2}));
  const tx=el("text",{x:bx+w/2,y:by+4.2,"text-anchor":"middle","font-size":2.4,
    fill:"#0d1117","font-style":"italic"});
  tx.textContent=short; grp.appendChild(tx);
  g.appendChild(grp);
  setTimeout(()=>{grp.style.transition="opacity .8s"; grp.style.opacity=0;
    setTimeout(()=>grp.remove(),900);},2200);
}
function goalFlash(){ const f=document.getElementById("gflash");
  f.style.opacity=1; setTimeout(()=>f.style.opacity=0,900); }

function tickMsg(ev){
  if(ev.type==="proposal") return `proposes ${(ev.dir||"?").toUpperCase()} ${ev.symbol} (conv ${ev.conviction})`;
  if(ev.type==="blocked") return ev.rule?`blocked by SENTINEL — ${ev.reason}`:
    `tackled by ${(roster[ev.by]||{name:ev.by}).name} on ${ev.symbol}`;
  if(ev.type==="open") return `SHOT — ${(ev.dir||"?").toUpperCase()} ${ev.symbol} executed`;
  if(ev.type==="close") return ev.goal?
    `GOAL! +${ev.pnl_pips} pips on ${ev.symbol} (${ev.exit_reason}${ev.tqs!=null?", TQS "+ev.tqs:""})`:
    `miss — ${ev.pnl_pips} pips on ${ev.symbol} (${ev.exit_reason})`;
  if(ev.type==="thought") return `\u{1F4AD} ${ev.text||""}`;
  if(ev.type==="tick_summary"){
    const nEv=(ev.players_evaluated||[]).length;
    const nPr=(ev.players_who_proposed||[]).length;
    const wc=ev.workspace_thought_count??0;
    const propTxt = ev.proposal_count===0
      ? "0 proposals"
      : `${ev.proposal_count} proposal${ev.proposal_count===1?"":"s"} (${nPr} proposer${nPr===1?"":"s"})`;
    return `\u22EF ${ev.symbol||"?"} @ ${(ev.t||"").slice(0,16)} — ${nEv} players evaluated, ${propTxt}, workspace: ${wc} thought${wc===1?"":"s"}`;
  }
  return JSON.stringify(ev);
}
function tick(ev){
  const tk=document.getElementById("ticker");
  if(ev.type==="tick_summary"){
    // Silent-tick row: muted styling, no roster lookup (no per-agent
    // attribution), respects the hidesilent checkbox.
    const div=document.createElement("div");
    div.className="tk tick-summary";
    if(document.getElementById("hidesilent") &&
       document.getElementById("hidesilent").checked) div.classList.add("hidden");
    div.innerHTML=`<span class="t">${esc((ev.t||"").slice(0,16))}</span>`+
      `<span class="who">tick</span><span>${esc(tickMsg(ev))}</span>`;
    tk.prepend(div);
    while(tk.children.length>80) tk.lastChild.remove();
    return;
  }
  const r=roster[ev.agent]||{name:ev.agent,color:"#8b949e"};
  const div=document.createElement("div"); div.className="tk";
  div.innerHTML=`<span class="t">${esc((ev.t||"").slice(0,16))}</span>`+
    `<span class="who" style="color:${r.color}">${esc(r.name)}</span><span>${esc(tickMsg(ev))}</span>`;
  div.addEventListener("click",()=>showEventDetail(ev.gi));
  tk.prepend(div);
  while(tk.children.length>80) tk.lastChild.remove();
}

function animate(ev){
  // tick_summary events are proof-of-life footers, not real match
  // events — no pitch animation, no score change. The ticker row is
  // the entire UI affordance.
  if(ev.type==="tick_summary") return;
  const p=playerPos(ev.agent);
  if(ev.type==="proposal"){ pulse(ev.agent,"#58a6ff"); ball(p,[50,30],"#58a6ff",true); }
  else if(ev.type==="blocked"){
    const q=ev.rule? [50,110] : playerPos(ev.by);
    pulse(ev.agent,"#f85149"); ball(p,q,"#f85149",true);
    if(!ev.rule) pulse(ev.by,"#d29922");
  }
  else if(ev.type==="open"){ pulse(ev.agent,"#3fb950"); ball(p,[50,8],"#3fb950",false); }
  else if(ev.type==="thought"){ speechBubble(ev.agent, ev.text||""); }
  else if(ev.type==="close"){
    if(ev.goal){ goals++; pulse(ev.agent,"#3fb950"); ball([50,8],[50,2],"#3fb950",false); goalFlash(); }
    else { misses++; pulse(ev.agent,"#8b949e"); }
    renderScore();
  }
}
function renderScore(){
  document.getElementById("goals").innerText=goals;
  document.getElementById("misses").innerText=misses;
}
function renderClock(ev){
  document.getElementById("clock").innerText=
    (ev? (ev.t||"").slice(0,16) : "—")+`  ·  ${pos}/${filtered.length}`;
  document.getElementById("seek").value=pos;
}

function step(){
  if(pos>=filtered.length){ setPlaying(false); return; }
  const ev=events[filtered[pos]]; pos++;
  renderClock(ev); animate(ev); tick(ev);
  if(ev.type==="close" && ev.goal && document.getElementById("pausegoal").checked)
    setPlaying(false);
}
function setPlaying(on){
  playing=on;
  document.getElementById("play").innerHTML=on?"&#10074;&#10074; Pause":"&#9654; Play";
  if(timer){clearInterval(timer); timer=null;}
  if(on){ const evps=Number(document.getElementById("speed").value);
    timer=setInterval(step, 1000/evps); }
}

function seek(p){
  pos=Math.max(0,Math.min(p,filtered.length));
  goals=0; misses=0;
  for(let i=0;i<pos;i++){ const ev=events[filtered[i]];
    if(ev.type==="close"){ if(ev.goal) goals++; else misses++; } }
  renderScore();
  const tk=document.getElementById("ticker"); tk.innerHTML="";
  for(let i=Math.max(0,pos-40);i<pos;i++) tick(events[filtered[i]]);
  renderClock(pos>0? events[filtered[pos-1]] : null);
}
function applyFilters(){
  const fa=document.getElementById("fagent").value;
  const fs=document.getElementById("fsymbol").value;
  const ft=document.getElementById("ftype").value;
  filtered=[];
  for(let i=0;i<events.length;i++){ const e=events[i];
    if(fa && e.agent!==fa && e.by!==fa) continue;
    if(fs && e.symbol!==fs) continue;
    if(ft && e.type!==ft) continue;
    filtered.push(i);
  }
  document.getElementById("seek").max=filtered.length;
  seek(0);
}
function jumpToDate(){
  const raw=document.getElementById("jumpdate").value.trim();
  if(!raw) return;
  const target=new Date(raw.length<=10? raw+"T00:00:00Z" : raw.replace(" ","T"));
  if(isNaN(target)) return;
  let lo=filtered.length;
  for(let i=0;i<filtered.length;i++){
    if(evDate(events[filtered[i]].t)>=target){ lo=i; break; } }
  seek(lo);
}

function fmtVal(v){
  if(v==null) return "—";
  if(typeof v==="number") return String(Math.round(v*10000)/10000);
  return String(v);
}
function openModal(html){
  document.getElementById("mbody").innerHTML=html;
  document.getElementById("overlay").classList.add("open");
}
function closeModal(){ document.getElementById("overlay").classList.remove("open"); }

async function showEventDetail(gi){
  if(gi==null || matchId==null) return;
  let ev;
  try{ ev=await (await fetch(`/api/v2/${matchId==="__live__"?"live":"match/"+matchId}/event/${gi}`)).json(); }
  catch(e){ return; }
  if(ev.error) return;
  const r=roster[ev.agent]||{name:ev.agent,color:"#8b949e"};
  let rows="";
  const base={type:ev.type, time:ev.t, symbol:ev.symbol, direction:ev.dir,
    conviction:ev.conviction, blocked_by:ev.by, reason:ev.reason,
    pnl_pips:ev.pnl_pips, exit_reason:ev.exit_reason, tqs:ev.tqs, text:ev.text};
  for(const [k,v] of Object.entries(base)) if(v!=null)
    rows+=`<dt>${esc(k)}</dt><dd>${esc(fmtVal(v))}</dd>`;
  if(ev.detail) for(const [k,v] of Object.entries(ev.detail)){
    if(v==null) continue;
    if(typeof v==="object")
      rows+=`<dt>${esc(k)}</dt><dd><pre style="margin:0">${esc(JSON.stringify(v,null,1))}</pre></dd>`;
    else rows+=`<dt>${esc(k)}</dt><dd>${esc(fmtVal(v))}</dd>`;
  }
  openModal(`<h2><span style="color:${r.color}">${esc(r.name)}</span> — ${esc(ev.type)} event</h2>`+
    `<dl class="kv2">${rows}</dl>`+
    `<details><summary class="dim" style="cursor:pointer;font-size:12px">raw JSON</summary>`+
    `<pre>${esc(JSON.stringify(ev,null,2))}</pre></details>`);
}

function sparkline(vals,w,h){
  if(vals.length<2) return `<div class="dim" style="font-size:12px">not enough closed trades for a sparkline</div>`;
  const min=Math.min(0,...vals), max=Math.max(0,...vals), span=(max-min)||1;
  const pts=vals.map((v,i)=>`${(i/(vals.length-1))*w},${h-((v-min)/span)*h}`).join(" ");
  const zy=h-((0-min)/span)*h;
  const last=vals[vals.length-1];
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`+
    `<line x1="0" y1="${zy}" x2="${w}" y2="${zy}" stroke="#30363d" stroke-width="1"/>`+
    `<polyline points="${pts}" fill="none" stroke="${last>=0?"#3fb950":"#f85149"}" stroke-width="1.5"/></svg>`;
}
function showProfile(aid){
  const r=roster[aid]||{name:aid,color:"#8b949e",role:"?",num:"?"};
  const d=(summaryData&&summaryData.per_agent&&summaryData.per_agent[aid])||
    {proposals:0,blocked:0,trades:0,goals:0,pips:0,mean_tqs:null,win_rate:null};
  const closes=events.filter(e=>e.type==="close"&&e.agent===aid);
  let cum=0; const series=closes.map(e=>{cum+=e.pnl_pips; return Math.round(cum*10)/10;});
  const recent=closes.slice(-8).reverse().map(e=>
    `<div class="tk rt" onclick="showEventDetail(${e.gi})"><span class="t">${esc((e.t||"").slice(0,16))}</span>`+
    `<span>${esc(e.symbol)}</span><span class="${e.goal?"ok":"bad"}">${e.pnl_pips>0?"+":""}${e.pnl_pips} pips</span>`+
    `<span class="dim">${esc(e.exit_reason||"")}</span></div>`).join("")||
    `<div class="dim" style="font-size:12px">no closed trades in this match</div>`;
  openModal(`<h2><span style="color:${r.color}">#${r.num} ${esc(r.name)}</span>`+
    ` <span class="dim" style="font-size:13px">${esc(r.role||"")}</span></h2>`+
    `<dl class="kv2"><dt>Proposals</dt><dd>${d.proposals}</dd>`+
    `<dt>Blocked</dt><dd>${d.blocked}</dd><dt>Trades</dt><dd>${d.trades}</dd>`+
    `<dt>Goals</dt><dd>${d.goals}</dd>`+
    `<dt>Win rate</dt><dd>${d.win_rate!=null? (d.win_rate*100).toFixed(0)+"%":"—"}</dd>`+
    `<dt>Pips</dt><dd class="${d.pips>=0?"ok":"bad"}">${d.pips}</dd>`+
    `<dt>Mean TQS</dt><dd>${d.mean_tqs??"—"}</dd></dl>`+
    `<div class="dim" style="font-size:12px">cumulative pips over the match</div>`+
    sparkline(series,280,54)+
    `<div class="dim" style="font-size:12px;margin-top:8px">recent trades</div>${recent}`);
}

function renderLeague(summary){
  const tbl=document.getElementById("league");
  tbl.querySelectorAll("tr:not(:first-child)").forEach(r=>r.remove());
  const rows=Object.entries(summary.per_agent||{})
    .sort((a,b)=>b[1].pips-a[1].pips);
  for(const [aid,d] of rows){
    const r=roster[aid]||{name:aid,color:"#8b949e"};
    const tr=document.createElement("tr");
    tr.innerHTML=`<td style="color:${r.color};font-weight:700">${esc(r.name)}</td>`+
      `<td>${d.proposals}</td><td>${d.blocked}</td><td>${d.trades}</td>`+
      `<td>${d.goals}</td><td>${d.win_rate!=null?(d.win_rate*100).toFixed(0)+"%":"—"}</td>`+
      `<td class="${d.pips>=0?'ok':'bad'}">${d.pips}</td>`+
      `<td>${d.mean_tqs??"—"}</td>`;
    tr.style.cursor="pointer";
    tr.addEventListener("click",()=>showProfile(aid));
    tbl.appendChild(tr);
  }
}
function populateFilterOptions(){
  const fa=document.getElementById("fagent");
  fa.querySelectorAll("option:not(:first-child)").forEach(o=>o.remove());
  for(const [aid,r] of Object.entries(roster)){
    const o=document.createElement("option"); o.value=aid; o.textContent=r.name;
    fa.appendChild(o); }
  const fs=document.getElementById("fsymbol");
  fs.querySelectorAll("option:not(:first-child)").forEach(o=>o.remove());
  for(const s of [...new Set(events.map(e=>e.symbol).filter(Boolean))].sort()){
    const o=document.createElement("option"); o.value=s; o.textContent=s;
    fs.appendChild(o); }
}

function setModeBadge(live,running,source){
  const b=document.getElementById("modebadge");
  if(live){ b.className="badge live";
    const isMarket = source && String(source).indexOf("live_market")===0;
    const isCache = source==="cache_replay";
    if(isMarket){
      b.innerText=running?"\u25CF LIVE — market paper (shadow-only)":"LIVE — market stream idle";
    } else if(isCache){
      b.innerText=running?"\u25CF LIVE — cache paper (shadow-only)":"LIVE — cache stream idle";
    } else {
      b.innerText=running?"\u25CF LIVE — paper stream (shadow-only)":"LIVE — stream idle";
    }
  }
  else { b.className="badge sim"; b.innerText="sim-only — not trading real lots"; }
}
function stopLive(){
  if(liveTimer){clearInterval(liveTimer); liveTimer=null;}
  livePolling=false; setModeBadge(false);
  document.getElementById("seek").disabled=false;
  document.getElementById("play").disabled=false;
}

async function fetchAllEvents(base){
  let cur=0, total=1, out=[];
  while(cur<total){
    const d=await (await fetch(`${base}/events?cursor=${cur}&limit=2000`)).json();
    // gi = absolute timeline index for the per-event detail endpoint.
    d.events.forEach((e,i)=>{ e.gi=d.cursor+i; });
    out=out.concat(d.events); total=d.total; cur=d.next_cursor;
    if(!d.events.length) break;
    document.getElementById("clock").innerText=`loaded ${cur}/${total} events…`;
  }
  return out;
}

async function loadMatch(id){
  if(id==="__live__") return loadLive();
  stopLive();
  setPlaying(false); events=[]; matchId=id;
  document.getElementById("clock").innerText="loading…";
  const s=await (await fetch(`/api/v2/match/${id}/summary`)).json();
  summaryData=s; roster=s.roster||{}; drawPitch(); renderLeague(s);
  events=await fetchAllEvents(`/api/v2/match/${id}`);
  populateFilterOptions(); applyFilters();
  document.getElementById("clock").innerText=`ready · ${events.length} events`;
}

async function loadLive(){
  stopLive(); setPlaying(false); events=[]; matchId="__live__";
  document.getElementById("clock").innerText="connecting to live stream…";
  let s;
  try{ s=await (await fetch("/api/v2/live/summary")).json(); }
  catch(e){ s=null; }
  if(!s || s.error){
    document.getElementById("clock").innerText="live dir not found — start the paper loop first";
    setModeBadge(true,false); drawPitch(); return;
  }
  summaryData=s; roster=s.roster||{}; drawPitch(); renderLeague(s);
  events=await fetchAllEvents("/api/v2/live");
  populateFilterOptions(); applyFilters();
  seek(filtered.length);   // catch up: ticker shows the recent tail
  // Live tail: seek/play are disabled; new events animate as they land.
  document.getElementById("seek").disabled=true;
  document.getElementById("play").disabled=true;
  livePolling=true;
  liveTimer=setInterval(pollLive, 2000);
  pollLiveStatus();
  document.getElementById("clock").innerText=
    `LIVE · ${events.length} events so far`;
}
async function pollLiveStatus(){
  try{ const st=await (await fetch("/api/v2/live/status")).json();
    setModeBadge(true, !!st.running, st.source); }
  catch(e){ setModeBadge(true,false,null); }
}
async function pollLive(){
  if(!livePolling) return;
  let d;
  try{ d=await (await fetch(
    `/api/v2/live/events?cursor=${events.length}&limit=500`)).json(); }
  catch(e){ return; }
  if(!d.events || matchId!=="__live__") return;
  d.events.forEach((e,i)=>{ e.gi=d.cursor+i; });
  const fa=document.getElementById("fagent").value;
  const fs=document.getElementById("fsymbol").value;
  const ft=document.getElementById("ftype").value;
  for(const e of d.events){
    events.push(e);
    if(fa && e.agent!==fa && e.by!==fa) continue;
    if(fs && e.symbol!==fs) continue;
    if(ft && e.type!==ft) continue;
    filtered.push(e.gi); pos=filtered.length;
    animate(e); tick(e);
    if(e.type==="close"){ if(e.goal) goals++; else misses++; renderScore(); }
    document.getElementById("clock").innerText=
      `LIVE · ${(e.t||"").slice(0,16)} · ${events.length} events`;
  }
  if(d.events.length) pollLiveStatus();
}

async function init(){
  const data=await (await fetch("/api/v2/matches")).json();
  const sel=document.getElementById("match");
  let liveAvailable=false;
  try{ const st=await (await fetch("/api/v2/live/status")).json();
    liveAvailable=!!st.exists; }catch(e){}
  if(!data.matches.length && !liveAvailable){
    document.getElementById("clock").innerText="no replay caches found";
    drawPitch(); return;
  }
  for(const m of data.matches){
    const o=document.createElement("option"); o.value=m.id; o.textContent=m.label;
    sel.appendChild(o);
  }
  if(liveAvailable){
    const o=document.createElement("option");
    o.value="__live__"; o.textContent="\u25CF LIVE — squad paper stream";
    sel.appendChild(o);
  }
  sel.onchange=()=>loadMatch(sel.value);
  document.getElementById("play").onclick=()=>setPlaying(!playing);
  document.getElementById("speed").onchange=()=>{ if(playing){setPlaying(false);setPlaying(true);} };
  document.getElementById("seek").oninput=e=>{ setPlaying(false); seek(Number(e.target.value)); };
  document.getElementById("jumpbtn").onclick=jumpToDate;
  document.getElementById("jumpdate").onkeydown=e=>{ if(e.key==="Enter") jumpToDate(); };
  for(const fid of ["fagent","fsymbol","ftype"])
    document.getElementById(fid).onchange=()=>{ setPlaying(false); applyFilters(); };
  document.getElementById("mclose").onclick=closeModal;
  document.getElementById("overlay").addEventListener("click",e=>{
    if(e.target.id==="overlay") closeModal(); });
  document.getElementById("hidesilent").onchange=e=>{
    // Toggle silent-tick visibility in-place without a full re-seek,
    // so playback position and score aren't disturbed. Applies to
    // rows currently in the ticker; new rows respect the checkbox at
    // insertion time (see tick()).
    const hide=e.target.checked;
    document.querySelectorAll(".tk.tick-summary").forEach(el=>{
      el.classList.toggle("hidden", hide);
    });
  };
  if(data.matches.length) await loadMatch(data.matches[0].id);
  else await loadLive();
}
init();
</script></body></html>"""

V2_PAGE = (_V2_TEMPLATE
           .replace("__BASE_CSS__", _BASE_CSS)
           .replace("__NAV__", nav('v2')))
