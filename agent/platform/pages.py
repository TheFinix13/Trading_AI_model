"""Static HTML/JS pages for the platform server (hub, /v1, /v2).

All pages are self-contained strings (no CDN, no build step) so the
server runs on the VM with stdlib only. The v2 pitch page renders an
SVG football field and plays back the squad event timeline served by
``/api/v2/...`` (see ``squad_events.py`` for the event schema).
"""
from __future__ import annotations

# Sprint 1 (D047 retro §5.5): `_BASE_CSS` carries a semantic version so
# any layout / typography / class-name change is a deliberate release
# step. Bump major on layout/typography/class-name breaks, minor on
# additive tokens, patch on bug-fix / typo / a11y correction.
# `tests/platform/test_pages_shared_states.py` pins this string so an
# accidental drift fails the suite.
_BASE_CSS_VERSION = "1.1.0"

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
.nav{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:18px;font-size:13px}
.nav a{padding:4px 12px;border:1px solid var(--border);border-radius:999px;
  white-space:nowrap;line-height:1.6}
.nav a.here{background:var(--panel);border-color:var(--accent)}
@media (max-width: 700px){
  body{padding:16px 14px}
  .nav{gap:8px;margin-bottom:14px}
  h1{font-size:19px}
  #updated{position:static;display:block;margin-bottom:8px}
}
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
<a href="/hq" class="{hq}">HQ · Blue Lock Trading Co.</a>
<a href="/performance" class="{performance}">Performance</a>
<a href="/players" class="{players}">Squad</a>
<a href="/highlights" class="{highlights}">Highlights</a>
<a href="/leaderboard" class="{leaderboard}">Standings</a>
<a href="/research" class="{research}">Research</a>
</div>"""


def nav(active: str) -> str:
    """Render the top nav pills; ``active`` marks one pill with .here.

    Accepted values: ``hub`` / ``v1`` / ``v2`` / ``hq`` / ``performance`` /
    ``players`` / ``highlights`` / ``leaderboard`` / ``research``. New Sprint 1
    destinations (``broker``, ``onboarding``) render the nav with no
    active pill so their dedicated wizard pages don't accidentally
    advertise themselves as a permanent top-level route. Unknown values
    render the nav with no active pill (safe default -- users can still
    see where they are from the URL).
    """
    return _NAV.format(
        hub="here" if active == "hub" else "",
        v1="here" if active == "v1" else "",
        v2="here" if active == "v2" else "",
        hq="here" if active == "hq" else "",
        performance="here" if active == "performance" else "",
        players="here" if active == "players" else "",
        highlights="here" if active == "highlights" else "",
        leaderboard="here" if active == "leaderboard" else "",
        research="here" if active == "research" else "",
    )


# ---------------------------------------------------------------------------
# F005 -- shared loading / error / empty-state helpers
# ---------------------------------------------------------------------------
#
# Every page's fetch() must have three states (loading, error, empty)
# per the F005 spec. Rather than re-implement per page, we ship a
# single `withStates(box, fetcher, renderer, opts?)` helper below and
# the matching skeleton / error / empty CSS. F001, F002, F003 all
# consume this; the pattern becomes hard to forget.
#
# Copy strings originate from `company/brand/error_copy.md` -- the
# JS-side CANONICAL_ERROR_COPY mirrors that document. When Brand
# revises the copy library, this constant tracks the change.

_SKELETON_CSS = r"""
/* F005: skeleton placeholders + error / empty-state affordances.
 * Shimmer uses only --panel and a slightly lighter shade so no new
 * palette tokens are introduced. Elements the caller can pin size
 * to (KPI tile, card row, chart, table row) get consistent looking
 * placeholders so there's no layout shift when data lands. */
@keyframes shimmer {
  0%   { background-position: -200px 0; }
  100% { background-position: calc(200px + 100%) 0; }
}
.sk {
  background: linear-gradient(90deg,
    var(--panel) 0%, #21262d 40%, var(--panel) 80%);
  background-size: 200px 100%;
  background-repeat: no-repeat;
  animation: shimmer 1.4s linear infinite;
  border-radius: 6px;
  display: inline-block;
  color: transparent;
}
.sk-line { height: 12px; width: 100%; margin: 6px 0; }
.sk-line.short { width: 40%; }
.sk-line.med { width: 65%; }
.sk-tile {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  min-height: 72px;
}
.sk-tile .sk-line { display: block; }
.sk-chart {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  height: 220px;
  position: relative;
  overflow: hidden;
}
.sk-chart::after {
  content: "";
  position: absolute; inset: 0;
  background: linear-gradient(90deg,
    transparent 0%, rgba(88,166,255,.06) 50%, transparent 100%);
  background-size: 220px 100%;
  animation: shimmer 1.6s linear infinite;
}
.sk-row {
  display: flex; gap: 10px; padding: 6px 0;
  border-bottom: 1px solid #1c2129;
}
.sk-row .sk-line { flex: 1; }
.sk-error, .sk-empty {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
  color: var(--fg);
  font-size: 13.5px;
  line-height: 1.55;
}
.sk-error { border-left: 3px solid var(--amber); }
.sk-empty { border-left: 3px solid var(--dim); }
.sk-error .msg, .sk-empty .msg { color: var(--fg); }
.sk-error .foot, .sk-empty .foot {
  color: var(--dim); font-size: 11.5px; margin-top: 8px;
}
.sk-error .retry, .sk-empty .retry {
  margin-top: 10px;
  background: #21262d;
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 14px;
  font-size: 12.5px;
  cursor: pointer;
}
.sk-error .retry:hover, .sk-empty .retry:hover {
  border-color: var(--accent); color: var(--accent);
}
"""

# The CANONICAL_ERROR_COPY object mirrors company/brand/error_copy.md
# keys. Frontend picks a key from a fetch outcome (network / 5xx /
# 401 / etc.), then looks up the user-facing string here. Overriding
# per-call happens via opts.errorCopy in withStates().
_ERROR_COPY_JS = r"""
const CANONICAL_ERROR_COPY = {
  "server_restarting":
    "Couldn't reach the platform server \u2014 it might be " +
    "restarting. Try again in a moment.",
  "temporary_glitch":
    "Something didn't come through this time. That's usually a " +
    "hiccup \u2014 one more try often works.",
  "unauthorized":
    "This view is protected \u2014 add a token to the URL " +
    "(?token=\u2026) or ask the operator for one.",
  "not_configured":
    "Not set up on this server yet. The operator can point this " +
    "page at the data by reading the runbook.",
  "no_data_yet":
    "No data yet \u2014 the squad is watching the market. Come " +
    "back after the next H4 bar close.",
  "unknown_route":
    "That page doesn't exist. Check the URL, or head back to the hub.",
  "api_not_found":
    "The data we need isn't available on this server. The page " +
    "will keep what it has and try again.",
  "stale_data":
    "The numbers you're seeing haven't updated in a while \u2014 " +
    "the backing data source may be paused. The page will keep trying."
};

const DEFAULT_ERROR_MAP = {
  "network":       "server_restarting",
  "http_5xx":      "temporary_glitch",
  "http_401":      "unauthorized",
  "http_404":      "api_not_found",
  "json_parse":    "temporary_glitch",
  "unconfigured":  "not_configured"
};
"""

# The withStates() helper wraps a fetch promise with the three-state
# lifecycle. Callers pass:
#   box       -- the DOM element to render into (already sized in CSS
#                so there's no layout shift when data lands).
#   fetcher   -- () => Promise<any>. Should return {__error__: "..."}
#                or {__auth__: true} on failure (the fetchJson helper
#                convention already used throughout the platform).
#   renderer  -- (data, box) => void. Called on success with the payload
#                and the box element. If it returns the string "empty",
#                the helper swaps in the empty-state affordance.
#   opts      -- optional:
#                  skeletonHtml : string  (defaults to a generic KPI +
#                                          chart + rows layout)
#                  emptyCopyKey : string  (which canonical empty-copy
#                                          key to use; default 'no_data_yet')
#                  emptyMessage : string  (override text if key insufficient)
#                  errorCopy    : object  (per-call override of the
#                                          fetch-outcome -> copy key map)
#                  retryLabel   : string  ('Try again' by default)
#
# On failure: the box is replaced with an error affordance including
# a retry button that re-invokes fetcher and re-runs the same
# renderer. State is idempotent -- calling withStates() again on the
# same box replaces its content cleanly.
_WITH_STATES_JS = r"""
function classifyFetchOutcome(result){
  if(result && result.__auth__)   return "http_401";
  if(!result || result.__error__ == null) return null;
  const err = String(result.__error__ || "");
  const m = err.match(/^HTTP\s+(\d+)/i);
  if(m){
    const code = parseInt(m[1], 10);
    if(code === 401) return "http_401";
    if(code === 404) return "http_404";
    if(code >= 500)  return "http_5xx";
    return "http_5xx";
  }
  if(/JSON|parse|unexpected token/i.test(err)) return "json_parse";
  return "network";
}
function skeletonHtml(){
  // Generic three-block skeleton: a header line, a tile grid, and a
  // chart placeholder. Callers pass opts.skeletonHtml for anything
  // custom (per-page mocks pin specific dimensions).
  return (
    '<div class="sk sk-line med" aria-hidden="true"></div>'+
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,'+
      'minmax(180px,1fr));gap:12px;margin:12px 0">'+
      '<div class="sk-tile"><div class="sk sk-line short"></div>'+
        '<div class="sk sk-line"></div></div>'+
      '<div class="sk-tile"><div class="sk sk-line short"></div>'+
        '<div class="sk sk-line"></div></div>'+
      '<div class="sk-tile"><div class="sk sk-line short"></div>'+
        '<div class="sk sk-line"></div></div>'+
    '</div>'+
    '<div class="sk-chart" role="progressbar" aria-label="Loading"></div>'
  );
}
function _esc(x){
  const d = document.createElement("div");
  d.innerText = String(x == null ? "" : x);
  return d.innerHTML;
}
function renderErrorState(box, copyKey, retryLabel, onRetry){
  const msg = CANONICAL_ERROR_COPY[copyKey] ||
              CANONICAL_ERROR_COPY["temporary_glitch"];
  box.innerHTML =
    '<div class="sk-error">'+
      '<div class="msg">'+_esc(msg)+'</div>'+
      '<button class="retry" type="button">'+_esc(retryLabel)+'</button>'+
    '</div>';
  const btn = box.querySelector(".retry");
  if(btn && typeof onRetry === "function") btn.addEventListener("click", onRetry);
}
function renderEmptyState(box, copyKey, override, retryLabel, onRetry){
  const msg = override || CANONICAL_ERROR_COPY[copyKey] ||
              CANONICAL_ERROR_COPY["no_data_yet"];
  const retryHtml = retryLabel
    ? '<button class="retry" type="button">'+_esc(retryLabel)+'</button>'
    : "";
  box.innerHTML =
    '<div class="sk-empty">'+
      '<div class="msg">'+_esc(msg)+'</div>'+
      retryHtml+
    '</div>';
  const btn = box.querySelector(".retry");
  if(btn && typeof onRetry === "function") btn.addEventListener("click", onRetry);
}
async function withStates(box, fetcher, renderer, opts){
  opts = opts || {};
  const errorCopy = Object.assign({}, DEFAULT_ERROR_MAP, opts.errorCopy || {});
  const skel = opts.skeletonHtml || skeletonHtml();
  const retryLabel = opts.retryLabel || "Try again";
  box.innerHTML = skel;
  let result;
  try { result = await fetcher(); }
  catch(e){ result = {__error__: String((e && e.message) || e)}; }
  // Backend-signalled "unconfigured" -- payload came back 200 but the
  // module returned a skeleton (e.g. missing ledger). Treat as a
  // dedicated copy key so operators see the runbook hint.
  const meta = (result && result.meta) || {};
  if(meta.unconfigured){
    renderErrorState(box, errorCopy["unconfigured"] || "not_configured",
      retryLabel, () => withStates(box, fetcher, renderer, opts));
    return;
  }
  const kind = classifyFetchOutcome(result);
  if(kind){
    renderErrorState(box, errorCopy[kind] || "temporary_glitch",
      retryLabel, () => withStates(box, fetcher, renderer, opts));
    return;
  }
  // Success -- delegate to the caller's renderer. If it returns
  // "empty" the helper swaps in the empty-state affordance (with an
  // optional retry, since data can appear later).
  let verdict = null;
  try { verdict = renderer(result, box); }
  catch(e){
    renderErrorState(box, "temporary_glitch", retryLabel,
      () => withStates(box, fetcher, renderer, opts));
    return;
  }
  if(verdict === "empty"){
    renderEmptyState(box, opts.emptyCopyKey || "no_data_yet",
      opts.emptyMessage, opts.retryLabel || "Try again",
      () => withStates(box, fetcher, renderer, opts));
  }
}
"""


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
/* F019 (I003): missing-broker state chip. Additive, hub-local CSS --
 * no _BASE_CSS_VERSION bump. Hidden by default; JS shows it only when
 * setup completed without a broker connection. */
.broker-chip{display:inline-block;background:rgba(210,153,34,.10);
  border:1px solid rgba(210,153,34,.4);border-left:3px solid var(--amber);
  border-radius:6px;padding:8px 12px;margin-bottom:14px;font-size:13px;
  line-height:1.5;max-width:640px}
.broker-chip b{color:var(--amber)}
</style></head><body>
<h1>Multi-pair trading platform</h1>
<div class="sub">Two AI agents on Exness demo MT5 &mdash; v1 trades real demo orders,
v2 shadow-simulates alongside for research. Auto-refreshes every 15&nbsp;s.</div>
__NAV__
<div id="updated">loading&hellip;</div>

<div id="broker-chip" class="broker-chip" style="display:none">
  <b>Broker not connected yet</b> &mdash; trading stays paused until a
  broker account is linked.
  <a href="/settings/broker">Connect one now &rarr;</a>
</div>

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
  <a class="tile" href="/hq">
    <h2>HQ &middot; Blue Lock Trading Co.
        <span class="badge sim" id="tile-hq-badge">company</span></h2>
    <p>See how the product is being built. Kanban of features by stage,
    role grid across all 19 seats (Executive / Executive-adjacent /
    Design / Engineering / Business), R&amp;D pulse (intake +
    experiments + latest finding), decisions log, blockers panel,
    sprint KPIs. Reads live from
    <code>company/ledger/company_state.json</code>. This is the
    company running around the trading agent &mdash; not a black box.</p>
    <div class="summary" id="tile-hq-summary">&hellip;</div>
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

<details class="glossary" id="glossary">
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
    return {cls:"alive", text:"live shadow paper", live:true};
  if(v2.running && src === "cache_replay")
    return {cls:"sim", text:"cache replay", live:true};
  if(v2.running) return {cls:"alive", text:"live", live:true};
  return {cls:"stale", text:"idle"};
}
function setBadge(id, cls, text, opts){
  const el = document.getElementById(id);
  if(!el) return;
  el.className = "badge " + cls;
  // Live badges get a pulsing ● glyph so LIVE state is legible at a
  // glance across the hub. innerText path is preserved for the rest
  // of the badges (idle / auth / error) so no other renderer changes.
  if(opts && opts.live){
    const d = document.createElement("div");
    d.innerText = String(text);
    el.innerHTML = '<span class="live-dot">\u25CF</span> ' + d.innerHTML;
  } else {
    el.innerText = text;
  }
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
  setBadge("kpi-v2-badge", b.cls, b.text, {live: b.live});
  setBadge("tile-v2-badge", b.cls, b.text, {live: b.live});
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

function renderHqTile(hq){
  const badgeEl = document.getElementById("tile-hq-badge");
  const summaryEl = document.getElementById("tile-hq-summary");
  if(!summaryEl || !badgeEl) return;
  if(hq.__auth__){
    setBadge("tile-hq-badge","stale","auth required");
    summaryEl.innerText = "pass ?token= in URL to see company state";
    return;
  }
  if(hq.__error__ && hq.__error__ !== "HTTP 404"){
    setBadge("tile-hq-badge","down","api error");
    summaryEl.innerText = "/api/hq/state: " + hq.__error__;
    return;
  }
  const meta = hq.meta || {};
  const kpis = hq.kpis || {};
  if(meta.unconfigured){
    setBadge("tile-hq-badge","no-data","not configured");
    summaryEl.innerText = meta.unconfigured_reason || "ledger not on disk";
    return;
  }
  setBadge("tile-hq-badge","sim","company");
  const shipped = kpis.features_shipped_sprint_0 || 0;
  const total = kpis.features_total_sprint_0 || 0;
  const active = kpis.active_roles || 0;
  const totalRoles = kpis.total_roles || 0;
  const bl = (hq.blockers || []).length;
  const blSuffix = bl > 0
    ? (" \u00b7 " + bl + " blocker" + (bl === 1 ? "" : "s"))
    : "";
  summaryEl.innerText =
    "sprint 0 \u00b7 " + shipped + "/" + total + " features shipped" +
    " \u00b7 " + active + "/" + totalRoles + " roles active" +
    blSuffix;
}

function renderBrokerChip(ob){
  // F019 (I003): the chip is a nudge, not a data panel -- it shows
  // only when setup finished WITHOUT a broker connection, and any
  // fetch problem hides it (fail-quiet; error/empty states of the
  // real panels stay unchanged).
  const el = document.getElementById("broker-chip");
  if(!el) return;
  const show = ob && !ob.__auth__ && !ob.__error__ &&
    ob.completed === true && ob.broker_connected === false;
  el.style.display = show ? "" : "none";
}

async function refreshAll(){
  const [v1, v2, evs, health, hq, ob] = await Promise.all([
    fetchJson("/api/v1/status"),
    fetchJson("/api/v2/live/status"),
    fetchJson("/api/v2/live/events?cursor=0&limit=5"),
    fetchJson("/healthz"),
    fetchJson("/api/hq/state"),
    fetchJson("/api/onboarding/state"),
  ]);
  const evsTotal = (evs && !evs.__auth__ && !evs.__error__)
    ? (evs.total != null ? evs.total : (evs.events || []).length) : null;
  renderV1Kpi(v1);
  renderV2Kpi(v2, evsTotal);
  renderSysKpi(health, v1);
  renderActivity(evs);
  renderHqTile(hq);
  renderBrokerChip(ob);
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
.card{{word-break:break-word;overflow-wrap:anywhere}}
.card h2{{margin:0 0 10px;font-size:17px;display:flex;align-items:center;gap:10px}}
.kv{{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;font-size:13px;margin:8px 0}}
.kv dt{{color:var(--dim)}} .kv dd{{margin:0}}
.pos{{border:1px solid var(--border);border-radius:8px;padding:8px 12px;margin:8px 0;font-size:13px}}
.pos .dir-long{{color:var(--green);font-weight:700}} .pos .dir-short{{color:var(--red);font-weight:700}}
.pos .dir-chip{{font-size:10px;font-weight:700;padding:1px 8px;border-radius:999px;
  text-transform:uppercase;letter-spacing:.03em;vertical-align:middle}}
.pos .dir-chip.long{{background:rgba(63,185,80,.15);color:var(--green);
  border:1px solid rgba(63,185,80,.4)}}
.pos .dir-chip.short{{background:rgba(248,81,73,.15);color:var(--red);
  border:1px solid rgba(248,81,73,.4)}}
.pos .exc-pills{{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}}
.pos .exc-pill{{font-size:11px;font-weight:500;padding:2px 8px;border-radius:999px;
  background:rgba(139,148,158,.1);border:1px solid var(--border);
  color:var(--fg);white-space:nowrap;font-variant-numeric:tabular-nums;
  display:inline-flex;gap:5px;align-items:baseline}}
.pos .exc-pill .k{{color:var(--dim);font-size:10px;text-transform:uppercase;
  letter-spacing:.03em;font-weight:600}}
.pos .exc-pill.mae{{background:rgba(248,81,73,.06);border-color:rgba(248,81,73,.28)}}
.pos .exc-pill.mfe{{background:rgba(63,185,80,.06);border-color:rgba(63,185,80,.28)}}
.pos .exc-pill.profit-pos{{background:rgba(63,185,80,.08);
  border-color:rgba(63,185,80,.4);color:var(--green);font-weight:600}}
.pos .exc-pill.profit-neg{{background:rgba(248,81,73,.08);
  border-color:rgba(248,81,73,.4);color:var(--red);font-weight:600}}
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
function fmtPips(v){{ if(v==null||isNaN(v)) return null;
  const n=Number(v); return (Math.round(n*10)/10).toFixed(1)+" pips"; }}
function fmtPx(v){{ if(v==null||isNaN(v)) return null;
  return Number(v).toFixed(5); }}
function fmtMoney(v){{ if(v==null||isNaN(v)) return null;
  const n=Number(v); const sign=n<0?"-":(n>0?"+":"");
  return sign+"$"+Math.abs(n).toFixed(2); }}
function excursionPills(exc){{
  // Parse the excursion dict written by
  // agent/live/monitor.py::_update_excursion into a compact pill row.
  // Missing / malformed fields are silently skipped so the section
  // degrades gracefully -- never render a raw JSON overflow line.
  if(!exc || typeof exc!=="object") return "";
  const pills=[];
  const mae=fmtPips(exc.mae_pips);
  if(mae!=null) pills.push({{cls:"mae",k:"MAE",v:mae}});
  const mfe=fmtPips(exc.mfe_pips);
  if(mfe!=null) pills.push({{cls:"mfe",k:"MFE",v:mfe}});
  const last=fmtPx(exc.last_price);
  if(last!=null) pills.push({{cls:"",k:"Last",v:last}});
  const profit=fmtMoney(exc.last_profit);
  if(profit!=null){{
    const cls = Number(exc.last_profit)>0 ? "profit-pos"
              : Number(exc.last_profit)<0 ? "profit-neg" : "";
    pills.push({{cls:cls,k:"Profit",v:profit}});
  }}
  const stop=fmtPx(exc.broker_stop);
  if(stop!=null) pills.push({{cls:"",k:"Stop",v:stop}});
  const tp=fmtPx(exc.broker_tp);
  if(tp!=null) pills.push({{cls:"",k:"TP",v:tp}});
  const openPx=fmtPx(exc.open_price);
  if(openPx!=null) pills.push({{cls:"",k:"Open",v:openPx}});
  if(!pills.length) return "";
  return '<div class="exc-pills">'+pills.map(p =>
    '<span class="exc-pill '+p.cls+'"><span class="k">'+esc(p.k)+
    '</span> '+esc(p.v)+'</span>').join("")+'</div>';
}}
function posHtml(p){{
  const dir=(p.direction||"?").toLowerCase();
  const dirChip=(dir==="long"||dir==="short")
    ? '<span class="dir-chip '+dir+'">'+dir.toUpperCase()+'</span>'
    : '<span class="dim">'+esc(dir.toUpperCase())+'</span>';
  const bits=[];
  for(const k of ["entry","sl","soft_stop","tp","lots","lot_size","timeframe","alpha"]){{
    if(p[k]!=null) bits.push(k+"="+p[k]); }}
  const exc=excursionPills(p.excursion);
  return '<div class="pos">'+dirChip+
    ' ticket '+esc(p.ticket)+' — '+esc(bits.join("  "))+exc+'</div>'; }}
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
/* v2 UX pass — mode picker with info button, popover, waiting panel,
 * hover tooltips, first-visit ribbon, guided tour overlay. */
.mode-wrap{position:relative;display:inline-flex;align-items:center;gap:6px}
.info-btn{background:none;border:1px solid var(--border);color:var(--dim);
  border-radius:999px;width:26px;height:26px;padding:0;cursor:pointer;
  font-size:13px;line-height:1;display:inline-flex;align-items:center;
  justify-content:center;transition:border-color .15s,color .15s}
.info-btn:hover,.info-btn:focus{border-color:var(--accent);color:var(--fg);outline:none}
.popover{position:fixed;z-index:60;background:var(--panel);
  border:1px solid var(--border);border-radius:10px;padding:14px 16px 12px;
  max-width:380px;font-size:12.8px;line-height:1.55;
  box-shadow:0 8px 32px rgba(0,0,0,.5);color:var(--fg);display:none}
.popover.open{display:block}
.popover .close{position:absolute;top:4px;right:8px;background:none;
  border:none;color:var(--dim);font-size:16px;cursor:pointer;line-height:1}
.popover .close:hover{color:var(--fg)}
.popover code{background:#0d1117;padding:1px 5px;border-radius:4px;font-size:11.5px;color:var(--dim)}
.popover .foot{margin-top:10px;font-size:11.5px;color:var(--dim)}
.popover .foot a{color:var(--accent)}
#waiting-panel{margin:12px 0 4px;padding:14px 16px;border-left:3px solid var(--accent);
  transition:opacity .5s;display:none}
#waiting-panel.open{display:block}
#waiting-panel h3{margin:0 0 8px;font-size:13.5px;color:var(--fg);
  display:flex;align-items:center;gap:8px}
#waiting-panel h3 .pulse{width:8px;height:8px;background:var(--red);border-radius:50%;
  box-shadow:0 0 8px rgba(248,81,73,.7);animation:wpulse 1.6s infinite ease-in-out}
@keyframes wpulse{0%,100%{opacity:.6}50%{opacity:1}}
#waiting-panel .row{display:flex;justify-content:space-between;font-size:12.5px;
  padding:3px 0;color:var(--dim);gap:12px}
#waiting-panel .row .v{color:var(--fg);font-variant-numeric:tabular-nums}
#waiting-panel .pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
#waiting-panel .foot{margin-top:8px;font-size:11.5px;color:var(--dim);font-style:italic}
.pill{font-size:11px;font-weight:600;padding:2px 9px 2px 7px;border-radius:999px;
  background:rgba(139,148,158,.12);border:1px solid var(--border);
  color:var(--fg);white-space:nowrap;display:inline-flex;align-items:center;gap:5px}
.pill .dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.player-tooltip{position:fixed;z-index:70;background:var(--panel);
  border:1px solid var(--border);border-radius:8px;padding:8px 10px;
  max-width:260px;font-size:12px;line-height:1.5;box-shadow:0 6px 20px rgba(0,0,0,.5);
  pointer-events:none;display:none;color:var(--fg)}
.player-tooltip.open{display:block}
.player-tooltip .n{font-weight:700;font-size:13px}
.player-tooltip .p{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  color:var(--accent);font-size:11.5px;margin:3px 0}
.player-tooltip .s{color:var(--dim);font-size:11px}
.player-tooltip .r{color:var(--fg);font-size:11.5px;margin-top:4px}
#v2-ribbon{background:rgba(88,166,255,.08);border:1px solid rgba(88,166,255,.35);
  border-radius:8px;padding:9px 14px;margin-bottom:14px;font-size:13px;
  display:none;align-items:center;gap:14px;flex-wrap:wrap;color:var(--fg);
  transition:opacity .35s}
#v2-ribbon.open{display:flex}
#v2-ribbon .msg{flex:1;min-width:200px}
#v2-ribbon button{background:#21262d;border:1px solid var(--border);color:var(--fg);
  border-radius:6px;padding:4px 12px;font-size:12.5px;cursor:pointer}
#v2-ribbon button.primary{background:rgba(88,166,255,.18);border-color:var(--accent);
  color:var(--accent)}
#v2-ribbon button:hover{border-color:var(--accent);color:var(--accent)}
#take-tour{position:fixed;top:14px;right:20px;font-size:12px;color:var(--dim);
  border:1px solid var(--border);padding:4px 10px;border-radius:999px;
  background:var(--panel);cursor:pointer;z-index:40;user-select:none}
#take-tour:hover{color:var(--accent);border-color:var(--accent);text-decoration:none}
#tour-shade{position:fixed;inset:0;background:rgba(1,4,9,.72);z-index:100;
  display:none;cursor:pointer}
#tour-shade.open{display:block}
.tour-spotlight{position:relative;z-index:110;box-shadow:0 0 0 3px rgba(88,166,255,.55),
  0 0 24px rgba(88,166,255,.3);border-radius:8px;transition:box-shadow .2s}
#tour-tooltip{position:fixed;z-index:120;background:var(--panel);
  border:1px solid var(--accent);border-radius:10px;padding:14px 16px;
  max-width:340px;font-size:13px;line-height:1.55;box-shadow:0 10px 40px rgba(0,0,0,.6);
  color:var(--fg);display:none}
#tour-tooltip.open{display:block}
#tour-tooltip h4{margin:0 0 6px;font-size:14px;color:var(--accent)}
#tour-tooltip .step-meta{font-size:11px;color:var(--dim);text-transform:uppercase;
  letter-spacing:.06em;margin-bottom:4px}
#tour-tooltip .actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center}
#tour-tooltip button{background:#21262d;border:1px solid var(--border);color:var(--fg);
  border-radius:6px;padding:5px 12px;font-size:12.5px;cursor:pointer}
#tour-tooltip button.primary{background:rgba(88,166,255,.2);border-color:var(--accent);
  color:var(--accent)}
#tour-tooltip button:hover{border-color:var(--accent)}
#tour-tooltip button.skip{margin-left:auto;color:var(--dim);border-color:transparent;
  background:transparent}
#tour-tooltip button.skip:hover{color:var(--fg);border-color:var(--border)}
/* v0.40 additions -- workspace panel + LIVE-connection pill + polish.
 * Grouped here so a future consolidation pass can pull the whole
 * block into a dedicated file without cherry-picking selectors. */
.card{transition:opacity 200ms ease}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.card.fade-in{animation:fadeIn 300ms ease}
/* Shared tooltip-panel class -- Item-3 info popover, Item-6 player
 * tooltip, and the workspace-thought hover use the same base look. */
.tooltip-panel{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:12px 14px;color:var(--fg);
  box-shadow:0 6px 24px rgba(0,0,0,.5)}
/* Pulsing ● glyph on LIVE indicators. Used in header badge, hub
 * cards, and #live-connection. Kept subtle -- 2 s ease loop. */
@keyframes livePulse{0%,100%{opacity:1}50%{opacity:.35}}
.live-dot{animation:livePulse 2s ease-in-out infinite;display:inline-block}
@keyframes rotate360{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.spin-once{animation:rotate360 300ms ease}
/* LIVE-connection pill: replaces the Play/speed transport in LIVE
 * mode so the user isn't teased with meaningless controls. */
#live-connection{display:none;align-items:center;gap:10px;font-size:12.5px;
  color:var(--dim);background:rgba(248,81,73,.06);
  border:1px solid rgba(248,81,73,.28);border-radius:999px;padding:4px 12px}
#live-connection.open{display:inline-flex}
#live-connection .dot{color:var(--red)}
#live-connection button{background:none;border:1px solid var(--border);
  color:var(--dim);border-radius:999px;width:24px;height:24px;padding:0;
  font-size:12px;line-height:1;cursor:pointer;display:inline-flex;
  align-items:center;justify-content:center}
#live-connection button:hover{color:var(--fg);border-color:var(--accent)}
#replay-transport{display:inline-flex;gap:10px;align-items:center}
#replay-transport.hidden{display:none}
/* Workspace panel -- "what the squad is thinking". Cell grid auto-fits
 * min 280px; per-agent grouping is done by JS-sort so we can keep the
 * layout a single CSS grid rather than per-agent subheaders. */
#workspace-panel{margin-top:14px}
#workspace-panel .meta{font-size:12px;color:var(--dim);margin:0 0 10px;
  display:flex;justify-content:space-between;align-items:center;gap:8px}
#workspace-panel .meta button{background:none;border:1px solid var(--border);
  color:var(--dim);border-radius:6px;padding:2px 10px;font-size:11.5px;
  cursor:pointer}
#workspace-panel .meta button:hover{color:var(--fg);border-color:var(--accent)}
.thought-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:10px}
.thought-card{border:1px solid var(--border);border-radius:8px;
  padding:10px 12px;background:rgba(139,148,158,.04);
  font-size:12.5px;line-height:1.5;transition:border-color .15s}
.thought-card:hover{border-color:var(--accent)}
.thought-card .hd{display:flex;align-items:center;gap:8px;font-size:12.5px;
  margin-bottom:6px}
.thought-card .hd .dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.thought-card .hd .nm{font-weight:700}
.thought-card .hd .sym{color:var(--dim);font-size:11.5px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.thought-card .hd .conf{margin-left:auto;font-size:11.5px;color:var(--dim);
  font-variant-numeric:tabular-nums}
.thought-card .narrative{color:var(--fg);font-size:12.5px;
  margin:2px 0 8px;font-style:italic;word-break:break-word;
  overflow-wrap:anywhere}
.thought-card .conf-bar{height:3px;background:rgba(139,148,158,.15);
  border-radius:2px;overflow:hidden;margin-bottom:8px}
.thought-card .conf-bar > span{display:block;height:100%;
  background:var(--accent);border-radius:2px}
.thought-card .tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px}
.thought-card .tag{font-size:10px;color:var(--dim);
  background:rgba(139,148,158,.1);padding:1px 6px;border-radius:4px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.thought-card .foot{color:var(--dim);font-size:11px;
  border-top:1px solid rgba(139,148,158,.15);padding-top:6px;
  margin-top:4px;display:flex;flex-wrap:wrap;gap:10px;
  font-variant-numeric:tabular-nums}
.thought-card .foot .k{color:var(--dim)}
.thought-card .foot .v{color:var(--fg)}
.thought-card.dir-long .hd{border-left:none}
.thought-card.dir-long .foot .v.dir{color:var(--green)}
.thought-card.dir-short .foot .v.dir{color:var(--red)}
#workspace-empty{padding:20px 16px;text-align:center;color:var(--dim);
  font-size:12.5px;font-style:italic}
/* 2026-07-24 I002 additions -- "why quiet" line + upcoming-events panel
 * + Sae's disabled-on-pitch state. Grouped like the v0.40 block above. */
#quiet-line{margin:2px 0 6px;font-size:12.5px;color:var(--fg);
  background:rgba(210,153,34,.08);border:1px solid rgba(210,153,34,.3);
  border-radius:8px;padding:5px 10px;display:inline-block}
.evrow{display:flex;align-items:baseline;gap:8px;padding:5px 2px;
  border-bottom:1px solid var(--border);font-size:12.5px}
.evrow:last-child{border-bottom:none}
.evrow .when{color:var(--dim);white-space:nowrap;
  font-variant-numeric:tabular-nums;font-size:11.5px}
.evrow .ttl{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.evrow .cd{color:var(--amber);white-space:nowrap;font-size:11.5px;
  font-variant-numeric:tabular-nums}
.evrow .sae-tag{font-size:10px;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;color:#e3b341;border:1px solid rgba(227,179,65,.5);
  background:rgba(227,179,65,.12);border-radius:6px;padding:1px 6px;
  white-space:nowrap}
/* Sae dimmed while state.json says sae_enabled=false: still on the
 * pitch (the roster is honest about the squad) but visibly benched. */
.player-off{opacity:.35}
</style></head><body>
<h1>Blue Lock squad — the pitch <span class="dim">v2 · M001 ensemble</span>
 <span class="badge sim" id="modebadge">sim-only — not trading real lots</span></h1>
<!-- "Why is the pitch quiet?" line — LIVE mode only, fed by
     live_status().quiet_reason so silence is legible, not spooky. -->
<div id="quiet-line" role="status" aria-live="polite" style="display:none">
  <span class="dim">why quiet:</span> <span id="quiet-reason">—</span>
</div>
<div class="sub" id="v2-subtitle">Walk-forward replay played as a match: passes are proposals, tackles are
aggregator rejections, the wall is Sentinel, goals are winning trades. Click a player for
their profile; click a ticker row for the full event payload.</div>
__NAV__
<div id="v2-ribbon" role="status">
  <span class="msg">💡 <b>First time here?</b> Click ℹ️ next to the mode selector for a
  quick explanation. This page is display-only — <b>real bars, no orders sent</b>.</span>
  <button class="primary" id="ribbon-tour">Show me around →</button>
  <button id="ribbon-dismiss" aria-label="Dismiss">Dismiss ×</button>
</div>
<a href="#" id="take-tour" role="button">Take the tour</a>
<div class="layout">
<div id="pitchwrap">
  <div class="controls">
    <span class="mode-wrap">
      <select id="match" aria-label="playback mode"></select>
      <button type="button" id="mode-info-btn" class="info-btn"
              title="What does this mode mean?" aria-label="Mode help">i</button>
    </span>
    <span id="replay-transport">
      <button id="play">&#9654; Play</button>
      <select id="speed" aria-label="playback speed">
        <option value="8" selected>🐢 Slow — 8 events/s</option>
        <option value="16">⏩ Medium — 16 events/s</option>
        <option value="60">🚀 Fast — 60 events/s</option>
        <option value="120">⚡ Turbo — 120 events/s</option>
      </select>
    </span>
    <span id="live-connection" role="status" aria-live="polite">
      <span class="dot live-dot">&#9679;</span>
      <span>LIVE · connected · refresh every 15s ·
        <span id="live-event-count">0</span> events since reset</span>
      <button type="button" id="live-refresh"
              title="Refresh now" aria-label="Refresh now">&#8635;</button>
    </span>
    <span id="clock">—</span>
    <span id="score">Goals <b id="goals">0</b> · Misses <span id="misses">0</span></span>
  </div>
  <div id="waiting-panel" class="card" role="status" aria-live="polite">
    <h3><span class="pulse"></span>Waiting on the market</h3>
    <div class="row"><span>Next bar close</span>
      <span class="v" id="wp-next">—</span></div>
    <div class="row"><span>Workspace</span>
      <span class="v" id="wp-workspace">—</span></div>
    <div class="row"><span>On standby</span>
      <span class="v" id="wp-standby-count">—</span></div>
    <div class="pills" id="wp-pills"></div>
    <div class="foot">The squad evaluates every H4 close (~4 h cadence). Most bars pass
      silently — a real proposal only appears when a character finds a clean setup.</div>
  </div>
  <div id="workspace-panel" class="card" role="region"
       aria-label="Squad workspace — recent thoughts" style="display:none">
    <h3 style="margin:0 0 8px;font-size:14px">Workspace — what the squad is thinking
      <span class="dim" style="font-size:11.5px;font-weight:400">
        · latest H4 close, newest first</span></h3>
    <div class="meta">
      <span id="workspace-meta">—</span>
      <button type="button" id="workspace-toggle" style="display:none">
        show all N thoughts</button>
    </div>
    <div class="thought-grid" id="workspace-grid"></div>
    <div id="workspace-empty" style="display:none">
      The squad hasn't published any thoughts yet. Wait for the next
      H4 close at <span id="workspace-next-hh">—</span> UTC.
    </div>
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
  <div class="card" id="ticker-card"><h2 style="margin:0 0 8px;font-size:15px">Match ticker <span class="dim" style="font-size:11px">click a row for detail</span></h2><div class="tkr" id="ticker"></div></div>
  <div class="card" id="league-card"><h2 style="margin:0 0 8px;font-size:15px">League table (this match)</h2>
    <table id="league"><tr><th>Player</th><th>Props</th><th>Blocked</th><th>Trades</th><th>Goals</th><th>Win%</th><th>Pips</th><th>TQS</th></tr></table></div>
  <!-- F020: latest match report teaser. Fill is fail-quiet: if the
       highlights API is unreachable the static link still works. -->
  <a class="card" id="highlights-teaser" href="/highlights"
     style="display:block;color:var(--fg);text-decoration:none">
    <h2 style="margin:0 0 6px;font-size:15px">Latest match report</h2>
    <div class="dim" id="highlights-teaser-line" style="font-size:12.5px">
      Yesterday retold as a match report &mdash; every line from the
      recorded tape. Read it on the Highlights page &rarr;</div>
  </a>
  <!-- Upcoming USD events (LIVE mode only): Sae's hunting calendar.
       Rows tagged "sae window" when now falls inside [T-30m, T+60m]. -->
  <div class="card" id="events-card" style="display:none">
    <h2 style="margin:0 0 4px;font-size:15px">Upcoming USD events
      <span class="dim" style="font-size:11px">high-impact · this week only</span></h2>
    <div class="dim" id="events-meta" style="font-size:11.5px;margin-bottom:6px">—</div>
    <div id="events-list"></div>
    <div id="events-empty" style="display:none;padding:12px 4px;text-align:center;
         color:var(--dim);font-size:12.5px;font-style:italic">
      No high-impact USD events left this week. The ForexFactory feed only
      covers the current week — the list refills after the weekly rollover.
    </div>
  </div>
</div>
</div>
<div class="gflash" id="gflash">GOAL!</div>
<div id="overlay"><div id="modal"><button class="x" id="mclose">&times;</button><div id="mbody"></div></div></div>
<div id="info-popover" class="popover tooltip-panel" role="dialog" aria-labelledby="info-popover-title">
  <button class="close" id="info-popover-close" aria-label="Close">&times;</button>
  <div id="info-popover-body"></div>
  <div class="foot">See the <a href="/#glossary">[glossary]</a> on the hub for every jargon term.</div>
</div>
<div id="player-tooltip" class="player-tooltip tooltip-panel" aria-hidden="true"></div>
<div id="tour-shade" aria-hidden="true"></div>
<div id="tour-tooltip" role="dialog" aria-live="polite">
  <div class="step-meta" id="tour-step-meta">Step 1 / 6</div>
  <h4 id="tour-title">—</h4>
  <div id="tour-body">—</div>
  <div class="actions">
    <button id="tour-back">Back</button>
    <button class="primary" id="tour-next">Next</button>
    <button class="skip" id="tour-skip">Skip tour</button>
  </div>
</div>
<script>
const NS="http://www.w3.org/2000/svg";
let roster={}, events=[], filtered=[], pos=0, playing=false, timer=null, goals=0, misses=0;
let matchId=null, summaryData=null, liveTimer=null, livePolling=false;
let currentMode=null, waitingTimer=null, tourStep=0, tourActive=false;
let ribbonAutoHideTimer=null;

// Plain-English labels for the mode picker. Keyed by the option `value`
// used in the <select> — replay values are the m.label from
// /api/v2/matches (e.g. "g7retry1-phi41"), plus the "__live__" sentinel.
// The internal wire ids (m.id = "g7_replay_cache_g7retry1-phi41") stay
// unchanged; this map ONLY controls display copy.
const MODE_LABELS = {
  "__live__": {
    display: "\uD83D\uDD34 LIVE — Today's market",
    subtitle: "Real MT5 bars, no orders sent",
    kind: "live",
  },
  "g7retry1-phi41": {
    display: "\uD83D\uDCFC Historical replay · Single-shot rule",
    subtitle: "2015-2019 walk-forward, one shot per pair per bar. Conservative — this is the G7-verdict arm.",
    kind: "replay",
  },
  "g7retry1-arm4": {
    display: "\uD83D\uDCFC Historical replay · Twin-strike rule",
    subtitle: "Same period; up to two shots per pair per bar. More aggressive — companion arm to the G7-verdict.",
    kind: "replay",
  },
};
function modeInfo(key){
  if(key && MODE_LABELS[key]) return MODE_LABELS[key];
  // Future aggregators: any g7retry1-<tail> label we haven't hard-coded
  // gets a synthesised historical-replay label so the picker never
  // shows a raw jargon id.
  const m = String(key||"").match(/^g7retry1-(.+)$/);
  if(m) return {
    display: "\uD83D\uDCFC Historical replay · " + m[1],
    subtitle: "Aggregator: " + m[1] + " (walk-forward replay).",
    kind: "replay",
  };
  return {display: String(key||"?"), subtitle: "", kind: "replay"};
}

// 2-3 sentence popover copy per mode. Keyed the same way as MODE_LABELS.
const MODE_HELP = {
  "__live__": "This is real-time. The squad is watching live MT5 bars and evaluating every H4 close (every 4 hours). Because setups are picky, most bars pass silently — you'll see a subtle <code>\u22EF tick_summary</code> row for each bar the squad observed. Real proposals appear only when a character finds a clean setup.",
  "g7retry1-phi41": "This replay shows how the squad performed over ~4 years of walk-forward when we picked the single highest-conviction character's proposal on each bar. This is the arm that carries the current G7 verdict.",
  "g7retry1-arm4": "Same replay period, but the aggregator allows up to two characters to shoot on the same bar. More trades, more risk exposure. Compare its league table with the single-shot rule to see how the aggregator choice matters.",
};
function modeHelp(key){
  if(key && MODE_HELP[key]) return MODE_HELP[key];
  const m = String(key||"").match(/^g7retry1-(.+)$/);
  if(m) return "Historical replay using the <code>" + esc(m[1]) +
    "</code> aggregator. See <a href=\"/#glossary\">the glossary</a> for aggregator definitions.";
  return "No description available for this mode.";
}

// Mode-aware subtitle. Rendered as HTML (has <code>/<strong>).
const MODE_SUBTITLE = {
  live: "Reading live MT5 bars in real time. The squad evaluates every H4 close (~4 h cadence) but only proposes on clean setups. Silent bars appear as subtle <code>\u22EF tick_summary</code> rows below. <strong>Nothing here is trading real money</strong> — shadow paper only.",
  replay: "Walk-forward replay played as a match: passes are proposals, tackles are aggregator rejections, the wall is Sentinel, goals are winning trades. Click a player for their profile; click a ticker row for the full event payload.",
};

// Character playstyles (from agent/squad/agents/a0X_*.py `playstyle`
// attribute) and default subscribed symbols (from agent/squad/roster.py
// DEFAULT_SYMBOLS + agent-specific overrides). Static because the hover
// tooltip is a display-only affordance — the source of truth stays in
// the Python roster.
const PLAYER_INFO = {
  "isagi_yoichi":   {playstyle:"conservative_metavision", symbols:["EURUSD","GBPUSD","USDCAD"]},
  "bachira_meguru": {playstyle:"rebel_tight",             symbols:["EURUSD","GBPUSD","USDCAD"]},
  "itoshi_rin":     {playstyle:"analytical_precision",    symbols:["EURUSD"]},
  "chigiri_hyoma":  {playstyle:"speed_momentum",          symbols:["EURUSD","GBPUSD"]},
  "reo_mikage":     {playstyle:"copier_hrp",              symbols:["EURUSD","GBPUSD","USDCAD"]},
  "nagi_seishiro":  {playstyle:"confluence_only",         symbols:["EURUSD","GBPUSD","USDCAD"]},
  "barou_shoei":    {playstyle:"solo_king",               symbols:["USDCAD"]},
};

// Guided tour steps. Kept short (5-6 total per spec) — each targets a
// selector already in the DOM and describes the element in plain English.
const TOUR_STEPS = [
  {sel:"#match", title:"Mode picker",
   body:"This is where you choose what to watch — live squad activity, or a historical replay of how the squad performed over past years."},
  {sel:"#mode-info-btn", title:"Info button",
   body:"Not sure what a mode means? Click here for a plain-English explanation of the current one."},
  {sel:"#pitch", title:"The pitch",
   body:"Every character is one of the 7 squad members. Hover a circle to see their playstyle and stats."},
  {sel:"#ticker-card", title:"Match ticker",
   body:"Every proposal, tackle, and shot appears here in order. Grey <code>\u22EF tick_summary</code> rows show the squad watching quietly between real events."},
  {sel:"#league-card", title:"League table",
   body:"How each character has performed in this match. Bachira usually leads — he's the volume proposer."},
  {sel:"#speed", title:"Playback speed",
   body:"For historical replays, this controls playback speed. LIVE mode ignores it since events arrive in real time."},
];

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
    pg.addEventListener("mouseenter",(e)=>showPlayerTooltip(aid, e));
    pg.addEventListener("mousemove",(e)=>positionPlayerTooltip(e));
    pg.addEventListener("mouseleave",hidePlayerTooltip);
    svg.appendChild(pg);
  }
  // Re-apply Sae's benched state after any redraw (redraws rebuild the
  // player groups, wiping the class applySaeState toggled last poll).
  applySaeState(saeEnabled);
}
// null = unknown (replay mode / status not resolved yet). Only an
// explicit false from live_status dims Sae -- the Phase AE gate made
// visible instead of a silently static striker.
let saeEnabled = null;
function applySaeState(enabled){
  saeEnabled = (enabled === undefined) ? null : enabled;
  const pg = document.getElementById("pl_sae_itoshi");
  if(!pg) return;
  const off = (matchId === "__live__" && saeEnabled === false);
  pg.classList.toggle("player-off", off);
  const labels = pg.querySelectorAll("text");
  const nm = labels[labels.length - 1];
  if(nm) nm.textContent = off ? "Sae (off)"
    : ((roster.sae_itoshi || {name: "Sae"}).name);
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
    // attribution), respects the hidesilent checkbox. In replay mode
    // a click opens the workspace panel with THIS tick's top-5 thoughts
    // (LIVE mode ignores the click -- its panel is already refreshing
    // on the 15 s cadence).
    const div=document.createElement("div");
    div.className="tk tick-summary";
    if(document.getElementById("hidesilent") &&
       document.getElementById("hidesilent").checked) div.classList.add("hidden");
    div.innerHTML=`<span class="t">${esc((ev.t||"").slice(0,16))}</span>`+
      `<span class="who">tick</span><span>${esc(tickMsg(ev))}</span>`;
    if(Array.isArray(ev.thoughts_top5) && ev.thoughts_top5.length){
      div.style.cursor = "pointer";
      div.addEventListener("click", () => {
        const info = modeInfo(currentMode);
        if(info.kind === "live") return;
        renderWorkspaceFromTop5(ev);
      });
    }
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
    // Wrap the ● glyph in .live-dot when running so it inherits the
    // header badge's shared pulse animation; idle states drop the
    // glyph entirely so a dead stream can't look alive.
    if(isMarket){
      b.innerHTML = running
        ? '<span class="live-dot">\u25CF</span> LIVE — market paper (shadow-only)'
        : 'LIVE — market stream idle';
    } else if(isCache){
      b.innerHTML = running
        ? '<span class="live-dot">\u25CF</span> LIVE — cache paper (shadow-only)'
        : 'LIVE — cache stream idle';
    } else {
      b.innerHTML = running
        ? '<span class="live-dot">\u25CF</span> LIVE — paper stream (shadow-only)'
        : 'LIVE — stream idle';
    }
  }
  else { b.className="badge sim"; b.innerText="sim-only — not trading real lots"; }
}

function updateModeUI(key){
  // Repaint the mode-scoped surfaces (subtitle, badge kind, waiting
  // panel visibility). Called when the user changes the picker or
  // whenever events cross the "waiting" threshold.
  currentMode = key;
  const info = modeInfo(key);
  const sub = document.getElementById("v2-subtitle");
  if(sub) sub.innerHTML = info.kind === "live"
    ? MODE_SUBTITLE.live : MODE_SUBTITLE.replay;
  // Base badge state; the LIVE polling path overwrites this with
  // running/source detail once /api/v2/live/status resolves.
  if(info.kind !== "live") setModeBadge(false);
  // Swap the transport row: Play + speed dropdown are meaningless on
  // LIVE (real-time, no seek), so hide them and show the connection
  // pill instead. Replay mode is the inverse.
  const transport = document.getElementById("replay-transport");
  const conn = document.getElementById("live-connection");
  if(info.kind === "live"){
    if(transport) transport.classList.add("hidden");
    if(conn) conn.classList.add("open");
    updateLiveEventCount();
  } else {
    if(transport) transport.classList.remove("hidden");
    if(conn) conn.classList.remove("open");
  }
  refreshWaitingPanel();
  // Workspace panel is LIVE-first: fetch immediately, then let the
  // poll cadence keep it fresh. Replay mode leaves it hidden until
  // the user clicks a tick_summary row.
  if(info.kind === "live") refreshLiveWorkspace();
  else hideWorkspacePanel();
}

function updateLiveEventCount(){
  const el = document.getElementById("live-event-count");
  if(el) el.innerText = String(events.length);
}

// ---------------------------------------------------------------------
// Item 5: "waiting on the market" empty-state panel (live mode only,
// <10 events). Countdown updates every 30 s; pill list refreshes when
// new events land via pollLive.
// ---------------------------------------------------------------------
function nextH4CloseMs(){
  const now = new Date();
  const hUtc = now.getUTCHours();
  const nextH = (Math.floor(hUtc/4) + 1) * 4;
  const y = now.getUTCFullYear(), m = now.getUTCMonth(), d = now.getUTCDate();
  if(nextH >= 24) return Date.UTC(y, m, d + 1, 0, 0, 0);
  return Date.UTC(y, m, d, nextH, 0, 0);
}
function fmtCountdown(ms){
  if(ms <= 0) return "any moment";
  const totalSec = Math.max(0, Math.round(ms / 1000));
  // Under a minute: seconds only, so the last stretch reads as a real
  // ticker. Otherwise h/m/s in the usual grouping.
  if(totalSec < 60) return "in " + totalSec + " s";
  const s = totalSec % 60;
  const totalMin = Math.floor(totalSec / 60);
  const h = Math.floor(totalMin / 60);
  const mn = totalMin % 60;
  if(h === 0) return "in " + mn + " m " + s + " s";
  return "in " + h + " h " + mn + " m " + s + " s";
}
function refreshWaitingPanel(){
  const el = document.getElementById("waiting-panel");
  if(!el) return;
  const info = modeInfo(currentMode);
  const shouldShow = (info.kind === "live") && (events.length < 10);
  if(!shouldShow){
    el.classList.remove("open");
    if(waitingTimer){ clearInterval(waitingTimer); waitingTimer = null; }
    return;
  }
  el.classList.add("open");
  el.classList.add("fade-in");
  renderWaitingContents();
  if(!waitingTimer){
    // 1 s cadence so the last-minute countdown reads as a real ticker.
    waitingTimer = setInterval(renderWaitingContents, 1_000);
  }
}
function renderWaitingContents(){
  const el = document.getElementById("waiting-panel");
  if(!el || !el.classList.contains("open")) return;
  const closeMs = nextH4CloseMs();
  const dt = new Date(closeMs);
  const hh = String(dt.getUTCHours()).padStart(2, "0");
  document.getElementById("wp-next").innerText =
    hh + ":00 UTC · " + fmtCountdown(closeMs - Date.now());
  // Latest tick_summary provides workspace count.
  let latestTick = null;
  for(let i = events.length - 1; i >= 0; i--){
    if(events[i].type === "tick_summary"){ latestTick = events[i]; break; }
  }
  const wsEl = document.getElementById("wp-workspace");
  if(latestTick){
    const n = latestTick.workspace_thought_count || 0;
    wsEl.innerText = n + " thought" + (n===1?"":"s") + " in workspace right now";
  } else {
    wsEl.innerText = "waiting for the first tick";
  }
  // Standby pills = union of players_evaluated across recent ticks.
  // Fall back to the roster if we've seen no tick_summary yet, so a
  // fresh page load isn't blank.
  const seen = new Set();
  for(const ev of events){
    if(ev.type === "tick_summary"){
      for(const p of (ev.players_evaluated || [])) seen.add(p);
    }
  }
  let ids = Array.from(seen);
  if(!ids.length) ids = Object.keys(roster || {}).filter(k =>
    (roster[k].role || "").indexOf("Sentinel") < 0);
  const pillsEl = document.getElementById("wp-pills");
  pillsEl.innerHTML = ids.map(aid => {
    const r = (roster && roster[aid]) || {name: aid, color: "#8b949e"};
    return '<span class="pill"><span class="dot" style="background:'+r.color+
      '"></span>'+esc(r.name)+'</span>';
  }).join("");
  document.getElementById("wp-standby-count").innerText =
    ids.length + " character" + (ids.length===1?"":"s");
}

// ---------------------------------------------------------------------
// Item 3: info popover (position:fixed near the info button, close on
// outside-click or Esc, pointer-events on the underlying pitch stay live).
// ---------------------------------------------------------------------
function openInfoPopover(){
  const btn = document.getElementById("mode-info-btn");
  const pop = document.getElementById("info-popover");
  if(!btn || !pop) return;
  const info = modeInfo(currentMode);
  document.getElementById("info-popover-body").innerHTML =
    "<b>" + esc(info.display) + "</b><p style=\"margin:6px 0 0\">" +
    modeHelp(currentMode) + "</p>";
  pop.classList.add("open");
  const r = btn.getBoundingClientRect();
  // Prefer below-right of the button; flip above if we'd overflow.
  const vw = window.innerWidth, vh = window.innerHeight;
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = r.left, top = r.bottom + 8;
  if(left + pw > vw - 8) left = Math.max(8, vw - pw - 8);
  if(top + ph > vh - 8) top = Math.max(8, r.top - ph - 8);
  pop.style.left = left + "px";
  pop.style.top = top + "px";
}
function closeInfoPopover(){
  const pop = document.getElementById("info-popover");
  if(pop) pop.classList.remove("open");
}

// ---------------------------------------------------------------------
// Item 6: player hover tooltip. Uses position:fixed so it doesn't clip
// the SVG viewBox; positioned from the cursor with edge-flipping.
// ---------------------------------------------------------------------
function showPlayerTooltip(aid, evt){
  const tip = document.getElementById("player-tooltip");
  if(!tip) return;
  const r = roster[aid] || {name: aid, color: "#8b949e"};
  const info = PLAYER_INFO[aid] || {playstyle: "?", symbols: []};
  const stats = (summaryData && summaryData.per_agent
                 && summaryData.per_agent[aid]) || null;
  let record = "no trades in this match yet";
  if(stats){
    record = stats.proposals + " proposal" + (stats.proposals===1?"":"s") +
      " · " + stats.trades + " trade" + (stats.trades===1?"":"s") +
      " · " + stats.goals + " goal" + (stats.goals===1?"":"s");
  }
  tip.innerHTML =
    '<div class="n" style="color:'+r.color+'">'+esc(r.name)+'</div>'+
    '<div class="p">'+esc(info.playstyle)+'</div>'+
    '<div class="s">'+esc(info.symbols.join(" · "))+'</div>'+
    '<div class="r">'+esc(record)+'</div>';
  tip.classList.add("open");
  positionPlayerTooltip(evt);
}
function positionPlayerTooltip(evt){
  const tip = document.getElementById("player-tooltip");
  if(!tip || !tip.classList.contains("open")) return;
  const pad = 12;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  const vw = window.innerWidth, vh = window.innerHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if(x + w > vw - 8) x = evt.clientX - w - pad;
  if(y + h > vh - 8) y = evt.clientY - h - pad;
  tip.style.left = Math.max(4, x) + "px";
  tip.style.top = Math.max(4, y) + "px";
}
function hidePlayerTooltip(){
  const tip = document.getElementById("player-tooltip");
  if(tip) tip.classList.remove("open");
}

// ---------------------------------------------------------------------
// Item 7: first-visit ribbon. localStorage 'v2_visited' prevents it
// showing again after dismiss or 60 s idle expiry.
// ---------------------------------------------------------------------
function initRibbon(){
  const r = document.getElementById("v2-ribbon");
  if(!r) return;
  let visited = false;
  try{ visited = localStorage.getItem("v2_visited") === "true"; }catch(e){}
  if(visited) return;
  r.classList.add("open");
  ribbonAutoHideTimer = setTimeout(dismissRibbon, 60_000);
  document.getElementById("ribbon-dismiss").onclick = dismissRibbon;
  document.getElementById("ribbon-tour").onclick = ()=>{
    dismissRibbon(); startTour(0);
  };
}
function dismissRibbon(){
  const r = document.getElementById("v2-ribbon");
  if(!r) return;
  r.classList.remove("open");
  try{ localStorage.setItem("v2_visited", "true"); }catch(e){}
  if(ribbonAutoHideTimer){ clearTimeout(ribbonAutoHideTimer);
    ribbonAutoHideTimer = null; }
}

// ---------------------------------------------------------------------
// Item 8: guided tour overlay. Progress state is JS-memory only —
// running the tour twice is fine. Escape / shade click both exit.
// ---------------------------------------------------------------------
function startTour(step){
  tourActive = true;
  tourStep = step || 0;
  document.getElementById("tour-shade").classList.add("open");
  renderTourStep();
}
function renderTourStep(){
  clearTourSpotlight();
  const s = TOUR_STEPS[tourStep];
  if(!s){ exitTour(); return; }
  const target = document.querySelector(s.sel);
  if(!target){
    // Target not in DOM — skip forward rather than trap the user.
    tourStep++; renderTourStep(); return;
  }
  target.classList.add("tour-spotlight");
  // Scroll into view if needed, then position the tooltip.
  const r = target.getBoundingClientRect();
  if(r.top < 20 || r.bottom > window.innerHeight - 20){
    target.scrollIntoView({behavior:"smooth", block:"center"});
  }
  const tip = document.getElementById("tour-tooltip");
  tip.classList.add("open");
  document.getElementById("tour-step-meta").innerText =
    "Step " + (tourStep+1) + " / " + TOUR_STEPS.length;
  document.getElementById("tour-title").innerText = s.title;
  document.getElementById("tour-body").innerHTML = s.body;
  document.getElementById("tour-back").disabled = (tourStep === 0);
  document.getElementById("tour-next").innerText =
    (tourStep === TOUR_STEPS.length - 1) ? "Done" : "Next";
  // Position tooltip: prefer below, fall back to above / side if needed.
  setTimeout(()=>positionTourTooltip(target), 20);
}
function positionTourTooltip(target){
  const tip = document.getElementById("tour-tooltip");
  const r = target.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  const pad = 14;
  let top = r.bottom + pad, left = r.left;
  if(top + th > vh - 8) top = Math.max(8, r.top - th - pad);
  if(top < 8) top = 8;
  if(left + tw > vw - 8) left = Math.max(8, vw - tw - 8);
  if(left < 8) left = 8;
  tip.style.top = top + "px";
  tip.style.left = left + "px";
}
function clearTourSpotlight(){
  document.querySelectorAll(".tour-spotlight").forEach(n =>
    n.classList.remove("tour-spotlight"));
}
function advanceTour(delta){
  const next = tourStep + delta;
  if(next < 0) return;
  if(next >= TOUR_STEPS.length){ exitTour(); return; }
  tourStep = next; renderTourStep();
}
function exitTour(){
  tourActive = false;
  clearTourSpotlight();
  document.getElementById("tour-shade").classList.remove("open");
  document.getElementById("tour-tooltip").classList.remove("open");
}
// ---------------------------------------------------------------------
// Workspace panel — "what the squad is thinking" (Fix 1).
// LIVE mode: fetch every 15 s from /api/v2/live/workspace (real-time
// snapshot). Replay mode: user clicks a tick_summary row -> renderFromTop5
// paints the top-5 thoughts captured in that tick's event row.
// ---------------------------------------------------------------------
let workspaceTimer = null;
let workspaceShowAll = false;
const WORKSPACE_DISPLAY_LIMIT = 14;
function hideWorkspacePanel(){
  const p = document.getElementById("workspace-panel");
  if(p) p.style.display = "none";
  if(workspaceTimer){ clearInterval(workspaceTimer); workspaceTimer = null; }
}
function showWorkspacePanel(){
  const p = document.getElementById("workspace-panel");
  if(!p) return;
  const was = p.style.display;
  p.style.display = "block";
  // Fade-in only on the first show, not on every refresh.
  if(was === "none"){
    p.classList.remove("fade-in");
    void p.offsetWidth;
    p.classList.add("fade-in");
  }
}
async function refreshLiveWorkspace(){
  const info = modeInfo(currentMode);
  if(info.kind !== "live"){
    hideWorkspacePanel();
    return;
  }
  showWorkspacePanel();
  let ws = null;
  try{ ws = await (await fetch("/api/v2/live/workspace")).json(); }
  catch(e){ ws = {exists:false, thoughts:[]}; }
  renderWorkspace(ws || {exists:false, thoughts:[]},
                   {source:"live", asOf: ws && ws.as_of, tickId: ws && ws.tick_id});
  // Poll every 15 s while LIVE is the active mode.
  if(!workspaceTimer){
    workspaceTimer = setInterval(refreshLiveWorkspace, 15_000);
  }
}
function renderWorkspaceFromTop5(ev){
  // Replay-mode entry point: a tick_summary row exposes at most 5
  // thoughts captured at emit time. Fewer fields than LIVE (compact
  // {agent_id, symbol, narrative, confidence}) so the card degrades
  // gracefully with narrative-only content.
  showWorkspacePanel();
  const thoughts = (ev && Array.isArray(ev.thoughts_top5))
    ? ev.thoughts_top5 : [];
  renderWorkspace({exists:true, thoughts_top5:true, thoughts},
                  {source:"tick_summary", asOf: ev && ev.t,
                   tickId: ev && ev.tick_id});
}
function renderWorkspace(ws, meta){
  const grid = document.getElementById("workspace-grid");
  const empty = document.getElementById("workspace-empty");
  const metaEl = document.getElementById("workspace-meta");
  const toggle = document.getElementById("workspace-toggle");
  if(!grid || !empty || !metaEl) return;
  const thoughts = (ws && Array.isArray(ws.thoughts)) ? ws.thoughts : [];
  // Sort: timestamp desc, agent_id asc. Engine already does this for
  // the LIVE snapshot; tick_summary top-5 arrives confidence-sorted,
  // so re-sort here for a single consistent presentation.
  thoughts.sort((a,b) => {
    const ta = new Date(a.timestamp || meta.asOf || 0).getTime();
    const tb = new Date(b.timestamp || meta.asOf || 0).getTime();
    if(tb !== ta) return tb - ta;
    return String(a.agent_id||"").localeCompare(String(b.agent_id||""));
  });
  // Group visually by agent: keep the (ts desc) primary order but
  // adjacent-cluster same-agent cards so hover / scan reads as a
  // per-character stack rather than a shuffled feed.
  const perAgent = {};
  const agentOrder = [];
  for(const t of thoughts){
    const aid = t.agent_id || "?";
    if(!(aid in perAgent)){ perAgent[aid] = []; agentOrder.push(aid); }
    perAgent[aid].push(t);
  }
  const ordered = [];
  for(const aid of agentOrder) for(const t of perAgent[aid]) ordered.push(t);
  const limit = workspaceShowAll ? ordered.length : WORKSPACE_DISPLAY_LIMIT;
  const shown = ordered.slice(0, limit);
  if(!thoughts.length){
    grid.innerHTML = "";
    empty.style.display = "block";
    const dt = new Date(nextH4CloseMs());
    const hh = String(dt.getUTCHours()).padStart(2, "0");
    const nn = document.getElementById("workspace-next-hh");
    if(nn) nn.innerText = hh + ":00";
    metaEl.innerText = "0 thoughts";
    if(toggle) toggle.style.display = "none";
    return;
  }
  empty.style.display = "none";
  grid.innerHTML = shown.map(t => workspaceCardHtml(t)).join("");
  // Meta line: source + count + tick id.
  const total = (ws && typeof ws.thought_count === "number")
    ? ws.thought_count : thoughts.length;
  const src = meta.source === "tick_summary"
    ? "from tick #" + (meta.tickId || "?") + " · " + (meta.asOf||"").slice(0,16)
    : "as of " + (meta.asOf ? String(meta.asOf).slice(11,19) + " UTC" : "—");
  metaEl.innerText = "Showing " + shown.length + " of " + total +
    " thought" + (total===1?"":"s") + " · " + src;
  if(toggle){
    if(ordered.length > WORKSPACE_DISPLAY_LIMIT){
      toggle.style.display = "inline-block";
      toggle.innerText = workspaceShowAll
        ? "show fewer"
        : ("show all " + ordered.length + " thoughts");
    } else {
      toggle.style.display = "none";
    }
  }
}
function workspaceCardHtml(t){
  const aid = t.agent_id || "?";
  const r = roster[aid] || {name: aid, color: "#8b949e"};
  const conf = (typeof t.confidence === "number") ? t.confidence
             : (typeof t.confidence_in_thought === "number")
               ? t.confidence_in_thought : null;
  const confPct = conf==null ? 0 : Math.max(0, Math.min(1, conf)) * 100;
  const confTxt = conf==null ? "?" : conf.toFixed(2);
  const tags = Array.isArray(t.tags) ? t.tags : [];
  const read = t.read || null;
  const exp = t.expected_action || null;
  const dir = read ? read.direction_bias : null;
  const stopPips = read ? read.expected_stop_pips : null;
  const dirClass = dir === "long" ? "dir-long"
                 : dir === "short" ? "dir-short" : "";
  let foot = "";
  if(exp || dir || stopPips != null){
    const parts = [];
    if(exp) parts.push('<span class="k">expected</span> <span class="v">'+esc(exp)+'</span>');
    if(dir) parts.push('<span class="k">dir</span> <span class="v dir">'+esc(String(dir).toUpperCase())+'</span>');
    if(stopPips != null) parts.push('<span class="k">stop</span> <span class="v">'+esc(Math.round(stopPips*10)/10)+' pips</span>');
    foot = '<div class="foot">'+parts.join("")+'</div>';
  }
  const narrative = t.narrative || "";
  const shortSym = t.symbol || "";
  const tagsHtml = tags.length
    ? '<div class="tags">'+tags.map(x =>
        '<span class="tag">'+esc(x)+'</span>').join("")+'</div>'
    : "";
  return '<div class="thought-card '+dirClass+'">'+
    '<div class="hd">'+
      '<span class="dot" style="background:'+r.color+'"></span>'+
      '<span class="nm" style="color:'+r.color+'">'+esc(r.name)+'</span>'+
      '<span class="sym">'+esc(shortSym)+'</span>'+
      '<span class="conf">conf '+esc(confTxt)+'</span>'+
    '</div>'+
    '<div class="narrative">'+esc(narrative)+'</div>'+
    '<div class="conf-bar"><span style="width:'+confPct.toFixed(0)+'%"></span></div>'+
    tagsHtml+foot+
  '</div>';
}

function stopLive(){
  if(liveTimer){clearInterval(liveTimer); liveTimer=null;}
  if(workspaceTimer){clearInterval(workspaceTimer); workspaceTimer=null;}
  if(statusTimer){clearInterval(statusTimer); statusTimer=null;}
  if(eventsTimer){clearInterval(eventsTimer); eventsTimer=null;}
  const ql=document.getElementById("quiet-line"); if(ql) ql.style.display="none";
  const ec=document.getElementById("events-card"); if(ec) ec.style.display="none";
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
  // For the label-key convention (see MODE_LABELS), we strip the
  // g7_replay_cache_ prefix — this is the same transform list_matches
  // does server-side to produce m.label.
  const modeKey = String(id).replace(/^g7_replay_cache_/, "");
  updateModeUI(modeKey);
  const s=await (await fetch(`/api/v2/match/${id}/summary`)).json();
  summaryData=s; roster=s.roster||{}; drawPitch(); renderLeague(s);
  events=await fetchAllEvents(`/api/v2/match/${id}`);
  populateFilterOptions(); applyFilters();
  document.getElementById("clock").innerText=`ready · ${events.length} events`;
}

async function loadLive(){
  stopLive(); setPlaying(false); events=[]; matchId="__live__";
  updateModeUI("__live__");
  document.getElementById("clock").innerText="connecting to live stream…";
  let s;
  try{ s=await (await fetch("/api/v2/live/summary")).json(); }
  catch(e){ s=null; }
  if(!s || s.error){
    document.getElementById("clock").innerText="live dir not found — start the paper loop first";
    setModeBadge(true,false); drawPitch();
    // Show the waiting panel even with no roster so newcomers see
    // the "next H4 close" affordance immediately.
    refreshWaitingPanel();
    return;
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
  refreshUpcomingEvents();
  // quiet_reason / warm-up need their own cadence: event batches are
  // hours apart on H4, so piggybacking on pollLive would go stale.
  if(!statusTimer) statusTimer=setInterval(pollLiveStatus, 15_000);
  if(!eventsTimer) eventsTimer=setInterval(refreshUpcomingEvents, 60_000);
  document.getElementById("clock").innerText=
    `LIVE · ${events.length} events so far`;
  refreshWaitingPanel();
}
async function pollLiveStatus(){
  try{ const st=await (await fetch("/api/v2/live/status")).json();
    setModeBadge(true, !!st.running, st.source);
    renderQuietLine(st); applySaeState(st.sae_enabled); }
  catch(e){ setModeBadge(true,false,null); renderQuietLine(null); }
}
// ---------------------------------------------------------------------
// I002 "why quiet" surfaces (2026-07-24). LIVE mode only: a status line
// under the badge fed by live_status().quiet_reason, and an upcoming
// USD-events panel fed by /api/v2/live/upcoming_events. Both degrade
// to honest text when their API is unreachable.
// ---------------------------------------------------------------------
let statusTimer=null, eventsTimer=null;
function renderQuietLine(st){
  const line=document.getElementById("quiet-line");
  const span=document.getElementById("quiet-reason");
  if(!line || !span) return;
  if(matchId!=="__live__"){ line.style.display="none"; return; }
  line.style.display="inline-block";
  if(!st){ span.innerText="status endpoint unreachable"; return; }
  let txt = st.quiet_reason || "\u2014";
  // Compact per-symbol warm-up detail, unless it IS the headline.
  const w = st.warmup;
  if(w && !/^warming up/.test(txt)){
    const parts = Object.keys(w).sort().map(sym=>{
      const x = w[sym] || {};
      return sym+" "+(x.bars_seen ?? "?")+"/"+(x.warmup_bars ?? "?")+
        (x.burn_in_remaining ? (" \u00b7 burn-in "+x.burn_in_remaining) : "");
    });
    if(parts.length) txt += " \u00b7 warm-up: "+parts.join(", ");
  }
  if(st.sae_enabled===false) txt += " \u00b7 Sae benched (pre-reg gate)";
  if(st.calendar_fetched_age_seconds==null) txt += " \u00b7 calendar cache missing";
  span.innerText = txt;
}
function fmtAge(s){
  if(s < 90) return Math.round(s)+"s";
  if(s < 5400) return Math.round(s/60)+"m";
  return (s/3600).toFixed(1)+"h";
}
async function refreshUpcomingEvents(){
  const card=document.getElementById("events-card");
  if(!card) return;
  if(matchId!=="__live__"){ card.style.display="none"; return; }
  card.style.display="";
  let d=null;
  try{ d=await (await fetch("/api/v2/live/upcoming_events")).json(); }
  catch(e){ d=null; }
  const meta=document.getElementById("events-meta");
  const list=document.getElementById("events-list");
  const empty=document.getElementById("events-empty");
  if(!d || d.error){
    meta.innerText="calendar API unreachable";
    list.innerHTML=""; empty.style.display=""; return;
  }
  // Fetched-at age makes a dead feed visible: a healthy refresher keeps
  // this under the ~6 h TTL; hours beyond that means fetches are failing.
  meta.innerText = d.fetched_age_seconds==null
    ? "calendar cache missing \u2014 news fetch never succeeded"
    : "calendar fetched "+fmtAge(d.fetched_age_seconds)+" ago";
  const evs=d.events||[];
  if(!evs.length){ list.innerHTML=""; empty.style.display=""; return; }
  empty.style.display="none";
  list.innerHTML=evs.map(e=>{
    const mins=Number(e.minutes_to_event ?? 0);
    const cd=mins>=60 ? Math.floor(mins/60)+"h "+(mins%60)+"m" : mins+"m";
    return '<div class="evrow">'+
      '<span class="when">'+esc(String(e.time_utc||"").slice(5,16).replace("T"," "))+' UTC</span>'+
      '<span class="ttl" title="'+esc(e.title)+'">'+esc(e.title)+'</span>'+
      (e.in_sae_window ? '<span class="sae-tag">sae window</span>' : "")+
      '<span class="cd">in '+esc(cd)+'</span>'+
    '</div>';
  }).join("");
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
  if(d.events.length){
    pollLiveStatus();
    // Waiting-panel visibility depends on events.length crossing 10;
    // recheck on every batch so the fade-out fires as soon as we have
    // enough real activity.
    refreshWaitingPanel();
  }
  // The live-connection pill's "N events since reset" counter tracks
  // events.length regardless of whether this batch was empty, so an
  // empty poll still confirms the count on-screen matches reality.
  updateLiveEventCount();
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
    const o=document.createElement("option");
    o.value=m.id;
    o.textContent=modeInfo(m.label).display;
    o.title=modeInfo(m.label).subtitle;
    sel.appendChild(o);
  }
  if(liveAvailable){
    const o=document.createElement("option");
    o.value="__live__";
    o.textContent=MODE_LABELS["__live__"].display;
    o.title=MODE_LABELS["__live__"].subtitle;
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

  // Info popover: toggle on click, close on outside-click / Esc.
  const infoBtn = document.getElementById("mode-info-btn");
  infoBtn.onclick = (e) => {
    e.stopPropagation();
    const pop = document.getElementById("info-popover");
    if(pop.classList.contains("open")) closeInfoPopover();
    else openInfoPopover();
  };
  document.getElementById("info-popover-close").onclick = closeInfoPopover;
  document.addEventListener("click", (e) => {
    const pop = document.getElementById("info-popover");
    if(!pop.classList.contains("open")) return;
    if(e.target === infoBtn || infoBtn.contains(e.target)) return;
    if(pop.contains(e.target)) return;
    closeInfoPopover();
  });
  document.getElementById("info-popover").addEventListener("click",
    (e) => e.stopPropagation());

  // First-visit ribbon + always-on "Take the tour" affordance.
  initRibbon();
  document.getElementById("take-tour").onclick = (e) => {
    e.preventDefault();
    dismissRibbon(); startTour(0);
  };

  // Tour buttons + shade click + Escape.
  document.getElementById("tour-next").onclick = () => advanceTour(1);
  document.getElementById("tour-back").onclick = () => advanceTour(-1);
  document.getElementById("tour-skip").onclick = exitTour;
  document.getElementById("tour-shade").onclick = exitTour;

  // LIVE connection pill: manual refresh button re-runs the same fetch
  // as the 15 s auto-refresh (status + workspace snapshot + event tail).
  // 300 ms spin animation on click as a "yes, we heard you" tell.
  const liveRefresh = document.getElementById("live-refresh");
  if(liveRefresh){
    liveRefresh.onclick = () => {
      liveRefresh.classList.remove("spin-once");
      void liveRefresh.offsetWidth;
      liveRefresh.classList.add("spin-once");
      pollLiveStatus();
      refreshLiveWorkspace();
      if(livePolling) pollLive();
    };
  }
  // Workspace panel show-all toggle.
  const wsToggle = document.getElementById("workspace-toggle");
  if(wsToggle){
    wsToggle.onclick = () => {
      workspaceShowAll = !workspaceShowAll;
      // Re-render from the last fetched state; simplest is to trigger
      // the same fetch path (LIVE) or a no-op in replay -- the tick
      // summary click will re-populate anyway.
      const info = modeInfo(currentMode);
      if(info.kind === "live") refreshLiveWorkspace();
      // For replay the user has to re-click the tick_summary row to
      // see the toggle change; that's fine -- their previous selection
      // was already the whole payload (max 5 thoughts).
    };
  }
  document.addEventListener("keydown", (e) => {
    if(e.key !== "Escape") return;
    if(tourActive){ exitTour(); return; }
    const pop = document.getElementById("info-popover");
    if(pop && pop.classList.contains("open")) closeInfoPopover();
  });

  if(data.matches.length) await loadMatch(data.matches[0].id);
  else await loadLive();
}
init();
// F020: fill the highlights teaser with the newest report headline.
// Fail-quiet -- the static link copy stays if anything goes wrong.
(async () => {
  try {
    const r = await fetch("/api/highlights/reports?n=1", {cache:"no-store"});
    if(!r.ok) return;
    const d = await r.json();
    const first = d && d.reports && d.reports[0];
    if(first && first.headline){
      const el = document.getElementById("highlights-teaser-line");
      if(el) el.textContent = first.headline + " Read the full report \u2192";
    }
  } catch(e) { /* teaser stays static */ }
})();
</script></body></html>"""

V2_PAGE = (_V2_TEMPLATE
           .replace("__BASE_CSS__", _BASE_CSS)
           .replace("__NAV__", nav('v2')))


# ---------------------------------------------------------------------------
# /hq  -- Blue Lock Trading Co. dashboard
# ---------------------------------------------------------------------------
#
# Reads /api/hq/state (backed by company/ledger/company_state.json via
# agent.platform.hq.hq_state()) and renders a live company dashboard:
# header + KPI strip + sprint Kanban + role grid + decisions log +
# blockers panel + footer. Same raw-template + __PLACEHOLDER__ trick as
# _V2_TEMPLATE so the inline JS can use backticks / braces without
# f-string doubling; framework-free, no CDN, matches the platform's
# dark theme via _BASE_CSS tokens.
_HQ_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue Lock Trading Co. -- HQ</title><style>__BASE_CSS__
.hq-header{display:flex;justify-content:space-between;align-items:flex-start;
  gap:16px;flex-wrap:wrap;margin-bottom:18px}
.hq-header .hq-title h1{margin:0 0 4px;font-size:22px}
.hq-header .hq-title .mission{color:var(--dim);font-size:13.5px;
  max-width:720px;line-height:1.55}
.hq-header .hq-sprint{display:flex;flex-direction:column;align-items:flex-end;
  gap:6px;font-size:12.5px;color:var(--dim);font-variant-numeric:tabular-nums;
  min-width:180px}
.hq-header .hq-sprint .sprint-badge{background:rgba(188,140,255,.12);
  color:var(--purple);border:1px solid rgba(188,140,255,.4);
  padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;
  letter-spacing:.06em;text-transform:uppercase;white-space:nowrap}
.hq-header .hq-sprint .day-counter{font-variant-numeric:tabular-nums}
.wd-strip{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px}
.wd-chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;
  padding:3px 10px;border-radius:999px;border:1px solid var(--border);
  color:var(--dim);background:rgba(255,255,255,.02)}
.wd-chip::before{content:"";width:8px;height:8px;border-radius:50%;
  background:#556}
.wd-chip.wd-ok::before{background:#3fb950}
.wd-chip.wd-ok{color:#7ee2a8;border-color:rgba(63,185,80,.35)}
.wd-chip.wd-warn::before{background:#d29922}
.wd-chip.wd-warn{color:#e3b341;border-color:rgba(210,153,34,.45)}
.wd-chip.wd-alarm::before{background:#f85149}
.wd-chip.wd-alarm{color:#ff7b72;border-color:rgba(248,81,73,.5)}
.wd-chip.wd-na::before{background:#556}
.kpi-strip{display:grid;grid-template-columns:repeat(9,1fr);gap:10px;
  margin-bottom:20px}
@media (max-width: 1400px){.kpi-strip{grid-template-columns:repeat(6,1fr)}}
@media (max-width: 1100px){.kpi-strip{grid-template-columns:repeat(3,1fr)}}
@media (max-width: 700px){.kpi-strip{grid-template-columns:repeat(2,1fr)}}
.kpi-tile{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:12px 14px}
.kpi-tile.warn{border-color:var(--red)}
.kpi-tile .k{font-size:11px;color:var(--dim);text-transform:uppercase;
  letter-spacing:.05em;font-weight:600;margin-bottom:6px}
.kpi-tile .v{font-size:22px;font-variant-numeric:tabular-nums;color:var(--fg);
  font-weight:600;line-height:1}
.kpi-tile.warn .v{color:var(--red)}
.kpi-tile .foot{font-size:11px;color:var(--dim);margin-top:6px}
.section{margin-bottom:22px}
.section h2{margin:0 0 10px;font-size:15px;display:flex;align-items:baseline;
  gap:10px;flex-wrap:wrap}
.section h2 .aux{font-size:11.5px;color:var(--dim);font-weight:400}
.kanban{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
@media (max-width: 1100px){.kanban{grid-template-columns:repeat(2,1fr)}}
@media (max-width: 700px){.kanban{grid-template-columns:1fr}}
.kanban-col{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:12px;min-height:120px}
.kanban-col h3{margin:0 0 10px;font-size:11.5px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--dim);display:flex;justify-content:space-between;
  align-items:baseline}
.kanban-col h3 .count{color:var(--fg);font-weight:700;
  font-variant-numeric:tabular-nums}
.feature-card{background:#0d1117;border:1px solid var(--border);
  border-radius:8px;padding:10px 12px;margin-bottom:8px;font-size:12.5px}
.feature-card:last-child{margin-bottom:0}
.feature-card .title{font-weight:600;color:var(--fg);
  display:flex;justify-content:space-between;align-items:flex-start;gap:8px;
  margin-bottom:6px}
.feature-card .title .fid{color:var(--dim);font-size:11px;font-weight:500;
  font-variant-numeric:tabular-nums}
.feature-card .meta{color:var(--dim);font-size:11.5px;
  display:flex;flex-wrap:wrap;gap:8px 12px;align-items:baseline}
.feature-card .meta .owner{color:var(--fg)}
.prio{font-size:10px;font-weight:700;padding:1px 6px;border-radius:4px;
  letter-spacing:.04em;text-transform:uppercase;white-space:nowrap;
  vertical-align:middle}
.prio.p0{background:rgba(248,81,73,.15);color:var(--red);
  border:1px solid rgba(248,81,73,.4)}
.prio.p1{background:rgba(210,153,34,.15);color:var(--amber);
  border:1px solid rgba(210,153,34,.4)}
.prio.p2{background:rgba(139,148,158,.15);color:var(--dim);
  border:1px solid var(--border)}
.roles-tier{margin-bottom:16px}
.roles-tier h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--dim);font-weight:600}
.role-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:10px}
.role-tile{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:10px 12px;font-size:12.5px;
  display:flex;flex-direction:column;gap:4px;transition:opacity .2s}
.role-tile.idle{opacity:.3}
.role-tile .role-title{font-weight:600;color:var(--fg);
  display:flex;align-items:center;gap:8px}
.role-tile .status-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.role-tile .status-dot.active{background:var(--green);
  box-shadow:0 0 6px rgba(63,185,80,.6)}
.role-tile .status-dot.idle{background:var(--dim)}
.role-tile .persona{color:var(--purple);font-size:11.5px;font-style:italic}
.role-tile .task{color:var(--dim);font-size:11.5px;line-height:1.4;
  overflow:hidden;text-overflow:ellipsis;display:-webkit-box;
  -webkit-line-clamp:2;-webkit-box-orient:vertical}
.role-tile .throughput{color:var(--dim);font-size:11px;
  font-variant-numeric:tabular-nums;margin-top:2px}
.decisions-log{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:14px 16px}
.decisions-log .row{display:grid;
  grid-template-columns:max-content max-content 1fr;
  gap:10px;padding:6px 0;border-bottom:1px solid #1c2129;
  font-size:12.5px;align-items:baseline}
.decisions-log .row:last-child{border-bottom:none}
.decisions-log .row .date{color:var(--dim);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.decisions-log .row .role{color:var(--accent);font-weight:600;white-space:nowrap;
  font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.decisions-log .row .decision{color:var(--fg)}
.decisions-log .row .decision .did{color:var(--dim);font-size:11px;
  margin-right:6px;font-variant-numeric:tabular-nums}
.decisions-log .empty,.kanban-col .empty,.role-grid .empty{color:var(--dim);
  font-style:italic;font-size:12px;padding:4px 0}
.blockers{background:var(--panel);border:2px solid var(--red);
  border-radius:10px;padding:14px 16px}
.blockers.empty-state{border-color:var(--border);border-width:1px}
.blockers h2{margin:0 0 10px;color:var(--red);font-size:15px}
.blockers.empty-state h2{color:var(--fg)}
.blockers .row{display:grid;
  grid-template-columns:max-content max-content 1fr;gap:10px;
  padding:6px 0;border-bottom:1px solid #2b1a1c;font-size:12.5px;
  align-items:baseline}
.blockers .row:last-child{border-bottom:none}
.blockers .row .fid{color:var(--red);font-weight:600;
  font-variant-numeric:tabular-nums;font-size:11.5px}
.blockers .row .raised-by{color:var(--dim);font-size:11px;
  text-transform:uppercase;letter-spacing:.05em}
.blockers .row .summary{color:var(--fg)}
.blockers .row .rec{color:var(--dim);font-size:11.5px;margin-top:2px;
  grid-column:1 / -1;padding-left:0}
.blockers .empty-msg{color:var(--dim);font-size:13px;font-style:italic}
.hq-footer{margin-top:24px;padding-top:12px;border-top:1px solid var(--border);
  font-size:11.5px;color:var(--dim);text-align:center;line-height:1.7}
.hq-footer code{background:#0d1117;padding:1px 6px;border-radius:4px;
  font-size:11px;color:var(--fg)}
#hq-updated{position:fixed;top:14px;right:20px;font-size:12px;color:var(--dim)}
.unconfigured-banner{background:rgba(210,153,34,.12);
  border-left:4px solid var(--amber);padding:10px 14px;border-radius:6px;
  margin-bottom:18px;font-size:13px;color:var(--fg)}
.unconfigured-banner code{background:#0d1117;padding:1px 6px;border-radius:4px;
  font-size:12px;color:var(--dim)}
.rd-pulse{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media (max-width: 1100px){.rd-pulse{grid-template-columns:1fr}}
.rd-column{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:12px 14px;min-height:120px;
  display:flex;flex-direction:column}
.rd-column h3{margin:0 0 10px;font-size:11.5px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--dim);font-weight:600}
.rd-column-body{flex:1;font-size:12.5px;line-height:1.5;color:var(--fg)}
.rd-column-body .rd-item{padding:6px 0;border-bottom:1px solid #1c2129}
.rd-column-body .rd-item:last-child{border-bottom:none}
.rd-column-body .rd-id{color:var(--dim);font-size:11px;
  font-variant-numeric:tabular-nums;margin-right:6px}
.rd-column-body .rd-prio{font-size:10px;font-weight:700;padding:1px 5px;
  border-radius:4px;letter-spacing:.04em;text-transform:uppercase;
  margin-right:6px;background:rgba(139,148,158,.15);color:var(--dim);
  border:1px solid var(--border)}
.rd-column-body .rd-tag{color:var(--purple);font-size:11px;margin-right:6px;
  text-transform:uppercase;letter-spacing:.04em}
.rd-column-body .empty{color:var(--dim);font-style:italic;font-size:12px}
.rd-more{margin-top:8px;font-size:11.5px;color:var(--accent);
  text-decoration:none;align-self:flex-start}
.rd-more:hover{text-decoration:underline}
/* F015 -- Org & Flow section. Page-scoped additive CSS (no _BASE_CSS
 * change, so no _BASE_CSS_VERSION bump). */
.org-flow{display:flex;flex-direction:column;gap:12px}
.org-sub{margin:0 0 10px;font-size:11.5px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--dim);font-weight:600}
.org-sub .aux{font-size:11px;color:var(--dim);font-weight:400;
  text-transform:none;letter-spacing:0}
.org-tier{margin-bottom:12px}
.org-tier:last-child{margin-bottom:0}
.org-tier h4{margin:0 0 6px;font-size:11px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--dim);font-weight:600}
.org-tier-roles{display:grid;
  grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
@media (max-width: 700px){.org-tier-roles{grid-template-columns:1fr}}
.org-chip{background:#0d1117;border:1px solid var(--border);
  border-radius:8px;padding:8px 10px;font-size:12px;
  display:flex;flex-direction:column;gap:3px}
.org-chip.idle{opacity:.35}
.org-chip .org-role{font-weight:600;color:var(--fg);
  display:flex;align-items:center;gap:7px}
.org-chip .org-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.org-chip .org-dot.active{background:var(--green);
  box-shadow:0 0 5px rgba(63,185,80,.6)}
.org-chip .org-dot.idle{background:var(--dim)}
.org-chip .org-persona{color:var(--purple);font-size:11px;font-style:italic}
.org-chip .org-reports{color:var(--dim);font-size:11px}
.org-chip .org-reports b{color:var(--accent);font-weight:600}
.org-pipeline{display:flex;flex-wrap:wrap;gap:6px;align-items:stretch}
.org-stage{background:#0d1117;border:1px solid var(--border);
  border-radius:8px;padding:6px 10px;font-size:11.5px;min-width:78px;
  display:flex;flex-direction:column;gap:2px}
.org-stage.cond{border-style:dashed;border-color:var(--amber)}
.org-stage .org-stage-name{font-weight:700;color:var(--fg);
  white-space:nowrap}
.org-stage.cond .org-stage-name{color:var(--amber)}
.org-stage .org-stage-owner{color:var(--dim);font-size:10.5px;
  white-space:nowrap}
.org-arrow{color:var(--dim);align-self:center;font-size:13px;
  user-select:none}
.org-handoffs .row{display:grid;
  grid-template-columns:max-content max-content 1fr;gap:10px;
  padding:5px 0;border-bottom:1px solid #1c2129;font-size:12px;
  align-items:baseline}
.org-handoffs .row:last-child{border-bottom:none}
.org-handoffs .row .ts{color:var(--dim);font-size:11px;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.org-handoffs .row .fid{color:var(--purple);font-weight:600;
  font-size:11px;font-variant-numeric:tabular-nums;white-space:nowrap}
.org-handoffs .row .edge b{color:var(--accent);font-weight:600}
@media (max-width: 700px){
  .org-handoffs .row{grid-template-columns:max-content 1fr}
  .org-handoffs .row .ts{grid-column:1 / -1}
}
</style></head><body>
__NAV__
<div id="hq-updated">loading&hellip;</div>

<div class="hq-header">
  <div class="hq-title">
    <h1>Blue Lock Trading Co. &mdash; HQ</h1>
    <div class="mission" id="hq-mission">&hellip;</div>
  </div>
  <div class="hq-sprint">
    <div class="sprint-badge" id="hq-sprint-badge">&hellip;</div>
    <div class="day-counter" id="hq-day-counter">&hellip;</div>
  </div>
</div>

<div id="hq-unconfigured"></div>

<div class="wd-strip" id="watchdog-strip" aria-label="Ops watchdog"
     title="F017 ops watchdog — green/amber/red per check">
  <span class="wd-chip wd-na">watchdog loading&hellip;</span>
</div>

<div class="kpi-strip" id="kpi-strip"></div>

<div class="section">
  <h2>Sprint Kanban <span class="aux">features by stage; owner + age
      in current stage</span></h2>
  <div class="kanban" id="kanban"></div>
</div>

<div class="section" aria-labelledby="rd-pulse-heading">
  <h2 id="rd-pulse-heading">R&amp;D pulse <span class="aux">intake queue,
      experiments in flight, most recent published finding</span></h2>
  <div class="rd-pulse" id="rd-pulse">
    <div class="rd-column">
      <h3>Intake queue</h3>
      <div class="rd-column-body" data-rd-column="intake">
        <div class="empty">loading&hellip;</div>
      </div>
      <a href="/rd/intake" class="rd-more">See all intake &rarr;</a>
    </div>
    <div class="rd-column">
      <h3>Experiments in flight</h3>
      <div class="rd-column-body" data-rd-column="experiments">
        <div class="empty">loading&hellip;</div>
      </div>
      <a href="/rd/experiments" class="rd-more">See all experiments &rarr;</a>
    </div>
    <div class="rd-column">
      <h3>Most recent published finding</h3>
      <div class="rd-column-body" data-rd-column="latest-finding">
        <div class="empty">loading&hellip;</div>
      </div>
      <a href="/research" class="rd-more">/research &rarr;</a>
    </div>
  </div>
</div>

<div class="section">
  <h2>Role grid <span class="aux">19 roles across 4 tiers (+
      executive-adjacent); active in colour, standby dimmed</span></h2>
  <div id="role-grid"></div>
</div>

<div class="section" aria-labelledby="org-flow-heading">
  <h2 id="org-flow-heading">Org &amp; Flow <span class="aux">who reports
      to whom, the review-chain pipeline, and the latest persona
      handoffs</span></h2>
  <div class="org-flow" id="org-flow">
    <div class="card">
      <h3 class="org-sub">Org chart <span class="aux">by tier; explicit
          report lines win, tier default otherwise</span></h3>
      <div id="org-chart"><div class="empty">loading&hellip;</div></div>
    </div>
    <div class="card">
      <h3 class="org-sub">Review-chain pipeline <span class="aux">*
          = conditional stage</span></h3>
      <div class="org-pipeline" id="org-pipeline"><div class="empty">
          loading&hellip;</div></div>
    </div>
    <div class="card">
      <h3 class="org-sub">Recent handoffs <span class="aux"
          id="org-handoffs-aux"></span></h3>
      <div class="org-handoffs" id="org-handoffs"><div class="empty">
          loading&hellip;</div></div>
    </div>
  </div>
</div>

<div class="section">
  <h2>Blockers panel <span class="aux">features awaiting CEO
      attention</span></h2>
  <div class="blockers empty-state" id="blockers">
    <h2>Blockers</h2>
    <div class="empty-msg">loading&hellip;</div>
  </div>
</div>

<div class="section">
  <h2>Decisions log <span class="aux">most recent decisions from the
      ledger</span></h2>
  <div class="decisions-log" id="decisions-log">
    <div class="empty">loading&hellip;</div>
  </div>
</div>

<div class="hq-footer" id="hq-footer">&hellip;</div>

<script>
function esc(x){ const d=document.createElement("div");
  d.innerText=String(x==null?"":x); return d.innerHTML; }

// Kanban stage -> column mapping. The review chain has 10 stages
// (spec / research / design / architecture / build / qa / security /
// legal / signoff / ship) but users want 5 columns for scannability;
// we bucket them here. Stages after "ship" collapse to Ship (shipped,
// done -> Ship).
const STAGE_TO_COLUMN = {
  "spec": "Backlog",
  "research": "Design",
  "design": "Design",
  "architecture": "Design",
  "build": "Build",
  "qa": "Review",
  "security": "Review",
  "legal": "Review",
  "signoff": "Review",
  "ship": "Ship",
  "shipped": "Ship",
  "done": "Ship"
};
const KANBAN_COLS = ["Backlog", "Design", "Build", "Review", "Ship"];

// Tier order for the role grid; matches company/README.md.
const TIER_ORDER = ["executive", "design", "engineering", "business"];
const TIER_LABELS = {
  "executive": "Executive",
  "design": "Design",
  "engineering": "Engineering",
  "business": "Business"
};

async function fetchJson(url){
  try {
    const r = await fetch(url);
    if(r.status === 401) return {__auth__: true};
    if(!r.ok) return {__error__: "HTTP " + r.status};
    return await r.json();
  } catch(e){ return {__error__: String((e && e.message) || e)}; }
}

function daysSinceIso(iso){
  if(!iso) return null;
  const t = new Date(String(iso).replace(" ","T"));
  if(isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t.getTime()) / 86400000));
}
function daysUntilIso(iso){
  if(!iso) return null;
  const t = new Date(String(iso).replace(" ","T"));
  if(isNaN(t)) return null;
  return Math.ceil((t.getTime() - Date.now()) / 86400000);
}

function renderHeader(hq){
  const meta = hq.meta || {};
  const sprint = (hq.sprints || [])[0] || {};
  document.getElementById("hq-mission").innerText =
    meta.one_liner || meta.mission || "";
  const badge = document.getElementById("hq-sprint-badge");
  if(sprint.id){
    badge.innerText = "SPRINT \u00B7 " + (sprint.name || sprint.id)
      .toUpperCase();
  } else {
    badge.innerText = "NO SPRINT";
  }
  const dayCounter = document.getElementById("hq-day-counter");
  if(sprint.started_at && sprint.day_target){
    const dayCount = daysSinceIso(sprint.started_at);
    const day = (dayCount == null ? 0 : dayCount) + 1;
    dayCounter.innerText = "day " + day + " of " + sprint.day_target;
  } else {
    dayCounter.innerText = "\u2014";
  }
}

function renderUnconfigured(hq){
  const box = document.getElementById("hq-unconfigured");
  const meta = hq.meta || {};
  if(hq.__auth__){
    box.innerHTML = '<div class="unconfigured-banner">Auth required '+
      '\u2014 pass <code>?token=</code> in the URL to see the '+
      'company state.</div>';
    return true;
  }
  if(hq.__error__){
    box.innerHTML = '<div class="unconfigured-banner">HQ API error: '+
      esc(hq.__error__) + ' \u2014 the platform server may be '+
      'restarting.</div>';
    return true;
  }
  if(meta.unconfigured){
    box.innerHTML = '<div class="unconfigured-banner">Company ledger '+
      'not yet configured on this server. Reason: <code>'+
      esc(meta.unconfigured_reason || "unknown") + '</code>. See '+
      '<code>company/README.md</code> for the charter.</div>';
    return true;
  }
  box.innerHTML = "";
  return false;
}

function renderKpiStrip(hq){
  const el = document.getElementById("kpi-strip");
  const k = hq.kpis || {};
  const intakeOpen = k.intake_items_open == null ? 0 : k.intake_items_open;
  const tiles = [
    {k: "Features shipped", v: (k.features_shipped_sprint_0 || 0) +
      " / " + (k.features_total_sprint_0 || 0),
     foot: "sprint 0"},
    {k: "Backlog", v: k.backlog_size == null ? "\u2014" : k.backlog_size,
     foot: "open features"},
    {k: "Bugs open", v: k.bugs_open == null ? "\u2014" : k.bugs_open,
     foot: "QA ledger"},
    {k: "Cycle time p50", v: k.cycle_time_days_p50 == null ? "n/a"
      : (k.cycle_time_days_p50 + " d"),
     foot: "spec \u2192 ship"},
    {k: "Test coverage", v: k.test_coverage_pct == null ? "n/a"
      : (k.test_coverage_pct + " %"),
     foot: "pytest tests/"},
    {k: "Active roles", v: (k.active_roles || 0) + " / " +
      (k.total_roles || 0),
     foot: "19 seats total"},
    {k: "Intake open", v: intakeOpen,
     foot: intakeOpen > 20 ? "over triage bandwidth" : "R&D queue",
     tone: intakeOpen > 20 ? "warn" : null},
    {k: "Experiments in flight", v: k.experiments_in_flight == null
      ? 0 : k.experiments_in_flight,
     foot: "R&D portfolio"},
    {k: "Findings (30d)", v: k.published_findings_last_30d == null
      ? 0 : k.published_findings_last_30d,
     foot: "condensed + shipped"}
  ];
  el.innerHTML = tiles.map(t =>
    '<div class="kpi-tile' + (t.tone === "warn" ? " warn" : "") + '">'+
      '<div class="k">' + esc(t.k) + '</div>'+
      '<div class="v">' + esc(t.v) + '</div>'+
      '<div class="foot">' + esc(t.foot) + '</div>'+
    '</div>').join("");
}

function renderRdPulse(hq){
  const intakeEl = document.querySelector(
    '[data-rd-column="intake"]');
  const expEl = document.querySelector(
    '[data-rd-column="experiments"]');
  const findEl = document.querySelector(
    '[data-rd-column="latest-finding"]');
  if(!intakeEl || !expEl || !findEl) return;

  const intake = (hq.intake || []).filter(i =>
    (i.status || "") !== "closed").slice(0, 5);
  if(!intake.length){
    intakeEl.innerHTML = '<div class="empty">'+
      'no open intake items</div>';
  } else {
    intakeEl.innerHTML = intake.map(i => {
      const cls = String(i.classification || "").toUpperCase();
      const prio = String(i.priority || "").toUpperCase();
      return '<div class="rd-item">'+
        '<span class="rd-id">' + esc(i.id || "") + '</span>'+
        (prio ? '<span class="rd-prio">' + esc(prio) + '</span>' : '') +
        (cls ? '<span class="rd-tag">' + esc(cls) + '</span>' : '') +
        esc(i.summary || "") +
      '</div>';
    }).join("");
  }

  const experiments = (hq.experiments || []).filter(e => {
    const s = String(e.status || "").toLowerCase();
    return s && s !== "closed" && !s.startsWith("closed-")
      && s !== "shipped" && s !== "done";
  }).slice(0, 5);
  if(!experiments.length){
    expEl.innerHTML = '<div class="empty">'+
      'no experiments in flight</div>';
  } else {
    expEl.innerHTML = experiments.map(e => {
      const hyp = e.hypothesis || e.verdict || "";
      return '<div class="rd-item">'+
        '<span class="rd-id">' + esc(e.id || "") + '</span>'+
        '<span class="rd-tag">' + esc(e.status || "") + '</span>'+
        esc(hyp) +
      '</div>';
    }).join("");
  }

  const published = (hq.experiments || []).filter(e =>
    (e.condensed_finding_status || "") === "published");
  if(!published.length){
    findEl.innerHTML = '<div class="empty">'+
      'no published findings yet</div>';
  } else {
    const latest = published[published.length - 1];
    findEl.innerHTML = '<div class="rd-item">'+
      '<span class="rd-id">' + esc(latest.id || "") + '</span>'+
      '<span class="rd-tag">' + esc(latest.verdict || "") + '</span>'+
      esc(latest.condensed_finding_path || "") +
    '</div>';
  }
}

function renderKanban(hq){
  const el = document.getElementById("kanban");
  const buckets = {};
  for(const c of KANBAN_COLS) buckets[c] = [];
  for(const f of (hq.features || [])){
    const col = STAGE_TO_COLUMN[f.current_stage] || "Backlog";
    buckets[col].push(f);
  }
  el.innerHTML = KANBAN_COLS.map(col => {
    const items = buckets[col] || [];
    const cards = items.length ? items.map(f => {
      const prio = (f.priority || "P2").toLowerCase();
      const owner = f.current_owner_role || "\u2014";
      const age = f.age_in_stage_days == null ? "0d"
        : (f.age_in_stage_days + "d");
      return '<div class="feature-card">'+
        '<div class="title">'+
          '<span>' + esc(f.title || "(untitled)") + '</span>'+
          '<span class="fid">' + esc(f.id || "") + '</span>'+
        '</div>'+
        '<div class="meta">'+
          '<span class="prio ' + prio + '">' + esc(f.priority || "") +
            '</span>'+
          '<span class="owner">' + esc(owner) + '</span>'+
          '<span>' + esc(age) + ' in stage</span>'+
          '<span>stage: ' + esc(f.current_stage || "\u2014") + '</span>'+
        '</div>'+
      '</div>';
    }).join("") : '<div class="empty">no features here</div>';
    return '<div class="kanban-col">'+
      '<h3><span>' + esc(col) + '</span>'+
      '<span class="count">' + items.length + '</span></h3>'+
      cards +
    '</div>';
  }).join("");
}

function renderRoleGrid(hq){
  const el = document.getElementById("role-grid");
  const byTier = {};
  for(const t of TIER_ORDER) byTier[t] = [];
  for(const r of (hq.roles || [])){
    const t = r.tier || "business";
    (byTier[t] || byTier.business).push(r);
  }
  el.innerHTML = TIER_ORDER.map(tier => {
    const roles = byTier[tier] || [];
    if(!roles.length) return "";
    return '<div class="roles-tier">'+
      '<h3>' + esc(TIER_LABELS[tier] || tier) +
        ' <span class="aux">(' + roles.length + ')</span></h3>'+
      '<div class="role-grid">'+
      roles.map(r => {
        const active = !!r.active;
        const throughput = r.throughput_last_7d == null ? 0
          : r.throughput_last_7d;
        return '<div class="role-tile ' + (active ? "" : "idle") + '">'+
          '<div class="role-title">'+
            '<span class="status-dot ' + (active ? "active" : "idle") +
              '"></span>'+
            '<span>' + esc(r.title || r.id) + '</span>'+
          '</div>'+
          (r.persona_name ?
            '<div class="persona">' + esc(r.persona_name) + '</div>'
            : '') +
          '<div class="task">' + esc(r.current_task || "\u2014") +
            '</div>'+
          '<div class="throughput">' + throughput +
            ' feature' + (throughput === 1 ? "" : "s") +
            ' owned last 7 d</div>'+
        '</div>';
      }).join("") +
      '</div>'+
    '</div>';
  }).join("");
}

function renderBlockers(hq){
  const el = document.getElementById("blockers");
  const blockers = hq.blockers || [];
  if(!blockers.length){
    el.className = "blockers empty-state";
    el.innerHTML = '<h2>Blockers</h2>'+
      '<div class="empty-msg">No blockers. Company is executing.</div>';
    return;
  }
  el.className = "blockers";
  el.innerHTML = '<h2>Blockers awaiting CEO</h2>'+
    blockers.map(b =>
      '<div class="row">'+
        '<span class="fid">' + esc(b.feature_id || "") + '</span>'+
        '<span class="raised-by">' + esc(b.raised_by || "") + '</span>'+
        '<span class="summary">' + esc(b.summary || "") + '</span>'+
        (b.recommendation
          ? ('<div class="rec">Recommendation: ' +
             esc(b.recommendation) + '</div>')
          : "") +
      '</div>').join("");
}

function renderDecisions(hq){
  const el = document.getElementById("decisions-log");
  const decisions = hq.decisions || [];
  if(!decisions.length){
    el.innerHTML = '<div class="empty">no decisions logged yet</div>';
    return;
  }
  el.innerHTML = decisions.slice().reverse().map(d =>
    '<div class="row">'+
      '<span class="date">' + esc(d.date || "") + '</span>'+
      '<span class="role">' + esc(d.role || "") + '</span>'+
      '<span class="decision">'+
        '<span class="did">' + esc(d.id || "") + '</span>'+
        esc(d.decision || "") +
      '</span>'+
    '</div>').join("");
}

function renderFooter(hq){
  const meta = hq.meta || {};
  const path = "company/ledger/company_state.json";
  document.getElementById("hq-footer").innerHTML =
    'updated ' + esc(new Date().toLocaleTimeString()) +
    ' \u00b7 generated from <code>' + esc(path) + '</code>' +
    ' \u00b7 schema v' + esc(meta.schema_version || "?") +
    ' \u00b7 founded ' + esc(meta.founded || "\u2014");
}

// F015 -- Org & Flow. Fetches /api/hq/org (its own endpoint so the
// /api/hq/state contract stays untouched) and renders the org chart,
// the review-chain pipeline, and the recent-handoff feed. Every
// failure path degrades to friendly copy inside the section.
function renderOrgChart(org){
  const el = document.getElementById("org-chart");
  const tiers = org.tiers || [];
  if(!tiers.length){
    el.innerHTML = '<div class="empty">' +
      (org.unconfigured
        ? 'company ledger not configured \u2014 ' +
          esc(org.unconfigured_reason || "unknown")
        : 'no roles on the ledger') + '</div>';
    return;
  }
  el.innerHTML = tiers.map(tier => {
    const roles = tier.roles || [];
    return '<div class="org-tier">'+
      '<h4>' + esc(tier.label || tier.id) +
        ' <span class="aux">(' + roles.length + ')</span></h4>'+
      '<div class="org-tier-roles">'+
      roles.map(r => {
        const active = !!r.active;
        const reports = (r.reports_to || [])
          .map(x => '<b>' + esc(String(x).toUpperCase()) + '</b>')
          .join(" + ");
        return '<div class="org-chip ' + (active ? "" : "idle") + '">'+
          '<div class="org-role">'+
            '<span class="org-dot ' + (active ? "active" : "idle") +
              '"></span>'+
            '<span>' + esc(r.title || r.id) + '</span>'+
          '</div>'+
          (r.persona_name
            ? '<div class="org-persona">' + esc(r.persona_name) + '</div>'
            : '') +
          '<div class="org-reports">' +
            (reports ? ('&#8627; reports to ' + reports)
                     : 'top of the chart') +
          '</div>'+
        '</div>';
      }).join("") +
      '</div>'+
    '</div>';
  }).join("");
}

function renderOrgPipeline(org){
  const el = document.getElementById("org-pipeline");
  const stages = org.review_chain || [];
  if(!stages.length){
    el.innerHTML = '<div class="empty">no review chain on file</div>';
    return;
  }
  el.innerHTML = stages.map((s, i) => {
    const cond = !!s.conditional;
    const pill = '<div class="org-stage' + (cond ? " cond" : "") +
      '" title="' + esc(s.fires_when || "") + '">'+
      '<span class="org-stage-name">' + esc(s.stage || "") +
        (cond ? "*" : "") + '</span>'+
      '<span class="org-stage-owner">' + esc(s.owner || "") + '</span>'+
    '</div>';
    const arrow = (i < stages.length - 1)
      ? '<span class="org-arrow">&#8594;</span>' : '';
    return pill + arrow;
  }).join("");
}

function renderOrgHandoffs(org){
  const el = document.getElementById("org-handoffs");
  const aux = document.getElementById("org-handoffs-aux");
  const handoffs = org.handoffs || [];
  if(aux){
    aux.innerText = org.handoffs_total
      ? ("latest " + handoffs.length + " of " + org.handoffs_total +
         " on tape")
      : "";
  }
  if(!handoffs.length){
    el.innerHTML = '<div class="empty">no handoffs on tape yet</div>';
    return;
  }
  el.innerHTML = handoffs.map(h => {
    const ts = String(h.timestamp || "").replace("T", " ")
      .replace("Z", "");
    return '<div class="row">'+
      '<span class="ts">' + esc(ts || "\u2014") + '</span>'+
      '<span class="fid">' + esc(h.feature_id || h.scope || "\u2014") +
        '</span>'+
      '<span class="edge"><b>' + esc(h.from_role || "?") + '</b>'+
        ' &#8594; <b>' + esc(h.to_role || "?") + '</b>'+
        (h.verdict ? (' \u00b7 ' + esc(h.verdict)) : '') +
      '</span>'+
    '</div>';
  }).join("");
}

async function renderOrgFlow(){
  const org = await fetchJson("/api/hq/org");
  if(org.__error__ || org.__auth__){
    const msg = org.__auth__ ? "auth required"
      : ("org API error: " + org.__error__);
    document.getElementById("org-chart").innerHTML =
      '<div class="empty">' + esc(msg) + '</div>';
    renderOrgPipeline({review_chain: []});
    renderOrgHandoffs({handoffs: []});
    return;
  }
  renderOrgChart(org);
  renderOrgPipeline(org);
  renderOrgHandoffs(org);
}

async function renderWatchdog(){
  // F017 ops-watchdog strip: one chip per check, coloured by status.
  const el = document.getElementById("watchdog-strip");
  const wd = await fetchJson("/api/watchdog/status");
  if(wd.__error__ || wd.__auth__){
    el.innerHTML = '<span class="wd-chip wd-na">watchdog: ' +
      esc(wd.__auth__ ? "auth required" : "unavailable") + '</span>';
    return;
  }
  const checks = wd.checks || [];
  if(!checks.length){
    el.innerHTML = '<span class="wd-chip wd-na">watchdog: no checks</span>';
    return;
  }
  el.innerHTML = checks.map(c => {
    const st = String(c.status || "na");
    return '<span class="wd-chip wd-' + esc(st) + '" title="' +
      esc(c.detail || "") + '">' + esc(c.id) +
      (st === "ok" ? "" : " \u00b7 " + esc(st)) + '</span>';
  }).join("");
}

async function refresh(){
  const hq = await fetchJson("/api/hq/state");
  document.getElementById("hq-updated").innerText =
    "updated " + new Date().toLocaleTimeString();
  const blocked = renderUnconfigured(hq);
  renderHeader(hq);
  if(blocked){
    // Still render everything else so the shell isn't blank.
    renderKpiStrip({kpis: {}});
    renderKanban({features: []});
    renderRdPulse({intake: [], experiments: []});
    renderRoleGrid({roles: []});
    renderBlockers({blockers: []});
    renderDecisions({decisions: []});
    renderFooter({meta: {}});
    return;
  }
  renderKpiStrip(hq);
  renderKanban(hq);
  renderRdPulse(hq);
  renderRoleGrid(hq);
  renderBlockers(hq);
  renderDecisions(hq);
  renderFooter(hq);
}
refresh();
renderOrgFlow();
renderWatchdog();
setInterval(refresh, 30000);
setInterval(renderOrgFlow, 30000);
setInterval(renderWatchdog, 60000);
</script></body></html>"""

HQ_PAGE = (_HQ_TEMPLATE
           .replace("__BASE_CSS__", _BASE_CSS)
           .replace("__NAV__", nav('hq')))


# ---------------------------------------------------------------------------
# /performance -- F001, public equity curve + KPI tiles + per-pair breakdown
# ---------------------------------------------------------------------------
#
# Renders GET /api/performance/state as: (a) an inline SVG equity curve
# (no chart lib -- framework-free per CTO), (b) 4-5 headline KPI tiles
# (days_live, net_pips, worst_dd_pips, win_rate_pct, sharpe_or_null),
# (c) a per-pair breakdown table, (d) a source-hint caption naming
# where the numbers came from, (e) a Legal-authored disclaimer footer.
#
# Loading / error / empty states all use the F005 withStates() helper
# so the page stays alive during network flakiness. Mobile media
# queries (@media (max-width: 700px)) collapse the KPI grid to a
# single column and the equity SVG reflows to full width -- F004
# baked in, not retrofit.

_PERFORMANCE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Performance -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
.perf-header{margin-bottom:18px}
.perf-header h1{margin:0 0 6px;font-size:22px}
.perf-header .preamble{color:var(--dim);font-size:13.5px;line-height:1.55;
  max-width:820px}
.source-hint{margin:12px 0 18px;padding:10px 14px;
  background:rgba(88,166,255,.06);border:1px solid rgba(88,166,255,.28);
  border-radius:8px;font-size:12.5px;color:var(--fg);line-height:1.55}
.source-hint .k{color:var(--dim);text-transform:uppercase;font-size:11px;
  letter-spacing:.05em;font-weight:600;margin-right:8px}
.kpi-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;
  margin-bottom:18px}
@media (max-width: 1100px){.kpi-grid{grid-template-columns:repeat(3,1fr)}}
@media (max-width: 700px){.kpi-grid{grid-template-columns:1fr}}
.kpi-tile{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:14px 16px;min-height:88px}
.kpi-tile .k{font-size:11px;color:var(--dim);text-transform:uppercase;
  letter-spacing:.05em;font-weight:600;margin-bottom:6px}
.kpi-tile .v{font-size:24px;font-variant-numeric:tabular-nums;color:var(--fg);
  font-weight:600;line-height:1.1}
.kpi-tile .v.ok{color:var(--green)} .kpi-tile .v.bad{color:var(--red)}
.kpi-tile .foot{font-size:11px;color:var(--dim);margin-top:8px;line-height:1.4}
.equity-wrap{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:16px 18px;margin-bottom:18px}
.equity-wrap h2{margin:0 0 10px;font-size:15px;display:flex;
  justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px}
.equity-wrap h2 .aux{font-size:11.5px;color:var(--dim);font-weight:400}
#equity-svg{display:block;width:100%;height:280px}
@media (max-width: 700px){#equity-svg{height:220px}}
.equity-empty{color:var(--dim);font-style:italic;padding:40px 8px;
  text-align:center;font-size:13px}
.per-pair-wrap{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:16px 18px;margin-bottom:18px;
  overflow-x:auto}
.per-pair-wrap h2{margin:0 0 10px;font-size:15px}
.per-pair-table{width:100%;border-collapse:collapse;font-size:12.5px;
  min-width:520px}
.per-pair-table th{text-align:left;padding:6px 10px;color:var(--dim);
  font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  border-bottom:1px solid var(--border)}
.per-pair-table td{padding:6px 10px;border-bottom:1px solid #1c2129;
  font-variant-numeric:tabular-nums}
.per-pair-table td.sym{font-weight:700;color:var(--fg)}
.per-pair-table td.pos{color:var(--green)} .per-pair-table td.neg{color:var(--red)}
.per-pair-table tr:last-child td{border-bottom:none}
.disclaimer{margin-top:24px;padding:14px 16px;border-radius:8px;
  background:rgba(139,148,158,.04);border:1px solid var(--border);
  font-size:12px;color:var(--dim);line-height:1.55}
.disclaimer .lead{color:var(--fg);font-weight:600;margin-bottom:6px}
#updated{position:fixed;top:14px;right:20px;font-size:12px;color:var(--dim)}
</style></head><body>
__NAV__
<div id="updated">loading&hellip;</div>

<div class="perf-header">
  <h1>How we're doing</h1>
  <div class="preamble">This is the demo-account P&amp;L for our live
  zones agent and the paper equity curve for the striker squad,
  updated bar-by-bar. Every number here is a real number the platform
  wrote to disk &mdash; no back-tests, no cherry-picks.</div>
</div>

<div class="source-hint" id="source-hint">
  <span class="k">Source</span><span id="source-hint-text">&hellip;</span>
</div>

<div id="perf-body">
  <!-- withStates() fills this in on load; skeleton renders first -->
</div>

<div class="disclaimer">
  <div class="lead">Past performance is not indicative of future
  results.</div>
  These numbers are from a demo (paper-money) MetaTrader&nbsp;5
  account. The v1 zones agent places real orders on that demo
  account; the v2 striker squad runs in shadow-paper mode and never
  sends orders to the broker. No real capital is at risk. Nothing on
  this page is investment advice or a solicitation. The Sharpe
  metric (when shown) is a raw daily-pip Sharpe annualised by
  &radic;252 &mdash; use it as a sanity ratio, not a target.
</div>

<script>
__ERROR_COPY_JS__
__WITH_STATES_JS__

async function fetchJson(url){
  try{
    const r = await fetch(url);
    if(r.status === 401) return {__auth__: true};
    if(!r.ok) return {__error__: "HTTP " + r.status};
    return await r.json();
  } catch(e){ return {__error__: String(e && e.message || e)}; }
}

function fmtPips(v){
  if(v == null || isNaN(v)) return "\u2014";
  const n = Number(v);
  const sign = n >= 0 ? "+" : "";
  if(Math.abs(n) >= 1000){
    return sign + Math.round(n).toLocaleString();
  }
  return sign + n.toFixed(1);
}
function fmtPct(v){
  if(v == null || isNaN(v)) return "\u2014";
  return Number(v).toFixed(1) + " %";
}
function fmtSharpe(v, needed){
  if(v == null){
    if(needed == null) return "n/a";
    return "n/a \u2014 need " + needed + " more days";
  }
  return Number(v).toFixed(2);
}
function pipSpan(pips, extraCls){
  const cls = (pips == null || pips == 0) ? "" :
    (pips > 0 ? "pos" : "neg");
  return '<td class="' + cls + (extraCls ? ' ' + extraCls : '') + '">' +
    _esc(fmtPips(pips)) + '</td>';
}

function performanceSkeleton(){
  // Tuned to the final layout so no shift when data lands.
  return (
    '<div class="kpi-grid">'+
      '<div class="sk-tile"><div class="sk sk-line short"></div>'+
        '<div class="sk sk-line"></div><div class="sk sk-line short"></div></div>'.repeat(5)+
    '</div>'+
    '<div class="equity-wrap">'+
      '<div class="sk sk-line short" style="margin-bottom:10px"></div>'+
      '<div class="sk-chart" role="progressbar" aria-label="Loading equity curve"></div>'+
    '</div>'+
    '<div class="per-pair-wrap">'+
      '<div class="sk sk-line short" style="margin-bottom:10px"></div>'+
      '<div class="sk-row"><div class="sk sk-line"></div>'+
        '<div class="sk sk-line"></div><div class="sk sk-line"></div></div>'+
      '<div class="sk-row"><div class="sk sk-line"></div>'+
        '<div class="sk sk-line"></div><div class="sk sk-line"></div></div>'+
      '<div class="sk-row"><div class="sk sk-line"></div>'+
        '<div class="sk sk-line"></div><div class="sk sk-line"></div></div>'+
    '</div>'
  );
}

function renderEquityCurve(curve){
  if(!curve || !curve.length){
    return '<div class="equity-empty">'+
      _esc("No shadow-paper data yet -- the squad is still warming up.") +
      '</div>';
  }
  // Simple SVG polyline. 800x260 viewBox scales to container width.
  const W = 800, H = 260, PAD_L = 40, PAD_R = 12, PAD_T = 16, PAD_B = 26;
  const innerW = W - PAD_L - PAD_R, innerH = H - PAD_T - PAD_B;
  const n = curve.length;
  const ys = curve.map(p => Number(p.cum_pips) || 0);
  let ymin = Math.min(0, ...ys), ymax = Math.max(0, ...ys);
  if(ymin === ymax){ ymin -= 1; ymax += 1; }
  const yScale = v => PAD_T + innerH -
    ((v - ymin) / (ymax - ymin)) * innerH;
  const xScale = i => PAD_L + (n === 1 ? innerW / 2
                                       : (i / (n - 1)) * innerW);
  const pts = curve.map((p, i) => xScale(i).toFixed(1) + "," +
    yScale(Number(p.cum_pips) || 0).toFixed(1)).join(" ");
  const zeroY = yScale(0).toFixed(1);
  const finalY = yScale(ys[ys.length - 1]).toFixed(1);
  const finalV = ys[ys.length - 1];
  const strokeCls = finalV >= 0 ? "var(--green)" : "var(--red)";
  return (
    '<svg id="equity-svg" viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none" aria-label="Equity curve">'+
      '<line x1="' + PAD_L + '" y1="' + zeroY + '" x2="' +
        (W - PAD_R) + '" y2="' + zeroY + '" '+
        'stroke="var(--border)" stroke-dasharray="4 4" '+
        'stroke-width="1"/>'+
      '<polyline fill="none" stroke="' + strokeCls +
        '" stroke-width="2" points="' + pts + '"/>'+
      '<circle cx="' + xScale(n - 1).toFixed(1) + '" cy="' + finalY +
        '" r="4" fill="' + strokeCls + '"/>'+
      '<text x="' + PAD_L + '" y="' + (H - 6) + '" '+
        'fill="var(--dim)" font-size="11" font-family="ui-monospace,'+
        'SFMono-Regular,Menlo,monospace">' +
        _esc(String(curve[0].ts || "").slice(0, 10)) + '</text>'+
      '<text x="' + (W - PAD_R) + '" y="' + (H - 6) + '" '+
        'fill="var(--dim)" font-size="11" text-anchor="end" '+
        'font-family="ui-monospace,SFMono-Regular,Menlo,monospace">' +
        _esc(String(curve[curve.length - 1].ts || "").slice(0, 10)) +
      '</text>'+
    '</svg>'
  );
}

function renderKpiGrid(state){
  const net = state.net_pips;
  const netCls = net > 0 ? " ok" : net < 0 ? " bad" : "";
  const dd = state.worst_dd_pips;
  return (
    '<div class="kpi-grid">'+
      '<div class="kpi-tile"><div class="k">Days live</div>'+
        '<div class="v">' + _esc(state.days_live) + '</div>'+
        '<div class="foot">' + _esc(state.trades_total) +
        ' closed trade' + (state.trades_total === 1 ? '' : 's') +
        ' on tape</div></div>'+
      '<div class="kpi-tile"><div class="k">Net pips</div>'+
        '<div class="v' + netCls + '">' + _esc(fmtPips(net)) + '</div>'+
        '<div class="foot">sum across every closed trade</div></div>'+
      '<div class="kpi-tile"><div class="k">Worst drawdown</div>'+
        '<div class="v bad">' + _esc(fmtPips(-Math.abs(dd || 0))) + '</div>'+
        '<div class="foot">peak-to-trough on the equity curve</div></div>'+
      '<div class="kpi-tile"><div class="k">Win rate</div>'+
        '<div class="v">' + _esc(fmtPct(state.win_rate_pct)) + '</div>'+
        '<div class="foot">wins / total closed trades</div></div>'+
      '<div class="kpi-tile"><div class="k">Sharpe</div>'+
        '<div class="v">' + _esc(fmtSharpe(state.sharpe_or_null,
          state.sharpe_days_needed)) + '</div>'+
        '<div class="foot">daily pip Sharpe &middot; annualised '+
        '(needs &ge; 30 days)</div></div>'+
    '</div>'
  );
}

function renderPerPair(perPair){
  if(!perPair || !perPair.length){
    return '<div class="per-pair-wrap"><h2>By pair</h2>'+
      '<div class="equity-empty">No trades on any pair yet.</div></div>';
  }
  const rows = perPair.map(r =>
    '<tr>'+
      '<td class="sym">' + _esc(r.symbol) + '</td>'+
      '<td>' + _esc(r.trades) + '</td>'+
      '<td>' + _esc(r.wins) + '</td>'+
      pipSpan(r.net_pips) +
      pipSpan(r.avg_pips) +
      pipSpan(r.best_pips) +
      pipSpan(r.worst_pips) +
    '</tr>').join("");
  return (
    '<div class="per-pair-wrap"><h2>By pair</h2>'+
      '<table class="per-pair-table">'+
        '<thead><tr>'+
          '<th>Pair</th><th>Trades</th><th>Wins</th>'+
          '<th>Net pips</th><th>Avg pips</th>'+
          '<th>Best trade</th><th>Worst trade</th>'+
        '</tr></thead>'+
        '<tbody>' + rows + '</tbody>'+
      '</table></div>'
  );
}

function renderPerformance(state, box){
  if(!state){ return "empty"; }
  const emptyOverall = (state.trades_total || 0) === 0 &&
                       (!state.equity_curve || !state.equity_curve.length);
  document.getElementById("source-hint-text").innerText =
    state.source_hint || "\u2014";
  box.innerHTML =
    renderKpiGrid(state) +
    '<div class="equity-wrap">'+
      '<h2>Equity curve <span class="aux">cumulative pips across '+
      'every closed trade &middot; newest at right</span></h2>'+
      renderEquityCurve(state.equity_curve) +
    '</div>' +
    renderPerPair(state.per_pair);
  if(emptyOverall) return "empty";
}

async function refresh(){
  const box = document.getElementById("perf-body");
  await withStates(
    box,
    () => fetchJson("/api/performance/state"),
    renderPerformance,
    {
      skeletonHtml: performanceSkeleton(),
      emptyCopyKey: "no_data_yet",
      emptyMessage: "No shadow-paper data yet -- the squad is still "+
                    "warming up. Come back after the next H4 bar close.",
      retryLabel: "Try again"
    }
  );
  document.getElementById("updated").innerText =
    "updated " + new Date().toLocaleTimeString();
}
refresh();
setInterval(refresh, 60000);
</script></body></html>"""

PERFORMANCE_PAGE = (_PERFORMANCE_TEMPLATE
                    .replace("__BASE_CSS__", _BASE_CSS)
                    .replace("__SKELETON_CSS__", _SKELETON_CSS)
                    .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                    .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                    .replace("__NAV__", nav('performance')))


# ---------------------------------------------------------------------------
# F002 -- /players index and /players/<id> detail
# ---------------------------------------------------------------------------
#
# Index page shows the ten strikers as a card grid. Detail page shows
# one striker's playstyle prose, career stats, signature setup, recent
# activity, evolution history, and the IP disclaimer footer. Both pages
# consume F005's withStates() helper for skeleton/error/empty states.
#
# Mobile media queries collapse the card grid and the stats grid to
# single-column below 480 px. Signature setup ASCII lives in a <pre>
# with overflow-x:auto so the diagram scrolls horizontally instead of
# wrapping.
#
# The IP disclaimer copy is authoritative in company/legal/disclaimers.md
# under `third-party-name-usage`; changes require a Legal-owned bump.

_PLAYERS_CSS = r"""
.players-header{margin-bottom:18px}
.players-header h1{margin:0 0 6px;font-size:22px}
.players-header .preamble{color:var(--dim);font-size:13.5px;line-height:1.55;
  max-width:820px}
.players-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;
  margin-bottom:18px}
@media (max-width: 1100px){.players-grid{grid-template-columns:repeat(2,1fr)}}
@media (max-width: 700px){.players-grid{grid-template-columns:1fr}}
.player-card{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:14px 16px;display:block;text-decoration:none;
  color:var(--fg);transition:border-color .15s ease}
.player-card:hover{border-color:var(--accent)}
.player-card.retired{opacity:.65}
.player-card .name{display:flex;justify-content:space-between;align-items:baseline;
  gap:8px}
.player-card .name .n{font-size:17px;font-weight:600}
.player-card .name .num{font-size:11.5px;color:var(--dim);font-variant-numeric:tabular-nums}
.player-card .tag{color:var(--dim);font-size:12.5px;margin:4px 0 10px;line-height:1.45}
.player-card .stats{display:flex;gap:14px;font-variant-numeric:tabular-nums;
  font-size:12.5px;color:var(--dim);flex-wrap:wrap}
.player-card .stats b{color:var(--fg);font-weight:600}
.status-pill{display:inline-block;padding:2px 8px;border-radius:99px;
  border:1px solid var(--border);font-size:10.5px;text-transform:uppercase;
  letter-spacing:.06em;font-weight:600;color:var(--dim)}
.status-pill.active{border-color:rgba(63,185,80,.55);color:#7ee787}
.status-pill.standby{border-color:rgba(88,166,255,.55);color:#79c0ff}
.status-pill.retired{border-color:rgba(139,148,158,.55);color:#8b949e}
/* F021: benched gate badge + form guide. Page-local CSS additions --
 * no _BASE_CSS_VERSION bump. */
.status-pill.benched{border-color:rgba(248,81,73,.55);color:#ff9992}
.form-strip{display:inline-flex;gap:3px;font-size:10.5px;font-weight:700;
  font-variant-numeric:tabular-nums;letter-spacing:.02em}
.form-strip .w{color:var(--green)} .form-strip .l{color:var(--red)}
.gate-note{background:rgba(248,81,73,.06);border:1px solid rgba(248,81,73,.35);
  border-left:3px solid var(--red);border-radius:8px;padding:10px 14px;
  margin:0 0 14px;font-size:13px;line-height:1.55}
.gate-note b{color:#ff9992}
.gate-note .stat{color:var(--dim);font-size:12px;margin-top:4px;
  font-variant-numeric:tabular-nums}
.sparkline-box{background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:10px 12px}
.sparkline-box svg{display:block;width:100%;height:48px}
.sparkline-box .cap{font-size:11px;color:var(--dim);margin-top:6px}
.form-meta{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;
  color:var(--dim);margin:10px 0 0;font-variant-numeric:tabular-nums}
.form-meta b{color:var(--fg)}
.form-meta .insufficient{color:var(--amber);font-style:italic}
.player-detail{max-width:960px;margin:0 auto}
.player-header{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:18px 22px;margin-bottom:18px}
.player-header .name-row{display:flex;justify-content:space-between;align-items:baseline;
  gap:12px;flex-wrap:wrap}
.player-header h1{margin:0;font-size:28px;line-height:1.15}
.player-header .num{font-size:14px;color:var(--dim);font-variant-numeric:tabular-nums}
.player-header .tag{color:var(--dim);font-size:14px;margin:6px 0 10px}
.player-header .meta{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;
  color:var(--dim);margin-top:8px}
.player-header .meta b{color:var(--fg);font-weight:600}
.player-header .blurb{margin-top:14px;color:var(--fg);font-size:14px;
  line-height:1.55}
.section{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:16px 18px;margin-bottom:18px}
.section h2{margin:0 0 12px;font-size:15px;letter-spacing:.02em}
.section .prose p{margin:0 0 10px;line-height:1.65;font-size:14px}
.section .prose p:last-child{margin-bottom:0}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media (max-width: 1100px){.stat-grid{grid-template-columns:repeat(3,1fr)}}
@media (max-width: 700px){.stat-grid{grid-template-columns:repeat(2,1fr)}}
@media (max-width: 480px){.stat-grid{grid-template-columns:1fr}}
.stat-tile{background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:10px 12px}
.stat-tile .k{font-size:10.5px;color:var(--dim);text-transform:uppercase;
  letter-spacing:.05em;font-weight:600;margin-bottom:4px}
.stat-tile .v{font-size:18px;font-variant-numeric:tabular-nums;color:var(--fg);
  font-weight:600;line-height:1.1}
.stat-tile .v.ok{color:var(--green)} .stat-tile .v.bad{color:var(--red)}
.setup-diagram{background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:12px 14px;overflow-x:auto}
.setup-diagram pre{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12.5px;line-height:1.35;color:var(--dim);white-space:pre}
.activity-list{list-style:none;padding:0;margin:0}
.activity-list li{display:flex;gap:12px;padding:8px 0;
  border-bottom:1px solid var(--border);font-size:12.5px;
  font-variant-numeric:tabular-nums;color:var(--fg);flex-wrap:wrap}
.activity-list li:last-child{border-bottom:none}
.activity-list .ts{color:var(--dim);min-width:130px}
.activity-list .pnl.ok{color:var(--green)} .activity-list .pnl.bad{color:var(--red)}
.evolution-list{padding-left:20px;margin:0;color:var(--fg);font-size:13.5px;
  line-height:1.6}
.disclaimer{margin-top:12px;padding:14px 16px;background:var(--panel);
  border:1px solid var(--border);border-radius:10px;font-size:12px;
  color:var(--dim);line-height:1.55}
.disclaimer p{margin:0}
.back-link{display:inline-block;margin-bottom:14px;color:var(--dim);
  text-decoration:none;font-size:12.5px}
.back-link:hover{color:var(--accent)}
"""


_PLAYERS_INDEX_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Squad -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
__PLAYERS_CSS__
</style></head>
<body>
__NAV__
<div class="wrap">
  <div class="players-header">
    <h1>The squad</h1>
    <div class="preamble">Ten specialists, one pitch. Each striker owns
    a specific trading playstyle. Click any card to read their bio
    and see what they have done recently.</div>
  </div>
  <div class="source-hint" id="source-hint" style="display:none"></div>
  <div id="grid"></div>
  <div class="disclaimer" role="note">
    <p><b>Blue Lock is a manga / anime by Yusuke Nomura and Muneyuki
    Kaneshiro, published by Kodansha.</b> Characters here are named
    as homage to describe our AI agents' trading playstyles; no
    affiliation, endorsement, or commercial arrangement is claimed.</p>
  </div>
</div>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
function pipSpan(n){
  var cls = n > 0 ? "ok" : (n < 0 ? "bad" : "");
  var sign = n > 0 ? "+" : "";
  return '<b class="'+cls+'">'+sign+n.toFixed(1)+'</b>';
}
function playersSkeleton(box){
  var html = '<div class="players-grid">';
  for(var i=0;i<10;i++){
    html += '<div class="sk-tile"><span class="sk sk-line med"></span>'+
            '<span class="sk sk-line short"></span>'+
            '<span class="sk sk-line"></span></div>';
  }
  html += '</div>';
  box.innerHTML = html;
}
function renderPlayers(data){
  var players = (data && data.players) || [];
  var out = '<div class="players-grid">';
  for(var i=0;i<players.length;i++){
    var p = players[i];
    var cls = "player-card";
    if(p.status === "retired") cls += " retired";
    var sym = (p.symbols || []).join(", ");
    var blurb = p.signature_blurb || p.playstyle_tag || "";
    out += '<a class="'+cls+'" href="/players/'+encodeURIComponent(p.id)+'">';
    out += '<div class="name"><span class="n">'+p.name+'</span>'+
           '<span class="num">Tier '+p.tier+'</span></div>';
    out += '<div class="tag">'+p.playstyle_tag+'</div>';
    out += '<div class="tag" style="margin-top:-6px">'+blurb+'</div>';
    out += '<div class="stats">';
    out += '<span>Props <b>'+(p.proposals|0)+'</b></span>';
    out += '<span>Wins <b>'+(p.wins|0)+'</b></span>';
    out += '<span>Net '+pipSpan(+p.net_pips || 0)+'</span>';
    // F021: gate pill (benched wins over the roster status) + form strip.
    var gate = p.gate || p.status;
    out += '<span class="status-pill '+gate+'">'+gate+'</span>';
    if(p.form){
      var letters = String(p.form).split("-");
      var strip = '';
      for(var k=0;k<letters.length;k++){
        strip += '<span class="'+letters[k].toLowerCase()+'">'+letters[k]+'</span>';
      }
      out += '<span class="form-strip" title="last 5 closed shadow-paper trades">'+strip+'</span>';
    }
    out += '</div>';
    out += '<div class="tag" style="margin-top:8px;font-size:11px">'+sym+'</div>';
    out += '</a>';
  }
  out += '</div>';
  var box = document.getElementById("grid");
  box.innerHTML = out;
  var hint = document.getElementById("source-hint");
  hint.style.display = "";
  hint.innerHTML = '<span class="k">SOURCE</span>' +
    'roster of ' + players.length + ' strikers -- bios shipped in-tree.';
}
function refresh(){
  return withStates(document.getElementById("grid"), function(){
    return fetch("/api/players/list", {cache:"no-store"}).then(function(r){
      if(!r.ok) throw new Error("HTTP "+r.status);
      return r.json();
    });
  }, renderPlayers, {
    skeleton: playersSkeleton,
    isEmpty: function(d){ return !d || !d.players || d.players.length === 0; },
    emptyKey: "no_data_yet",
    emptyMessage: "No strikers available yet."
  });
}
refresh();
setInterval(refresh, 60000);
</script></body></html>"""


_PLAYER_DETAIL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__PLAYER_NAME__ -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
__PLAYERS_CSS__
</style></head>
<body>
__NAV__
<div class="wrap player-detail">
  <a class="back-link" href="/players">&larr; Back to the squad</a>
  <div id="detail"></div>
  <div class="disclaimer" role="note">
    <p><b>Blue Lock is a manga / anime by Yusuke Nomura and Muneyuki
    Kaneshiro, published by Kodansha.</b> Characters here are named
    as homage to describe our AI agents' trading playstyles; no
    affiliation, endorsement, or commercial arrangement is claimed.</p>
  </div>
</div>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
var PLAYER_ID = "__PLAYER_ID__";
function pipSpan(n){
  var cls = n > 0 ? "ok" : (n < 0 ? "bad" : "");
  var sign = n > 0 ? "+" : "";
  return '<b class="'+cls+'">'+sign+n.toFixed(1)+'</b>';
}
function esc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function detailSkeleton(box){
  var html = '<div class="player-header">'+
    '<span class="sk sk-line med"></span>'+
    '<span class="sk sk-line short"></span>'+
    '<span class="sk sk-line"></span></div>'+
    '<div class="section">'+
    '<h2>Career stats</h2>'+
    '<div class="stat-grid">';
  for(var i=0;i<8;i++){
    html += '<div class="sk-tile"><span class="sk sk-line short"></span>'+
            '<span class="sk sk-line"></span></div>';
  }
  html += '</div></div>';
  box.innerHTML = html;
}
function proseHtml(text){
  if(!text) return '<p class="dim">Bio not yet written.</p>';
  var paras = String(text).split(/\n\s*\n/);
  var out = "";
  for(var i=0;i<paras.length;i++){
    var p = paras[i].trim();
    if(p) out += '<p>'+esc(p)+'</p>';
  }
  return out;
}
// F021: inline SVG sparkline -- no chart dependency. `series` is
// [{t, tqs}]; renders a polyline normalised to the value range.
function sparklineSvg(series, label){
  if(!series || series.length < 2) return "";
  var vals = series.map(function(p){ return +p.tqs; });
  var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
  var span = (mx - mn) || 1;
  var W = 260, H = 48, pad = 4;
  var pts = [];
  for(var i=0;i<vals.length;i++){
    var x = pad + (W - 2*pad) * (i / (vals.length - 1));
    var y = H - pad - (H - 2*pad) * ((vals[i] - mn) / span);
    pts.push(x.toFixed(1) + "," + y.toFixed(1));
  }
  return '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" '+
    'role="img" aria-label="'+esc(label)+'">'+
    '<polyline fill="none" stroke="#58a6ff" stroke-width="1.6" points="'+
    pts.join(" ")+'"/></svg>';
}
function renderPlayer(data){
  var s = data.stats || {};
  var gate = data.gate_status || {};
  var gateState = gate.status || data.status;
  var html = '';
  html += '<div class="player-header">';
  html += '<div class="name-row"><h1>'+esc(data.name)+'</h1>'+
    '<span class="num">'+esc(data.canon_player)+'</span></div>';
  html += '<div class="tag">'+esc(data.playstyle_tag)+'</div>';
  html += '<div class="meta">'+
    '<span class="status-pill '+esc(gateState)+'">'+esc(gateState)+'</span>'+
    '<span>Tier <b>'+esc(data.tier)+'</b></span>'+
    '<span>Home TF <b>'+esc(data.home_tf)+'</b></span>'+
    '<span>Symbols <b>'+esc((data.symbols || []).join(", "))+'</b></span>'+
    '<span>Weapon <b>'+esc(data.weapon)+'</b></span>'+
    '</div>';
  if(data.signature_blurb){
    html += '<div class="blurb">'+esc(data.signature_blurb)+'</div>';
  }
  html += '</div>';

  html += '<div class="source-hint"><span class="k">SOURCE</span>'+
          esc(data.source_hint || "")+'</div>';

  // F021: benched gate note -- the honest negative IS the story arc.
  // Reason + headline come from the publication manifest via the API;
  // nothing here is hardcoded prose.
  if(gateState === "benched"){
    html += '<div class="gate-note" role="note"><b>Benched</b> &mdash; '+
            esc(gate.reason || "pre-registered gate FAIL")+'.';
    if(gate.headline_stat){
      html += '<div class="stat">'+esc(gate.headline_stat)+'</div>';
    }
    if(gate.finding_url){
      html += ' <a href="'+esc(gate.finding_url)+
              '">Read the finding &rarr;</a>';
    }
    html += '</div>';
  }

  var netCls = (+s.net_pips > 0) ? "ok" : ((+s.net_pips < 0) ? "bad" : "");
  var netSign = (+s.net_pips > 0) ? "+" : "";
  var bestCls = (+s.best_trade_pips > 0) ? "ok" : "";
  var worstCls = (+s.worst_trade_pips < 0) ? "bad" : "";
  html += '<div class="section"><h2>Career stats</h2><div class="stat-grid">';
  html += '<div class="stat-tile"><div class="k">Proposals</div>'+
          '<div class="v">'+(s.proposals|0)+'</div></div>';
  html += '<div class="stat-tile"><div class="k">Trades</div>'+
          '<div class="v">'+(s.trades|0)+'</div></div>';
  html += '<div class="stat-tile"><div class="k">Wins</div>'+
          '<div class="v ok">'+(s.wins|0)+'</div></div>';
  html += '<div class="stat-tile"><div class="k">Win rate</div>'+
          '<div class="v">'+((+s.win_rate_pct||0).toFixed(1))+'%</div></div>';
  html += '<div class="stat-tile"><div class="k">Net pips</div>'+
          '<div class="v '+netCls+'">'+netSign+((+s.net_pips||0).toFixed(1))+'</div></div>';
  html += '<div class="stat-tile"><div class="k">Avg pips</div>'+
          '<div class="v">'+((+s.avg_pips||0).toFixed(2))+'</div></div>';
  html += '<div class="stat-tile"><div class="k">Best trade</div>'+
          '<div class="v '+bestCls+'">'+((+s.best_trade_pips||0).toFixed(1))+'p</div></div>';
  html += '<div class="stat-tile"><div class="k">Worst trade</div>'+
          '<div class="v '+worstCls+'">'+((+s.worst_trade_pips||0).toFixed(1))+'p</div></div>';
  html += '<div class="stat-tile"><div class="k">Best pair</div>'+
          '<div class="v">'+esc(s.best_pair || "-")+'</div></div>';
  html += '<div class="stat-tile"><div class="k">Days active</div>'+
          '<div class="v">'+(s.days_active|0)+'</div></div>';
  html += '</div></div>';

  // F021: form guide -- rolling TQS sparkline + windowed win-rate.
  // Small-sample honesty: below fg.min_sample closed trades the
  // win-rate is withheld and the explicit note renders instead.
  var fg = data.form_guide;
  if(fg){
    html += '<div class="section"><h2>Form guide</h2>';
    if(fg.sample_size === 0){
      html += '<p class="dim">No closed shadow-paper trades on tape '+
              'yet. The form guide starts with the first close.</p>';
    } else {
      if(fg.tqs_series && fg.tqs_series.length >= 2){
        html += '<div class="sparkline-box">'+
          sparklineSvg(fg.tqs_series, "TQS sparkline, "+fg.window_label)+
          '<div class="cap">TQS per closed trade &middot; '+
          esc(fg.window_label)+'</div></div>';
      }
      html += '<div class="form-meta">';
      if(fg.win_rate_pct == null){
        html += '<span class="insufficient">'+esc(fg.note ||
          "insufficient sample (n="+fg.sample_size+")")+
          ' &mdash; win-rate withheld below '+fg.min_sample+' closes</span>';
      } else {
        html += '<span>Win rate <b>'+fg.win_rate_pct.toFixed(1)+
                '%</b> ('+esc(fg.window_label)+')</span>';
      }
      if(fg.form){
        html += '<span>Form <b>'+esc(fg.form)+'</b></span>';
      }
      html += '<span>Net (window) <b>'+
              (+fg.net_pips_window).toFixed(1)+'p</b></span>';
      html += '<span>Sample <b>n='+fg.sample_size+'</b></span>';
      html += '</div>';
    }
    html += '</div>';
  }

  html += '<div class="section"><h2>Playstyle</h2>'+
          '<div class="prose">'+proseHtml(data.playstyle_prose)+'</div></div>';

  if(data.signature_setup){
    html += '<div class="section"><h2>Signature setup</h2>'+
            '<div class="setup-diagram" role="img" aria-label="'+
            esc(data.playstyle_tag)+' signature setup">'+
            '<pre>'+esc(stripFence(data.signature_setup))+'</pre></div></div>';
  }

  var activity = data.recent_activity || [];
  html += '<div class="section"><h2>Recent activity</h2>';
  if(activity.length === 0){
    html += '<p class="dim">No recent activity yet.</p>';
  } else {
    html += '<ul class="activity-list">';
    for(var i=0;i<activity.length;i++){
      var a = activity[i];
      html += '<li><span class="ts">'+esc(a.t)+'</span>'+
              '<span>'+esc(a.type)+'</span>'+
              '<span>'+esc(a.symbol || "")+'</span>';
      if(a.dir) html += '<span>'+esc(a.dir)+'</span>';
      if(a.pnl_pips !== undefined){
        var cls = a.pnl_pips > 0 ? "ok" : (a.pnl_pips < 0 ? "bad" : "");
        var sign = a.pnl_pips > 0 ? "+" : "";
        html += '<span class="pnl '+cls+'">'+sign+
                a.pnl_pips.toFixed(1)+'p</span>';
      }
      html += '</li>';
    }
    html += '</ul>';
  }
  html += '</div>';

  html += '<div class="section"><h2>Evolution history</h2>';
  var evo = data.evolution || [];
  if(evo.length === 0){
    html += '<p class="dim">No evolution recorded yet.</p>';
  } else {
    html += '<ul class="evolution-list">';
    for(var i=0;i<evo.length;i++){
      html += '<li>'+esc(evo[i].note)+'</li>';
    }
    html += '</ul>';
  }
  html += '</div>';

  document.getElementById("detail").innerHTML = html;
}
function stripFence(s){
  s = String(s).replace(/^```[a-zA-Z]*\s*\n?/, "").replace(/\n?```\s*$/,"");
  return s;
}
function refresh(){
  return withStates(document.getElementById("detail"), function(){
    return fetch("/api/players/" + encodeURIComponent(PLAYER_ID),
                 {cache:"no-store"}).then(function(r){
      if(!r.ok) throw new Error("HTTP "+r.status);
      return r.json();
    });
  }, renderPlayer, {
    skeleton: detailSkeleton,
    isEmpty: function(d){ return !d || !d.id; },
    emptyKey: "no_data_yet",
    emptyMessage: "This striker has no live data yet."
  });
}
refresh();
setInterval(refresh, 60000);
</script></body></html>"""


PLAYERS_INDEX_PAGE = (_PLAYERS_INDEX_TEMPLATE
                      .replace("__BASE_CSS__", _BASE_CSS)
                      .replace("__SKELETON_CSS__", _SKELETON_CSS)
                      .replace("__PLAYERS_CSS__", _PLAYERS_CSS)
                      .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                      .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                      .replace("__NAV__", nav('players')))


def player_detail_page(player_id: str, player_name: str) -> str:
    """Return the /players/<id> detail page with per-player title +
    pinned PLAYER_ID constant embedded. ``player_id`` is trusted (the
    route handler is expected to normalise it via
    ``agent.platform.players.normalize_id`` before this call).

    ``player_name`` is the display-cased name (e.g. ``"Isagi"``);
    the callee uses it only in the browser <title>.
    """
    safe_id = str(player_id or "").replace('"', '').replace("'", "")
    safe_name = str(player_name or "").replace("<", "").replace(">", "")
    return (_PLAYER_DETAIL_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__SKELETON_CSS__", _SKELETON_CSS)
            .replace("__PLAYERS_CSS__", _PLAYERS_CSS)
            .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
            .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
            .replace("__NAV__", nav('players'))
            .replace("__PLAYER_ID__", safe_id)
            .replace("__PLAYER_NAME__", safe_name))


_PLAYERS_404_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Striker not found -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__PLAYERS_CSS__
.notfound{max-width:640px;margin:60px auto;padding:24px}
.notfound h1{margin:0 0 12px;font-size:22px}
.notfound p{color:var(--dim);line-height:1.55}
.notfound .known{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
.notfound .known a{background:var(--panel);border:1px solid var(--border);
  padding:6px 12px;border-radius:6px;color:var(--fg);text-decoration:none;
  font-size:12.5px}
.notfound .known a:hover{border-color:var(--accent)}
</style></head>
<body>
__NAV__
<div class="wrap notfound">
  <h1>Striker not found</h1>
  <p>The URL you followed does not match any of our ten strikers.
  Here is the full squad:</p>
  <div class="known">__KNOWN_LINKS__</div>
  <p><a href="/players">&larr; Back to the squad index</a></p>
</div>
</body></html>"""


def players_not_found_page(known_ids: list[str]) -> str:
    """Return the 404 shell listing the ten valid striker slugs.

    ``known_ids`` is the sequence to render as links, in roster order.
    The template does not depend on ``pages.py``'s knowledge of the
    roster -- the caller supplies it so a future rename of the roster
    module doesn't recouple this file to it.
    """
    ids = list(known_ids) if known_ids else []
    if not ids:
        links = '<span class="dim">roster unavailable</span>'
    else:
        links = "".join(
            '<a href="/players/{i}">{i}</a>'.format(i=x) for x in ids
        )
    return (_PLAYERS_404_TEMPLATE
            .replace("__BASE_CSS__", _BASE_CSS)
            .replace("__PLAYERS_CSS__", _PLAYERS_CSS)
            .replace("__NAV__", nav('players'))
            .replace("__KNOWN_LINKS__", links))


# ---------------------------------------------------------------------------
# F003 -- /research verdict timeline
# ---------------------------------------------------------------------------
#
# Read-only view over the CPO-gated publication manifest. Every entry on
# this page has been explicitly allow-listed in
# company/research/publication_manifest.json (D007). Backend parses more
# than what appears here; publication requires a manual CPO signoff row.
#
# The page reuses F001/F002 primitives (.source-hint, .disclaimer,
# .kpi-tile via the headline-stat block) and adds two F003-owned
# primitives: .verdict-card and .date-header (sticky month heading).
# The FDR explainer is a native <details> block -- keyboard-toggleable,
# accessible, and it degrades gracefully when JS is off.

_RESEARCH_CSS = r"""
.research-header{margin-bottom:18px}
.research-header h1{margin:0 0 6px;font-size:22px}
.research-header .preamble{color:var(--dim);font-size:13.5px;line-height:1.55;
  max-width:820px}
.research-header .signoff{margin-top:8px;font-size:12px;color:var(--dim)}
.date-header{position:sticky;top:0;background:var(--bg);
  padding:10px 0 6px;margin:22px 0 10px;border-bottom:1px solid var(--border);
  font-size:13px;font-weight:600;letter-spacing:.03em;color:var(--dim);
  text-transform:uppercase;z-index:2}
.verdict-card{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:16px 18px;margin-bottom:14px}
.verdict-card .top{display:flex;align-items:baseline;flex-wrap:wrap;gap:10px;
  margin-bottom:8px}
.verdict-card .top .title{font-size:16px;font-weight:600;color:var(--fg);
  line-height:1.3}
.verdict-card .top .date{font-size:12px;color:var(--dim);
  font-variant-numeric:tabular-nums;margin-left:auto}
.verdict-card .cid{font-size:11.5px;color:var(--dim);margin-bottom:8px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.verdict-card .summary{font-size:13.5px;line-height:1.6;color:var(--fg);
  margin:0 0 12px}
.verdict-card .headline{background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:10px 12px;font-size:12.5px;color:var(--fg);
  font-variant-numeric:tabular-nums;margin:0 0 10px}
.verdict-card .headline .k{color:var(--dim);text-transform:uppercase;
  font-size:10.5px;letter-spacing:.05em;font-weight:600;margin-right:8px}
.verdict-card .link{font-size:12.5px}
.verdict-card .link a{color:var(--accent);text-decoration:none}
.verdict-card .link a:hover{text-decoration:underline}
.verdict-pill{display:inline-block;padding:2px 10px;border-radius:99px;
  border:1px solid var(--border);font-size:10.5px;text-transform:uppercase;
  letter-spacing:.06em;font-weight:600;color:var(--dim)}
.verdict-pill.alive_survivor,.verdict-pill.pass,.verdict-pill.pass_thin,
.verdict-pill.combined_alive{border-color:rgba(63,185,80,.55);color:#7ee787}
.verdict-pill.complete,.verdict-pill.stage_1_complete,
.verdict-pill.in_progress{border-color:rgba(88,166,255,.55);color:#79c0ff}
.verdict-pill.dead,.verdict-pill.fail{border-color:rgba(248,81,73,.55);
  color:#ff9992}
.verdict-pill.stopped,.verdict-pill.stopped_at_stage_1,
.verdict-pill.parked,.verdict-pill.parked_low_yield,
.verdict-pill.unknown{border-color:rgba(139,148,158,.55);color:#8b949e}
.fdr-explainer{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:12px 16px;margin:22px 0 14px}
.fdr-explainer summary{cursor:pointer;color:var(--fg);font-size:13.5px;
  font-weight:600;list-style:none}
.fdr-explainer summary::-webkit-details-marker{display:none}
.fdr-explainer summary::before{content:"▸ ";color:var(--dim)}
.fdr-explainer[open] summary::before{content:"▾ ";color:var(--dim)}
.fdr-explainer .body{margin-top:10px;color:var(--fg);font-size:13px;
  line-height:1.6}
.fdr-explainer .body p{margin:0 0 8px}
.fdr-explainer .body p:last-child{margin:0}
@media (max-width: 700px){
  .verdict-card .top{align-items:flex-start;flex-direction:column}
  .verdict-card .top .date{margin-left:0}
}
"""


_RESEARCH_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research verdicts -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
__RESEARCH_CSS__
</style></head>
<body>
__NAV__
<div class="wrap">
  <div class="research-header">
    <h1>Research verdicts</h1>
    <div class="preamble">We publish the experiments that failed.
    This is the receipt trail for the ones that worked -- and the
    ones that didn't. Every verdict below was pre-registered before
    the numbers came in; no cherry-picks, no back-fills.</div>
    <div class="signoff" id="signoff"></div>
  </div>
  <div class="source-hint" id="source-hint" style="display:none"></div>
  <div id="timeline"></div>

  <details class="fdr-explainer">
    <summary>How pre-registration and BH-FDR keep us honest</summary>
    <div class="body">
      <p><b>Pre-registration</b> means the verdict criteria are
      written down (in a PROTOCOL.md file) before the numbers come
      in. If we don't hit the pre-committed number, the campaign is
      dead. No follow-up "we found something interesting instead"
      story -- the stopped and dead entries on this page exist
      precisely because a pre-registered rule was triggered.</p>
      <p><b>BH-FDR at q = 0.10</b> means the Benjamini-Hochberg
      false-discovery-rate correction is applied across each
      campaign's family of hypotheses. If we test 8 candidate
      widenings and 1 comes back significant at the raw p-value,
      BH-FDR asks whether that one is likely a real effect or a
      lucky coincidence given the eight tries. Many candidates
      pass raw p-values and fail BH-FDR -- and that is a feature of
      the method, not a bug.</p>
      <p>The "dead" and "fail" cards on this page are the receipt
      trail. Read them first if you want to trust the "alive" ones.</p>
    </div>
  </details>

  <div class="disclaimer" role="note" id="verdict-disclaimer">
    <p>Every verdict below is the result of a pre-registered
    experiment on historical market data. "Alive" and "dead" refer
    to whether a mechanism passed the study's specific promotion
    criteria -- not to whether it would work on future markets.
    False-discovery-rate corrections are applied across each
    experiment family; individual "alive" verdicts do not compose
    into a portfolio-level claim.</p>
  </div>
</div>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
function esc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function monthLabelFromDate(d){
  var m = String(d).match(/(\d{4})-(\d{2})/);
  if(!m) return "Undated";
  var monthNames = ["January","February","March","April","May","June",
                    "July","August","September","October","November","December"];
  var y = m[1], mo = parseInt(m[2],10)-1;
  return monthNames[mo] + " " + y;
}
function pillClass(kind){
  var known = ["alive_survivor","pass","pass_thin","combined_alive",
               "complete","stage_1_complete","in_progress",
               "dead","fail",
               "stopped","stopped_at_stage_1","parked","parked_low_yield",
               "unknown"];
  return known.indexOf(kind) >= 0 ? kind : "unknown";
}
function researchSkeleton(box){
  var html = '';
  for(var i=0;i<3;i++){
    html += '<div class="sk-tile" style="min-height:120px;margin-bottom:14px">'+
            '<span class="sk sk-line short"></span>'+
            '<span class="sk sk-line med"></span>'+
            '<span class="sk sk-line"></span>'+
            '<span class="sk sk-line"></span></div>';
  }
  box.innerHTML = html;
}
function renderResearch(data){
  var entries = (data && data.entries) || [];
  var out = '';
  var lastMonth = null;
  for(var i=0;i<entries.length;i++){
    var e = entries[i];
    var monthLabel = monthLabelFromDate(e.date || "");
    if(monthLabel !== lastMonth){
      out += '<div class="date-header">'+esc(monthLabel)+'</div>';
      lastMonth = monthLabel;
    }
    var kind = pillClass(e.verdict_kind);
    out += '<article class="verdict-card">';
    out += '<div class="top">';
    out += '<span class="verdict-pill '+kind+'">'+esc(e.verdict_label || kind)+'</span>';
    out += '<span class="title">'+esc(e.title || e.campaign_id || "")+'</span>';
    out += '<span class="date">'+esc(e.date || "")+'</span>';
    out += '</div>';
    out += '<div class="cid">'+esc(e.campaign_id || "")+'</div>';
    if(e.summary){
      out += '<p class="summary">'+esc(e.summary)+'</p>';
    }
    if(e.headline_stat){
      out += '<div class="headline"><span class="k">HEADLINE</span>'+
             esc(e.headline_stat)+'</div>';
    }
    if(e.report_path){
      out += '<div class="link"><a href="#" data-path="'+esc(e.report_path)+
             '" onclick="return false;">read full report ('+
             esc(e.report_path)+') &rarr;</a></div>';
    }
    out += '</article>';
  }
  document.getElementById("timeline").innerHTML = out;

  var hint = document.getElementById("source-hint");
  hint.style.display = "";
  var head = "<span class='k'>SOURCE</span>";
  if(data.source_exists){
    hint.innerHTML = head + esc(data.published_total) + " of " +
      esc(data.all_candidates) + " candidate reports published.";
  } else {
    hint.innerHTML = head + "Research repo not on this machine -- " +
      "see docs/RUNBOOK_demo_launch.md for setup.";
  }
  var sign = document.getElementById("signoff");
  if(data.cpo_signoff_by){
    sign.innerHTML = "&#x25B8; Approved for publication by " +
      esc(data.cpo_signoff_by) + " &middot; " +
      esc(data.cpo_signoff_at || "");
  } else {
    sign.innerHTML = "&#x25B8; Publication manifest not signed off yet.";
  }
}
function refresh(){
  return withStates(document.getElementById("timeline"), function(){
    return fetch("/api/research/verdicts", {cache:"no-store"}).then(function(r){
      if(!r.ok) throw new Error("HTTP "+r.status);
      return r.json();
    });
  }, renderResearch, {
    skeleton: researchSkeleton,
    isEmpty: function(d){ return !d || !d.entries || d.entries.length === 0; },
    emptyKey: (d) => (d && d.unconfigured) ? "not_configured" : "no_data_yet",
    emptyMessage: function(d){
      if(d && d.unconfigured){
        return "The publication manifest is not on tape yet. " +
          "CPO signoff pending.";
      }
      if(d && !d.source_exists){
        return "Research repo not configured on this machine. " +
          "See docs/RUNBOOK_demo_launch.md \u00A77b.";
      }
      return "No published verdicts yet.";
    }
  });
}
refresh();
setInterval(refresh, 60000);
</script></body></html>"""


RESEARCH_PAGE = (_RESEARCH_TEMPLATE
                 .replace("__BASE_CSS__", _BASE_CSS)
                 .replace("__SKELETON_CSS__", _SKELETON_CSS)
                 .replace("__RESEARCH_CSS__", _RESEARCH_CSS)
                 .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                 .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                 .replace("__NAV__", nav('research')))


# ---------------------------------------------------------------------------
# F020 -- /highlights match reports
# ---------------------------------------------------------------------------
#
# Daily match reports auto-derived from the shadow-paper tape by
# agent/platform/highlights.py. Deterministic templating only -- every
# line click-traces to recorded events. All CSS is page-local
# (_HIGHLIGHTS_CSS) so _BASE_CSS_VERSION does not bump.

_HIGHLIGHTS_CSS = r"""
.hl-header{margin-bottom:16px}
.hl-header .preamble{color:var(--dim);font-size:13.5px;line-height:1.55;
  max-width:820px}
.hl-provenance{margin:0 0 16px;padding:10px 14px;background:var(--panel);
  border:1px solid var(--border);border-left:3px solid var(--amber);
  border-radius:8px;font-size:12px;color:var(--dim);line-height:1.55}
.hl-provenance .k{color:var(--amber);text-transform:uppercase;
  font-size:10.5px;letter-spacing:.05em;font-weight:700;margin-right:8px}
.hl-index{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
  gap:12px;margin-bottom:20px}
.hl-day-card{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:12px 14px;cursor:pointer;text-align:left;
  color:var(--fg);font:inherit;line-height:1.5}
.hl-day-card:hover{border-color:var(--accent)}
.hl-day-card.sel{border-color:var(--accent);
  box-shadow:0 0 0 1px var(--accent) inset}
.hl-day-card .d{font-weight:700;font-variant-numeric:tabular-nums;
  margin-bottom:4px}
.hl-day-card .h{font-size:12.5px;color:var(--dim)}
.hl-day-card .h.quiet{font-style:italic}
.hl-report{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:16px 18px;margin-bottom:18px}
.hl-report .headline{font-size:16px;font-weight:600;margin-bottom:10px}
.hl-report .quiet-note{color:var(--dim);font-style:italic;font-size:13px;
  margin-bottom:10px}
.hl-ft{display:flex;flex-wrap:wrap;gap:8px 18px;background:var(--bg);
  border:1px solid var(--border);border-radius:8px;padding:10px 12px;
  font-size:12.5px;font-variant-numeric:tabular-nums;margin-bottom:12px}
.hl-ft .k{color:var(--dim);margin-right:5px}
.hl-line{display:grid;grid-template-columns:max-content 1fr;gap:10px;
  padding:5px 0;border-bottom:1px solid #1c2129;font-size:13px;
  align-items:baseline}
.hl-line:last-child{border-bottom:none}
.hl-line .t{color:var(--dim);font-variant-numeric:tabular-nums;
  white-space:nowrap;font-size:11.5px}
.hl-line.goal .txt{color:var(--green)}
.hl-line.miss .txt{color:var(--red)}
.hl-players{width:100%;border-collapse:collapse;font-size:12.5px;
  margin-top:12px;font-variant-numeric:tabular-nums}
.hl-players th{text-align:left;color:var(--dim);font-size:10.5px;
  text-transform:uppercase;letter-spacing:.05em;padding:4px 8px 4px 0;
  border-bottom:1px solid var(--border)}
.hl-players td{padding:5px 8px 5px 0;border-bottom:1px solid #1c2129}
.hl-players tr:last-child td{border-bottom:none}
@media (max-width: 700px){
  .hl-index{grid-template-columns:1fr}
  .hl-ft{gap:6px 12px}
  .hl-players{display:block;overflow-x:auto}
}
"""

_HIGHLIGHTS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Match highlights -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
__HIGHLIGHTS_CSS__
</style></head>
<body>
__NAV__
<div class="hl-header">
  <h1>Match highlights</h1>
  <div class="preamble">Every day the squad plays, the tape writes the
  match report. Each line below is derived from recorded events --
  nothing is retold that didn't happen. Tomorrow's match hasn't been
  written yet.</div>
</div>
<div class="hl-provenance" role="note"><span class="k">Provenance</span>
<span id="hl-provenance-text">Shadow-paper activity and quality metrics
from the v2 squad (demo data feed, no orders sent to any broker)
&mdash; NOT profit performance. Past activity is not indicative of
future results.</span></div>
<div id="hl-index"></div>
<div id="hl-report"></div>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
function hesc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function fetchJson(url){
  return fetch(url, {cache:"no-store"}).then(function(r){
    if(!r.ok) throw new Error("HTTP "+r.status);
    return r.json();
  });
}
var selectedDay = null;
function renderFullTime(ft){
  if(!ft) return "";
  var cells = [
    ["Shots", ft.shots], ["On target", ft.on_target],
    ["Tackles", ft.tackles], ["Goals", ft.goals],
    ["Misses", ft.misses], ["Net pips", ft.net_pips],
    ["Net R", ft.net_r == null ? "\u2014" : ft.net_r],
    ["Mean TQS", ft.mean_tqs == null ? "\u2014" : ft.mean_tqs],
    ["Bars evaluated", ft.ticks_evaluated]
  ];
  var out = '<div class="hl-ft">';
  for(var i=0;i<cells.length;i++){
    out += '<span><span class="k">'+hesc(cells[i][0])+'</span>'+
           hesc(cells[i][1])+'</span>';
  }
  return out + '</div>';
}
function renderReport(data, box){
  if(!data || data.empty) return "empty";
  var out = '<article class="hl-report">';
  out += '<div class="headline">'+hesc(data.headline)+'</div>';
  if(data.quiet && data.quiet_note){
    out += '<div class="quiet-note">'+hesc(data.quiet_note)+'</div>';
  }
  out += renderFullTime(data.full_time);
  var tl = data.timeline || [];
  for(var i=0;i<tl.length;i++){
    var ev = tl[i];
    var cls = "";
    if(ev.type === "close"){
      cls = (typeof ev.pnl_pips === "number" && ev.pnl_pips > 0)
        ? " goal" : " miss";
    }
    out += '<div class="hl-line'+cls+'">'+
           '<span class="t">'+hesc((ev.t||"").slice(11,16))+'</span>'+
           '<span class="txt">'+hesc(ev.line)+'</span></div>';
  }
  var pl = data.players || [];
  if(pl.length){
    out += '<table class="hl-players"><tr><th>Player</th><th>Shots</th>'+
           '<th>Tackled</th><th>On target</th><th>Resolved</th>'+
           '<th>Goals</th><th>Net pips</th></tr>';
    for(var j=0;j<pl.length;j++){
      var p = pl[j];
      out += '<tr><td>'+hesc(p.name)+'</td><td>'+hesc(p.shots)+'</td>'+
             '<td>'+hesc(p.tackled)+'</td><td>'+hesc(p.opens)+'</td>'+
             '<td>'+hesc(p.resolved)+'</td><td>'+hesc(p.goals)+'</td>'+
             '<td>'+hesc(p.net_pips)+'</td></tr>';
    }
    out += '</table>';
  }
  out += '</article>';
  box.innerHTML = out;
  if(data.provenance){
    document.getElementById("hl-provenance-text").textContent =
      data.provenance;
  }
}
function loadReport(day){
  selectedDay = day;
  var cards = document.querySelectorAll(".hl-day-card");
  for(var i=0;i<cards.length;i++){
    cards[i].classList.toggle("sel", cards[i].dataset.day === day);
  }
  return withStates(document.getElementById("hl-report"), function(){
    return fetchJson("/api/highlights/report/"+encodeURIComponent(day));
  }, renderReport, {
    emptyMessage: "No tape on record for "+day+"."
  });
}
function renderIndex(data, box){
  var reports = (data && data.reports) || [];
  if(!reports.length) return "empty";
  var out = '<div class="hl-index">';
  for(var i=0;i<reports.length;i++){
    var r = reports[i];
    out += '<button type="button" class="hl-day-card" data-day="'+
           hesc(r.day)+'"><span class="d">'+hesc(r.day)+'</span>'+
           '<span class="h'+(r.quiet ? " quiet" : "")+'">'+
           hesc(r.headline)+'</span></button>';
  }
  out += '</div>';
  box.innerHTML = out;
  var cards = box.querySelectorAll(".hl-day-card");
  for(var j=0;j<cards.length;j++){
    cards[j].addEventListener("click", function(){
      loadReport(this.dataset.day);
    });
  }
  loadReport(selectedDay || reports[0].day);
}
withStates(document.getElementById("hl-index"), function(){
  return fetchJson("/api/highlights/reports?n=14");
}, renderIndex, {
  emptyMessage: "No match days on tape yet \u2014 the squad is " +
    "watching the market. Come back after the next H4 bar close."
});
</script></body></html>"""

HIGHLIGHTS_PAGE = (_HIGHLIGHTS_TEMPLATE
                   .replace("__BASE_CSS__", _BASE_CSS)
                   .replace("__SKELETON_CSS__", _SKELETON_CSS)
                   .replace("__HIGHLIGHTS_CSS__", _HIGHLIGHTS_CSS)
                   .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                   .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                   .replace("__NAV__", nav('highlights')))


# ---------------------------------------------------------------------------
# F022 -- /leaderboard standings page (Sprint 3)
# ---------------------------------------------------------------------------
#
# Per-agent / per-pair standings computed on read by
# agent/platform/leaderboard.py. Internal squad standings on a demo
# feed -- rankings are activity/quality metrics, not investment
# performance, and the header says so. All CSS is page-local
# (_LEADERBOARD_CSS) so _BASE_CSS_VERSION does not bump.

_LEADERBOARD_CSS = r"""
.lb-header{margin-bottom:16px}
.lb-header .preamble{color:var(--dim);font-size:13.5px;line-height:1.55;
  max-width:820px}
.lb-provenance{margin:0 0 16px;padding:10px 14px;background:var(--panel);
  border:1px solid var(--border);border-left:3px solid var(--amber);
  border-radius:8px;font-size:12px;color:var(--dim);line-height:1.55}
.lb-provenance .k{color:var(--amber);text-transform:uppercase;
  font-size:10.5px;letter-spacing:.05em;font-weight:700;margin-right:8px}
.lb-toggles{display:flex;flex-wrap:wrap;gap:8px 18px;margin-bottom:14px}
.lb-toggle-group{display:flex;gap:6px;align-items:center}
.lb-toggle-group .lbl{color:var(--dim);font-size:11px;
  text-transform:uppercase;letter-spacing:.05em;margin-right:2px}
.lb-toggle{padding:4px 12px;border:1px solid var(--border);
  border-radius:999px;background:none;color:var(--fg);cursor:pointer;
  font:inherit;font-size:12.5px;line-height:1.5}
.lb-toggle.on{background:var(--panel);border-color:var(--accent)}
.lb-window-note{color:var(--dim);font-size:12px;margin-bottom:10px}
.lb-table{width:100%;border-collapse:collapse;font-size:13px;
  font-variant-numeric:tabular-nums;background:var(--panel);
  border:1px solid var(--border);border-radius:10px;overflow:hidden}
.lb-table th{text-align:left;color:var(--dim);font-size:10.5px;
  text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;
  border-bottom:1px solid var(--border)}
.lb-table td{padding:7px 10px;border-bottom:1px solid #1c2129}
.lb-table tr:last-child td{border-bottom:none}
.lb-table .rank{color:var(--dim);width:36px}
.lb-table .pos-r{color:var(--green)} .lb-table .neg-r{color:var(--red)}
.lb-table .nrule{color:var(--dim);font-style:italic}
@media (max-width: 700px){
  .lb-toggles{gap:6px 12px}
  .lb-table-wrap{overflow-x:auto}
  .lb-table{min-width:560px}
}
"""

_LEADERBOARD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Standings -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
__LEADERBOARD_CSS__
</style></head>
<body>
__NAV__
<div class="lb-header">
  <h1>Standings</h1>
  <div class="preamble">The league table the tape writes: which
  striker is in form, which pair has been kindest to the squad.
  Rankings move as the shadow window accrues -- internal squad
  standings only, one install ranked within itself.</div>
</div>
<div class="lb-provenance" role="note"><span class="k">Provenance</span>
<span id="lb-provenance-text">Internal squad standings on a demo feed
&mdash; shadow-paper activity and quality metrics from the v2 squad
(no orders sent to any broker), NOT investment performance. No
comparison against any external benchmark is implied. Past activity
is not indicative of future results.</span></div>
<div class="lb-toggles">
  <div class="lb-toggle-group" id="lb-by-group">
    <span class="lbl">Rank by</span>
    <button type="button" class="lb-toggle on" data-by="agent">Strikers</button>
    <button type="button" class="lb-toggle" data-by="pair">Pairs</button>
  </div>
  <div class="lb-toggle-group" id="lb-window-group">
    <span class="lbl">Window</span>
    <button type="button" class="lb-toggle on" data-window="all">All time</button>
    <button type="button" class="lb-toggle" data-window="30">30 days</button>
    <button type="button" class="lb-toggle" data-window="7">7 days</button>
  </div>
</div>
<div id="lb-window-note" class="lb-window-note"></div>
<div id="lb-table"></div>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
function lesc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function fetchJson(url){
  return fetch(url, {cache:"no-store"}).then(function(r){
    if(!r.ok) throw new Error("HTTP "+r.status);
    return r.json();
  });
}
var state = {by: "agent", win: "all"};
function fmtR(v){
  if(typeof v !== "number") return "\u2014";
  return (v > 0 ? "+" : "") + v.toFixed(2) + "R";
}
function renderTable(data, box){
  var rows = (data && data.rows) || [];
  document.getElementById("lb-window-note").textContent =
    "Window: " + (data.window_label || "") + " \u00b7 " +
    (data.total_closed || 0) + " closed shadow-paper trade(s) in scope.";
  if(data.provenance){
    document.getElementById("lb-provenance-text").textContent =
      data.provenance;
  }
  if(!rows.length) return "empty";
  var head = state.by === "pair" ? "Pair" : "Striker";
  var out = '<div class="lb-table-wrap"><table class="lb-table"><tr>'+
    '<th>#</th><th>'+lesc(head)+'</th><th>Closed</th><th>Cum R</th>'+
    '<th>Mean TQS</th><th>Win rate</th><th>Last active</th></tr>';
  for(var i=0;i<rows.length;i++){
    var r = rows[i];
    var name = r.player_id
      ? '<a href="/players/'+lesc(r.player_id)+'">'+lesc(r.name)+'</a>'
      : lesc(r.name);
    var rCls = (typeof r.cum_r === "number" && r.cum_r !== 0)
      ? (r.cum_r > 0 ? ' class="pos-r"' : ' class="neg-r"') : "";
    var winCell = r.insufficient_sample
      ? '<span class="nrule">'+lesc(r.note || ("n="+r.closed_trades))+'</span>'
      : lesc(r.win_rate_pct) + "%";
    out += '<tr><td class="rank">'+lesc(r.rank)+'</td>'+
      '<td>'+name+'</td>'+
      '<td>'+lesc(r.closed_trades)+'</td>'+
      '<td'+rCls+'>'+lesc(fmtR(r.cum_r))+'</td>'+
      '<td>'+(r.mean_tqs == null ? "\u2014" : lesc(r.mean_tqs))+'</td>'+
      '<td>'+winCell+'</td>'+
      '<td>'+lesc((r.last_active||"").slice(0,16).replace("T"," ")||"\u2014")+
      '</td></tr>';
  }
  out += '</table></div>';
  box.innerHTML = out;
}
function load(){
  var win = state.win === "all" ? "" : state.win;
  return withStates(document.getElementById("lb-table"), function(){
    return fetchJson("/api/leaderboard?by="+encodeURIComponent(state.by)+
                     "&window="+encodeURIComponent(win));
  }, renderTable, {
    emptyMessage: "No closed shadow-paper trades on tape for this " +
      "window yet \u2014 standings appear after the first close."
  });
}
function wireToggles(groupId, attr, key){
  var group = document.getElementById(groupId);
  group.addEventListener("click", function(e){
    var btn = e.target.closest(".lb-toggle");
    if(!btn) return;
    state[key] = btn.dataset[attr];
    var btns = group.querySelectorAll(".lb-toggle");
    for(var i=0;i<btns.length;i++){
      btns[i].classList.toggle("on", btns[i] === btn);
    }
    load();
  });
}
wireToggles("lb-by-group", "by", "by");
wireToggles("lb-window-group", "window", "win");
load();
</script></body></html>"""

LEADERBOARD_PAGE = (_LEADERBOARD_TEMPLATE
                    .replace("__BASE_CSS__", _BASE_CSS)
                    .replace("__SKELETON_CSS__", _SKELETON_CSS)
                    .replace("__LEADERBOARD_CSS__", _LEADERBOARD_CSS)
                    .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                    .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                    .replace("__NAV__", nav('leaderboard')))


# ---------------------------------------------------------------------------
# F007 -- Broker connection wizard at /settings/broker
# ---------------------------------------------------------------------------
#
# Multi-step wizard: account type -> credentials -> (live confirmation)
# -> test connection -> save. Uses F005 withStates() for the in-flight
# spinner during test-connection. Copy tokens live in copy.md \u00a7F007.
# All new primitives (.wiz-step / .wiz-radio-card / .wiz-form / etc.)
# are additive; _BASE_CSS_VERSION does not bump (patch would apply if
# we later need visual tokens).

_BROKER_CSS = r"""
.wiz{max-width:640px;margin:0 auto}
.wiz-step{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:20px 22px;margin-bottom:14px}
.wiz-step h2{margin:0 0 6px;font-size:16px}
.wiz-step .lead{color:var(--dim);font-size:13px;margin:0 0 14px}
.wiz-radio-card{border:1px solid var(--border);border-radius:8px;
  padding:12px 14px;margin-bottom:10px;cursor:pointer;background:#0f141a}
.wiz-radio-card:hover{border-color:var(--accent)}
.wiz-radio-card.selected{border-color:var(--accent);
  box-shadow:0 0 0 1px var(--accent) inset}
.wiz-radio-card .label{font-weight:600;font-size:14px}
.wiz-radio-card .sub{color:var(--dim);font-size:12px;margin-top:4px}
.wiz-form{display:grid;gap:10px}
.wiz-form label{display:block;font-size:12px;color:var(--dim);
  text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}
.wiz-form input,.wiz-form select{width:100%;background:#0d1117;
  color:var(--fg);border:1px solid var(--border);border-radius:6px;
  padding:8px 10px;font:14px inherit}
.wiz-form input:focus,.wiz-form select:focus{outline:none;
  border-color:var(--accent)}
.wiz-actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
.wiz-btn{background:var(--accent);color:#000;border:none;
  border-radius:6px;padding:8px 16px;font-weight:600;cursor:pointer;
  font-size:14px}
.wiz-btn:hover{filter:brightness(1.08)}
.wiz-btn.secondary{background:transparent;color:var(--fg);
  border:1px solid var(--border)}
.wiz-btn:disabled{opacity:0.5;cursor:not-allowed}
.wiz-warn{background:rgba(210,153,34,.10);
  border:1px solid rgba(210,153,34,.4);border-left:3px solid var(--amber);
  border-radius:6px;padding:10px 12px;color:var(--fg);font-size:13px;
  margin:10px 0}
.wiz-warn strong{color:var(--amber)}
.wiz-result{background:#0f141a;border:1px solid var(--border);
  border-radius:8px;padding:12px 14px;font-size:13px;margin-top:12px}
.wiz-result.ok{border-left:3px solid var(--green)}
.wiz-result.fail{border-left:3px solid var(--red)}
.wiz-alias-row{display:flex;align-items:center;justify-content:space-between;
  padding:8px 0;border-bottom:1px solid #1c2129}
.wiz-alias-row:last-child{border-bottom:none}
.wiz-alias-row .meta{color:var(--dim);font-size:12px}
.wiz-alias-badge{font-size:11px;padding:1px 8px;border-radius:999px;
  border:1px solid var(--border);margin-left:6px}
.wiz-alias-badge.demo{color:var(--green);border-color:rgba(63,185,80,.4);
  background:rgba(63,185,80,.10)}
.wiz-alias-badge.live{color:var(--red);border-color:rgba(248,81,73,.4);
  background:rgba(248,81,73,.10)}
@media (max-width: 700px){
  .wiz{padding:0 4px}
  .wiz-step{padding:16px 14px}
  .wiz-actions{gap:6px}
}
"""


_BROKER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect your broker -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
__BROKER_CSS__
</style></head>
<body>
__NAV__
<div class="wrap">
  <h1>Connect your broker</h1>
  <div class="sub">Sandbox is the default. Live requires an extra
  confirmation step.</div>

  <div class="wiz">
    <section class="wiz-step" id="step-type" data-step="1">
      <h2>1. Which account are we connecting?</h2>
      <div class="lead">Pick sandbox / demo unless you know you need
      the live one. You can always change this later.</div>
      <div class="wiz-radio-card selected" data-type="demo"
           tabindex="0" role="radio" aria-checked="true">
        <div class="label">Demo / Sandbox account (recommended)</div>
        <div class="sub">No real money at risk. Perfect for
        evaluating the squad.</div>
      </div>
      <div class="wiz-radio-card" data-type="live"
           tabindex="0" role="radio" aria-checked="false">
        <div class="label">Live account (real money)</div>
        <div class="sub">Requires typed confirmation on the next
        screen.</div>
      </div>
      <div class="wiz-actions">
        <button class="wiz-btn" id="btn-next-type">Next &rarr;</button>
      </div>
    </section>

    <section class="wiz-step" id="step-creds" data-step="2" style="display:none">
      <h2>2. Enter your MT5 credentials</h2>
      <div class="lead">Your password lives on your device only.
      The platform server sees it only during the test-connection call.</div>
      <div class="wiz-form">
        <div>
          <label for="in-server">MT5 server (exact name from broker)</label>
          <input id="in-server" type="text" list="server-suggestions"
                 autocomplete="off" spellcheck="false" required
                 placeholder="e.g. Exness-MT5Trial7">
          <datalist id="server-suggestions">
            __SERVER_OPTIONS__
          </datalist>
        </div>
        <div>
          <label for="in-login">Login (numeric MT5 login)</label>
          <input id="in-login" type="text" inputmode="numeric"
                 autocomplete="off" spellcheck="false"
                 pattern="\d{1,20}" required>
        </div>
        <div>
          <label for="in-pw">Password</label>
          <input id="in-pw" type="password" autocomplete="off"
                 spellcheck="false" required>
        </div>
      </div>
      <div class="wiz-actions">
        <button class="wiz-btn secondary" id="btn-back-creds">&larr; Back</button>
        <button class="wiz-btn" id="btn-next-creds">Next &rarr;</button>
      </div>
    </section>

    <section class="wiz-step" id="step-confirm-live" data-step="2.5"
             style="display:none">
      <h2>You picked a live account</h2>
      <div class="wiz-warn" id="live-warning-body"><strong>Warning.</strong>
      <span id="live-warning-text">Loading warning\u2026</span></div>
      <div class="wiz-form">
        <label>
          <input type="checkbox" id="in-live-ack"> I understand this
          uses real money.
        </label>
        <div>
          <label for="in-live-typed">Type LIVE to continue:</label>
          <input id="in-live-typed" type="text" autocomplete="off"
                 spellcheck="false">
        </div>
      </div>
      <div class="wiz-actions">
        <button class="wiz-btn secondary" id="btn-back-live">&larr; Back</button>
        <button class="wiz-btn" id="btn-next-live" disabled>Continue &rarr;</button>
      </div>
    </section>

    <section class="wiz-step" id="step-test" data-step="3" style="display:none">
      <h2>3. Test the connection</h2>
      <div class="lead">We call your broker with the credentials above
      and read back the account type + currency.</div>
      <div class="wiz-actions">
        <button class="wiz-btn secondary" id="btn-back-test">&larr; Back</button>
        <button class="wiz-btn" id="btn-run-test">Test connection</button>
      </div>
      <div id="test-result"></div>
    </section>

    <section class="wiz-step" id="step-save" data-step="4" style="display:none">
      <h2>4. Save the connection</h2>
      <div class="wiz-form">
        <div>
          <label for="in-alias">Save this as</label>
          <input id="in-alias" type="text" autocomplete="off"
                 spellcheck="false" placeholder="primary">
        </div>
      </div>
      <div class="wiz-actions">
        <button class="wiz-btn secondary" id="btn-back-save">&larr; Back</button>
        <button class="wiz-btn" id="btn-run-save">Save connection</button>
      </div>
      <div id="save-result"></div>
    </section>

    <section class="wiz-step" id="step-list" data-step="5">
      <h2>Saved connections</h2>
      <div class="lead">Passwords are never displayed here \u2014 stored
      encrypted in your OS keychain.</div>
      <div id="alias-list"></div>
    </section>
  </div>
</div>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
function esc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
var state = {accountType: "demo"};

function showStep(id){
  var steps = document.querySelectorAll(".wiz-step");
  for(var i=0;i<steps.length;i++){ steps[i].style.display = "none"; }
  document.getElementById(id).style.display = "";
  document.getElementById("step-list").style.display = "";
  window.scrollTo(0, 0);
}

function bindRadioCards(){
  var cards = document.querySelectorAll("#step-type .wiz-radio-card");
  cards.forEach(function(c){
    c.addEventListener("click", function(){
      cards.forEach(function(x){ x.classList.remove("selected");
        x.setAttribute("aria-checked", "false"); });
      c.classList.add("selected");
      c.setAttribute("aria-checked", "true");
      state.accountType = c.getAttribute("data-type");
    });
    c.addEventListener("keydown", function(e){
      if(e.key === " " || e.key === "Enter"){ e.preventDefault(); c.click(); }
    });
  });
}

function bindNavigation(){
  document.getElementById("btn-next-type").addEventListener("click", function(){
    showStep("step-creds");
  });
  document.getElementById("btn-back-creds").addEventListener("click", function(){
    showStep("step-type");
  });
  document.getElementById("btn-next-creds").addEventListener("click", function(){
    if(state.accountType === "live"){
      loadLiveWarning();
      showStep("step-confirm-live");
    } else {
      showStep("step-test");
    }
  });
  document.getElementById("btn-back-live").addEventListener("click", function(){
    showStep("step-creds");
  });
  document.getElementById("btn-next-live").addEventListener("click", function(){
    showStep("step-test");
  });
  document.getElementById("btn-back-test").addEventListener("click", function(){
    if(state.accountType === "live"){ showStep("step-confirm-live"); }
    else { showStep("step-creds"); }
  });
  document.getElementById("btn-back-save").addEventListener("click", function(){
    showStep("step-test");
  });
  document.getElementById("btn-run-test").addEventListener("click", runTest);
  document.getElementById("btn-run-save").addEventListener("click", runSave);
  var ack = document.getElementById("in-live-ack");
  var typed = document.getElementById("in-live-typed");
  function evalLiveGate(){
    var ok = (ack.checked === true) && (typed.value.trim() === "LIVE");
    document.getElementById("btn-next-live").disabled = !ok;
  }
  ack.addEventListener("change", evalLiveGate);
  typed.addEventListener("input", evalLiveGate);
}

function loadLiveWarning(){
  fetch("/api/broker/live-warning", {cache:"no-store"}).then(function(r){
    return r.ok ? r.text() : "Live-broker warning failed to load.";
  }).then(function(t){
    document.getElementById("live-warning-text").innerText = t;
  }).catch(function(){
    document.getElementById("live-warning-text").innerText =
      "Live-broker warning failed to load. Please contact the operator.";
  });
}

function runTest(){
  var box = document.getElementById("test-result");
  box.innerHTML = '<div class="sk-chart" style="height:60px"></div>';
  var body = JSON.stringify({
    login: document.getElementById("in-login").value,
    password: document.getElementById("in-pw").value,
    server: document.getElementById("in-server").value
  });
  fetch("/api/broker/test-connection", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: body,
    cache: "no-store"
  }).then(function(r){ return r.json(); })
    .then(function(data){
    var cls = data.success ? "ok" : "fail";
    var out = '<div class="wiz-result '+cls+'">';
    if(data.success){
      out += '<b>Connected.</b> Account #'+esc(data.account_number)+
        ' on '+esc(data.server)+' \u2014 '+esc(data.account_type)+
        ' ('+esc(data.balance_currency || 'currency n/a')+').';
      document.getElementById("btn-run-test").disabled = true;
      showStep("step-save");
    } else {
      out += '<b>Not connected.</b> '+esc(data.error_message ||
        'Unknown error.');
    }
    out += '</div>';
    box.innerHTML = out;
  }).catch(function(e){
    box.innerHTML = '<div class="wiz-result fail">Request failed \u2014 '+
      esc(e && e.message || 'network error')+'</div>';
  });
}

function runSave(){
  var box = document.getElementById("save-result");
  box.innerHTML = '<div class="sk-chart" style="height:40px"></div>';
  var alias = (document.getElementById("in-alias").value || "primary").trim();
  var body = JSON.stringify({
    alias: alias,
    login: document.getElementById("in-login").value,
    password: document.getElementById("in-pw").value,
    server: document.getElementById("in-server").value,
    account_type: state.accountType
  });
  fetch("/api/broker/save", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: body,
    cache: "no-store"
  }).then(function(r){ return r.json(); }).then(function(data){
    if(data.success){
      box.innerHTML = '<div class="wiz-result ok"><b>Saved.</b> '+
        'Your password is encrypted at rest.</div>';
      refreshAliases();
    } else {
      box.innerHTML = '<div class="wiz-result fail"><b>Save failed.</b> '+
        esc(data.error || 'Unknown error.')+'</div>';
    }
  }).catch(function(e){
    box.innerHTML = '<div class="wiz-result fail">Request failed \u2014 '+
      esc(e && e.message || 'network error')+'</div>';
  });
}

function refreshAliases(){
  var box = document.getElementById("alias-list");
  fetch("/api/broker/list", {cache:"no-store"}).then(function(r){
    return r.json();
  }).then(function(data){
    var rows = (data && data.aliases) || [];
    if(rows.length === 0){
      box.innerHTML = '<div class="sk-empty">No saved connections yet.'+
        ' Complete the steps above to add one.</div>';
      return;
    }
    var out = '';
    for(var i=0;i<rows.length;i++){
      var r = rows[i];
      var badge = r.account_type === 'live' ? 'live' : 'demo';
      out += '<div class="wiz-alias-row">'+
        '<div><b>'+esc(r.alias)+'</b>'+
        '<span class="wiz-alias-badge '+badge+'">'+esc(r.account_type)+'</span>'+
        '<div class="meta">'+esc(r.server)+' \u2014 login '+esc(r.login)+'</div></div>'+
        '<button class="wiz-btn secondary" data-alias="'+esc(r.alias)+
        '">Remove</button></div>';
    }
    box.innerHTML = out;
    var btns = box.querySelectorAll("button[data-alias]");
    for(var j=0;j<btns.length;j++){
      btns[j].addEventListener("click", function(ev){
        var alias = ev.currentTarget.getAttribute("data-alias");
        if(!confirm("Remove " + alias +
                    "? The stored password is deleted.")) return;
        fetch("/api/broker/" + encodeURIComponent(alias), {
          method: "DELETE", cache: "no-store"
        }).then(function(){ refreshAliases(); });
      });
    }
  }).catch(function(){
    box.innerHTML = '<div class="sk-error">Could not load saved '+
      'connections. The page will keep trying.</div>';
  });
}

bindRadioCards();
bindNavigation();
refreshAliases();
</script></body></html>"""


def _server_options() -> str:
    """Emit ``<option>`` hints inside the server-suggestion datalist.

    Users type the exact server their broker gave them
    (e.g. ``Exness-MT5Trial7``); we surface only the allow-listed
    prefixes so it's clear which brokers are supported. The value we
    emit is the prefix itself so a click auto-fills the prefix which
    the user then completes -- we never emit an unvalidated full
    server string.
    """
    from agent.platform.broker_connection import ALLOWED_SERVERS
    opts = []
    for prefix in ALLOWED_SERVERS:
        opts.append(f'<option value="{prefix}">')
    return "\n            ".join(opts)


BROKER_WIZARD_PAGE = (_BROKER_TEMPLATE
                     .replace("__BASE_CSS__", _BASE_CSS)
                     .replace("__SKELETON_CSS__", _SKELETON_CSS)
                     .replace("__BROKER_CSS__", _BROKER_CSS)
                     .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                     .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                     .replace("__SERVER_OPTIONS__", _server_options())
                     .replace("__NAV__", nav('broker')))


# ---------------------------------------------------------------------------
# F008 -- Onboarding wizard page
# ---------------------------------------------------------------------------
#
# First-visit redirect target. Walks the user through:
#   1. Welcome (Legal agreement pass-through)
#   2. Passphrase (optional if keychain available, mandatory otherwise)
#   3. Broker (in-page CTA that opens /settings/broker in a new tab)
#   4. Default pairs (EURUSD default on; GBPUSD, USDCAD optional)
#   5. Confirm (recap + "Finish setup" button)
#
# All CSS is additive under _ONBOARDING_CSS -- no _BASE_CSS_VERSION bump.

_ONBOARDING_CSS = r"""
.onb{max-width:640px;margin:0 auto}
.onb-stepper{display:flex;justify-content:space-between;
  margin:6px 0 18px;font-size:12px;color:var(--dim)}
.onb-stepper span{flex:1;text-align:center;padding:6px 4px;
  border-bottom:2px solid var(--border)}
.onb-stepper span.done{border-bottom-color:var(--green);color:var(--green)}
.onb-stepper span.current{border-bottom-color:var(--accent);
  color:var(--fg);font-weight:600}
.onb-step{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:22px 24px;margin-bottom:14px}
.onb-step h2{margin:0 0 8px;font-size:17px}
.onb-step .lead{color:var(--dim);font-size:13px;margin:0 0 14px}
.onb-form{display:grid;gap:10px}
.onb-form label{display:block;font-size:12px;color:var(--dim);
  text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}
.onb-form input[type=password],.onb-form input[type=text]{
  width:100%;background:#0d1117;color:var(--fg);
  border:1px solid var(--border);border-radius:6px;
  padding:8px 10px;font:14px inherit}
.onb-form input:focus{outline:none;border-color:var(--accent)}
.onb-check{display:flex;align-items:flex-start;gap:8px;padding:6px 0}
.onb-check input{margin-top:2px}
.onb-actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;
  justify-content:flex-end}
.onb-btn{background:var(--accent);color:#000;border:none;
  border-radius:6px;padding:8px 16px;font-weight:600;cursor:pointer;
  font-size:14px}
.onb-btn:hover{filter:brightness(1.08)}
.onb-btn.secondary{background:transparent;color:var(--fg);
  border:1px solid var(--border)}
.onb-btn:disabled{opacity:0.5;cursor:not-allowed}
.onb-result{background:#0f141a;border:1px solid var(--border);
  border-radius:8px;padding:10px 12px;font-size:13px;margin-top:10px}
.onb-result.ok{border-left:3px solid var(--green)}
.onb-result.fail{border-left:3px solid var(--red)}
.onb-recap{background:#0f141a;border:1px solid var(--border);
  border-radius:8px;padding:12px 14px;margin-bottom:10px;font-size:13px}
.onb-recap b{color:var(--accent)}
.onb-agreement{background:rgba(88,166,255,.08);
  border:1px solid rgba(88,166,255,.25);border-left:3px solid var(--accent);
  border-radius:6px;padding:10px 12px;font-size:12.5px;
  color:var(--fg);margin:10px 0}
.onb-chip{display:inline-block;background:rgba(210,153,34,.10);
  border:1px solid rgba(210,153,34,.4);border-left:3px solid var(--amber);
  border-radius:6px;padding:8px 12px;margin-top:10px;font-size:13px;
  line-height:1.5}
.onb-chip b{color:var(--amber)}
@media (max-width: 700px){
  .onb{padding:0 4px}
  .onb-step{padding:16px 14px}
  .onb-stepper{font-size:11px}
  .onb-actions{gap:6px}
}
"""

_ONBOARDING_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Welcome -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
__ONBOARDING_CSS__
</style></head>
<body>
__NAV__
<div class="wrap">
  <h1>Set up your Blue Lock install</h1>
  <div class="sub">Five short steps. Nothing leaves your machine.</div>

  <div class="onb">
    <div class="onb-stepper" id="stepper" role="progressbar"
         aria-label="Onboarding progress">
      <span data-step="welcome" class="current">1. Welcome</span>
      <span data-step="passphrase">2. Passphrase</span>
      <span data-step="broker">3. Broker</span>
      <span data-step="pairs">4. Pairs</span>
      <span data-step="confirm">5. Confirm</span>
    </div>

    <section class="onb-step" id="step-welcome" data-step="welcome">
      <h2>Welcome</h2>
      <div class="lead">Blue Lock is a single-user hobbyist trading
      platform. You install it on your machine. It doesn't send
      your data anywhere.</div>
      <div class="onb-agreement">
        By continuing you agree that Blue Lock Trading Co. is not a
        regulated broker or investment adviser, that nothing this
        platform outputs is financial advice, and that any losses
        incurred through connected broker accounts are your
        responsibility.
      </div>
      <div class="onb-actions">
        <button class="onb-btn" id="btn-next-welcome">Continue &rarr;</button>
      </div>
    </section>

    <section class="onb-step" id="step-passphrase" data-step="passphrase"
             style="display:none">
      <h2>Set your fallback passphrase</h2>
      <div class="lead">Blue Lock stores your broker credentials in
      your OS keychain when it can. If a keychain isn't available on
      this machine, we fall back to an encrypted file protected by
      this passphrase. Leave empty if your keychain works and you
      want to skip the fallback.</div>
      <div class="onb-form">
        <div>
          <label for="in-passphrase">Passphrase</label>
          <input id="in-passphrase" type="password"
                 autocomplete="new-password" spellcheck="false">
        </div>
        <div class="onb-check">
          <input type="checkbox" id="in-noop-passphrase">
          <label for="in-noop-passphrase">Skip passphrase
            (my OS keychain is available).</label>
        </div>
      </div>
      <div id="passphrase-result"></div>
      <div class="onb-actions">
        <button class="onb-btn secondary" id="btn-back-passphrase">
          &larr; Back</button>
        <button class="onb-btn" id="btn-next-passphrase">
          Continue &rarr;</button>
      </div>
    </section>

    <section class="onb-step" id="step-broker" data-step="broker"
             style="display:none">
      <h2>Connect a broker</h2>
      <div class="lead">Blue Lock trades on MT5. You'll open the
      broker wizard, connect a demo (or live) account, then return
      here to finish setup.</div>
      <div class="onb-actions">
        <button class="onb-btn secondary" id="btn-back-broker">
          &larr; Back</button>
        <a class="onb-btn" href="/settings/broker" target="_blank"
           rel="noopener">Open broker wizard &rarr;</a>
        <button class="onb-btn" id="btn-next-broker">
          I've connected a broker &rarr;</button>
      </div>
      <div id="broker-status" class="onb-result"></div>
    </section>

    <section class="onb-step" id="step-pairs" data-step="pairs"
             style="display:none">
      <h2>Choose default pairs</h2>
      <div class="lead">Which FX pairs should the squad watch first?
      You can change this later on the /players page.</div>
      <div class="onb-form">
        <div class="onb-check">
          <input type="checkbox" id="pair-EURUSD" checked>
          <label for="pair-EURUSD">EURUSD (default)</label>
        </div>
        <div class="onb-check">
          <input type="checkbox" id="pair-GBPUSD">
          <label for="pair-GBPUSD">GBPUSD</label>
        </div>
        <div class="onb-check">
          <input type="checkbox" id="pair-USDCAD">
          <label for="pair-USDCAD">USDCAD</label>
        </div>
      </div>
      <div class="onb-actions">
        <button class="onb-btn secondary" id="btn-back-pairs">
          &larr; Back</button>
        <button class="onb-btn" id="btn-next-pairs">
          Continue &rarr;</button>
      </div>
    </section>

    <section class="onb-step" id="step-confirm" data-step="confirm"
             style="display:none">
      <h2>Ready to go</h2>
      <div class="lead">Here's your setup:</div>
      <div class="onb-recap" id="recap"></div>
      <div class="onb-actions">
        <button class="onb-btn secondary" id="btn-back-confirm">
          &larr; Back</button>
        <button class="onb-btn" id="btn-finish">Finish setup</button>
      </div>
      <div id="finish-result"></div>
    </section>
  </div>
</div>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
var STEP_IDS = ["welcome","passphrase","broker","pairs","confirm"];
var state = {
  step: "welcome",
  passphraseSkipped: false,
  brokerConnected: false,
  keyringAvailable: false,
  defaultPairs: ["EURUSD"]
};

function esc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function showStep(id){
  state.step = id;
  var steps = document.querySelectorAll(".onb-step");
  for(var i=0;i<steps.length;i++){ steps[i].style.display = "none"; }
  document.getElementById("step-" + id).style.display = "";
  var pips = document.querySelectorAll("#stepper span");
  var seen = false;
  for(var j=0;j<pips.length;j++){
    pips[j].classList.remove("done");
    pips[j].classList.remove("current");
    if(pips[j].getAttribute("data-step") === id){
      pips[j].classList.add("current"); seen = true;
    } else if(!seen){
      pips[j].classList.add("done");
    }
  }
  window.scrollTo(0, 0);
  fetch("/api/onboarding/state?step=" + encodeURIComponent(id),
        {method: "POST", cache: "no-store"}).catch(function(){});
}

function loadState(){
  fetch("/api/onboarding/state", {cache:"no-store"})
    .then(function(r){ return r.json(); })
    .then(function(data){
      state.keyringAvailable = !!data.keyring_available;
      state.brokerConnected = !!data.broker_connected;
      state.defaultPairs = data.default_pairs || ["EURUSD"];
      if(data.completed){
        window.location.assign("/");
        return;
      }
      showStep(data.step || "welcome");
      refreshBrokerStatus();
    })
    .catch(function(){ showStep("welcome"); });
}

function bindNav(){
  document.getElementById("btn-next-welcome")
    .addEventListener("click", function(){ showStep("passphrase"); });
  document.getElementById("btn-back-passphrase")
    .addEventListener("click", function(){ showStep("welcome"); });
  document.getElementById("btn-next-passphrase")
    .addEventListener("click", submitPassphrase);
  document.getElementById("btn-back-broker")
    .addEventListener("click", function(){ showStep("passphrase"); });
  document.getElementById("btn-next-broker")
    .addEventListener("click", function(){
      refreshBrokerStatus(function(){
        if(state.brokerConnected){ showStep("pairs"); }
      });
    });
  document.getElementById("btn-back-pairs")
    .addEventListener("click", function(){ showStep("broker"); });
  document.getElementById("btn-next-pairs")
    .addEventListener("click", submitPairs);
  document.getElementById("btn-back-confirm")
    .addEventListener("click", function(){ showStep("pairs"); });
  document.getElementById("btn-finish")
    .addEventListener("click", finishSetup);
}

function submitPassphrase(){
  var box = document.getElementById("passphrase-result");
  var pw = document.getElementById("in-passphrase").value || "";
  var skipped = document.getElementById("in-noop-passphrase").checked;
  var body = JSON.stringify({passphrase: skipped ? "" : pw,
                              skipped: skipped});
  fetch("/api/onboarding/passphrase", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: body, cache: "no-store"
  }).then(function(r){ return r.json(); }).then(function(data){
    if(data.ok){
      box.innerHTML = '<div class="onb-result ok">' +
        esc(data.message || 'Passphrase accepted.') + '</div>';
      state.passphraseSkipped = !!skipped;
      showStep("broker");
    } else {
      box.innerHTML = '<div class="onb-result fail">' +
        esc(data.message || 'Passphrase rejected.') + '</div>';
    }
  }).catch(function(){
    box.innerHTML = '<div class="onb-result fail">' +
      'Could not reach the server.</div>';
  });
}

function refreshBrokerStatus(cb){
  fetch("/api/onboarding/state", {cache:"no-store"})
    .then(function(r){ return r.json(); }).then(function(data){
      state.brokerConnected = !!data.broker_connected;
      var box = document.getElementById("broker-status");
      if(state.brokerConnected){
        box.className = "onb-result ok";
        box.innerHTML = "Broker connection detected.";
      } else {
        box.className = "onb-result";
        box.innerHTML = "No broker connected yet. Complete the " +
          "wizard tab and click Continue.";
      }
      if(cb) cb();
    }).catch(function(){});
}

function submitPairs(){
  var checked = [];
  ["EURUSD","GBPUSD","USDCAD"].forEach(function(p){
    if(document.getElementById("pair-" + p).checked){ checked.push(p); }
  });
  if(checked.length === 0){
    alert("Pick at least one pair -- EURUSD is the sensible default.");
    return;
  }
  fetch("/api/onboarding/pairs", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({pairs: checked}),
    cache: "no-store"
  }).then(function(r){ return r.json(); }).then(function(data){
    if(data.ok){
      state.defaultPairs = data.pairs || checked;
      renderRecap();
      showStep("confirm");
    } else {
      alert(data.message || "Could not save your pairs.");
    }
  });
}

function renderRecap(){
  var box = document.getElementById("recap");
  box.innerHTML =
    '<div>Passphrase: <b>' +
      (state.passphraseSkipped ? 'skipped (keychain)' : 'set') +
    '</b></div>' +
    '<div>Broker: <b>' +
      (state.brokerConnected ? 'connected' : 'not connected yet') +
    '</b></div>' +
    '<div>Default pairs: <b>' + esc(state.defaultPairs.join(", ")) +
    '</b></div>';
}

function finishSetup(){
  var box = document.getElementById("finish-result");
  fetch("/api/onboarding/complete", {method: "POST", cache: "no-store"})
    .then(function(r){ return r.json(); }).then(function(data){
      if(data.ok){
        // F019 (I003): completing without a broker is allowed, but
        // never silent -- the chip states the gap and links the wizard.
        var chip = state.brokerConnected ? '' :
          '<div class="onb-chip"><b>Broker not connected yet</b> ' +
          '\u2014 trading stays paused until a broker account is ' +
          'linked. <a href="/settings/broker">Connect one any time ' +
          '&rarr;</a></div>';
        box.innerHTML = '<div class="onb-result ok">Setup complete. ' +
          'Taking you to the hub.</div>' + chip;
        setTimeout(function(){ window.location.assign("/"); },
                   state.brokerConnected ? 1200 : 3500);
      } else {
        box.innerHTML = '<div class="onb-result fail">' +
          esc(data.message || 'Could not mark setup complete.') +
        '</div>';
      }
    });
}

bindNav();
loadState();
</script></body></html>"""


ONBOARDING_PAGE = (_ONBOARDING_TEMPLATE
                   .replace("__BASE_CSS__", _BASE_CSS)
                   .replace("__SKELETON_CSS__", _SKELETON_CSS)
                   .replace("__ONBOARDING_CSS__", _ONBOARDING_CSS)
                   .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                   .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                   .replace("__NAV__", nav('onboarding')))


# ---------------------------------------------------------------------------
# F008 -- /settings/reset-install confirmation page
# ---------------------------------------------------------------------------

_RESET_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reset install -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
.onb-step{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:22px 24px;margin:14px 0}
.onb-btn{background:var(--red);color:#000;border:none;
  border-radius:6px;padding:8px 16px;font-weight:600;cursor:pointer;
  font-size:14px}
.onb-btn.secondary{background:transparent;color:var(--fg);
  border:1px solid var(--border)}
.wiz-warn{background:rgba(210,153,34,.10);
  border:1px solid rgba(210,153,34,.4);border-left:3px solid var(--amber);
  border-radius:6px;padding:10px 12px;color:var(--fg);font-size:13px;
  margin:10px 0}
</style></head>
<body>
__NAV__
<div class="wrap">
  <h1>Reset your Blue Lock install</h1>
  <div class="sub">This clears your install token and saved broker
  connections, then sends you back through setup.</div>

  <div class="onb-step">
    <div class="wiz-warn"><strong>Warning.</strong> This deletes every
    saved broker alias, your install token, and the passphrase-fallback
    file (if any). It cannot be undone. Nothing is sent anywhere -- the
    keys are simply removed from your keychain / config file.</div>

    <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
      <a class="onb-btn secondary" href="/">&larr; Cancel</a>
      <button class="onb-btn" id="btn-reset">Reset install</button>
    </div>
    <div id="reset-result" style="margin-top:12px"></div>
  </div>
</div>
<script>
document.getElementById("btn-reset").addEventListener("click", function(){
  if(!confirm("Really reset your install? This cannot be undone.")) return;
  fetch("/api/onboarding/reset", {method: "POST", cache: "no-store"})
    .then(function(r){ return r.json(); }).then(function(data){
      var box = document.getElementById("reset-result");
      if(data.ok){
        box.innerHTML = "Reset complete. Taking you back to setup.";
        setTimeout(function(){
          window.location.assign("/onboarding");
        }, 1000);
      } else {
        box.innerHTML = "Reset failed. " +
          (data.message || 'Unknown error.');
      }
    });
});
</script></body></html>"""


RESET_INSTALL_PAGE = (_RESET_TEMPLATE
                      .replace("__BASE_CSS__", _BASE_CSS)
                      .replace("__NAV__", nav('reset')))


# ---------------------------------------------------------------------------
# F011 -- /settings/kill-switches page (Sprint 2)
# ---------------------------------------------------------------------------
#
# Toggle grid + reason textarea + audit-event log. Uses `withStates()`
# from F005 for the load / error / empty affordances. Mobile: media
# query at 700px collapses the toggle grid to a single column.

_KILL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kill switches -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
.ks-wrap{max-width:960px;margin:0 auto}
.ks-lead{color:var(--dim);margin:6px 0 14px}
.ks-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:12px 0 18px}
.ks-cell{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px}
.ks-cell.on{border-color:var(--red);background:rgba(248,81,73,.10)}
.ks-cell h3{margin:0 0 6px;font-size:14px;letter-spacing:.02em}
.ks-cell.on h3{color:var(--red)}
.ks-cell .state{font-size:12px;color:var(--dim);margin-bottom:8px}
.ks-cell.on .state{color:var(--red);font-weight:600}
.ks-btn{background:var(--red);color:#fff;border:none;
  border-radius:6px;padding:7px 12px;font-weight:600;cursor:pointer;
  font-size:13px}
.ks-btn.clear{background:var(--panel);color:var(--fg);
  border:1px solid var(--border)}
.ks-reason{width:100%;background:var(--bg);border:1px solid var(--border);
  color:var(--fg);border-radius:6px;padding:8px 10px;font:13px/1.4 inherit;
  min-height:60px;resize:vertical;box-sizing:border-box}
.ks-audit{margin-top:22px}
.ks-audit h2{font-size:15px;margin:0 0 8px}
.ks-event{border-bottom:1px dashed var(--border);padding:6px 0;font-size:13px}
.ks-event .ts{color:var(--dim);margin-right:8px}
.ks-event .act.activate{color:var(--red);font-weight:600}
.ks-event .act.clear{color:var(--green);font-weight:600}
.ks-result{margin-top:10px;font-size:13px;color:var(--dim);min-height:20px}
@media (max-width: 700px){
  .ks-grid{grid-template-columns:1fr}
}
</style></head>
<body>
__NAV__
<div class="ks-wrap">
  <h1>Kill switches</h1>
  <div class="ks-lead">Halt live orders globally or per-symbol. Activating
  a switch creates a flag file the future live-order pathway will honour
  as the second of the four safety checks (kill &rarr; risk &rarr;
  approval, all after live-mode is enabled). Sprint 2 ships the switch,
  not the wiring &mdash; toggling it here is safe.</div>

  <textarea class="ks-reason" id="ks-reason" placeholder="Reason (required when activating; max 200 chars)"></textarea>

  <div id="ks-grid" class="ks-grid"></div>

  <div id="ks-result" class="ks-result" role="status" aria-live="polite"></div>

  <section class="ks-audit">
    <h2>Recent events</h2>
    <div id="ks-audit"></div>
  </section>
</div>
<script>
__ERROR_COPY_JS__
__WITH_STATES_JS__

function esc(s){
  var d=document.createElement("div"); d.innerText=String(s==null?"":s);
  return d.innerHTML;
}

async function fetchStatus(){
  const r = await fetch("/api/kill-switches/status", {cache: "no-store"});
  if(r.status === 401) return {__auth__: true};
  if(!r.ok) return {__error__: "HTTP " + r.status};
  return await r.json();
}

async function postAction(url, body){
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {}),
  });
  var out;
  try { out = await r.json(); } catch(e){ out = {}; }
  return {status: r.status, body: out};
}

const SYMBOLS = ["GLOBAL", "EURUSD", "GBPUSD", "USDCAD", "USDJPY", "USDCHF"];

function renderGrid(state, box){
  const killed = new Set((state.killed_scopes || []).map(function(k){ return k.scope; }));
  const reasons = {};
  (state.killed_scopes || []).forEach(function(k){ reasons[k.scope] = k.reason; });
  var out = "";
  SYMBOLS.forEach(function(sym){
    const on = killed.has(sym);
    const scopeLabel = sym === "GLOBAL" ? "Global (all pairs)" : sym;
    out += '<div class="ks-cell'+(on?' on':'')+'" data-scope="'+esc(sym)+'">';
    out +=   '<h3>'+esc(scopeLabel)+'</h3>';
    out +=   '<div class="state">'+(on ? 'ACTIVE'+(reasons[sym]?' -- '+esc(reasons[sym]):'') : 'inert')+'</div>';
    if(on){
      out += '<button class="ks-btn clear" data-act="clear" data-scope="'+esc(sym)+'">Clear</button>';
    } else {
      out += '<button class="ks-btn" data-act="activate" data-scope="'+esc(sym)+'">Activate kill</button>';
    }
    out += '</div>';
  });
  box.innerHTML = out;
  box.querySelectorAll("button.ks-btn").forEach(function(btn){
    btn.addEventListener("click", handleClick);
  });
}

function renderAudit(state){
  var box = document.getElementById("ks-audit");
  const events = state.events || [];
  if(!events.length){
    box.innerHTML = '<div class="dim">No events yet.</div>';
    return;
  }
  box.innerHTML = events.slice().reverse().map(function(e){
    return '<div class="ks-event"><span class="ts">'+esc(e.ts||"")+'</span>'+
      '<span class="act '+esc(e.action||"")+'">'+esc((e.action||"").toUpperCase())+'</span> '+
      esc(e.scope||"")+' &mdash; '+esc(e.reason||"")+
      ' <span class="dim">by '+esc(e.by||"user")+'</span></div>';
  }).join("");
}

async function refresh(){
  var grid = document.getElementById("ks-grid");
  await withStates(grid, fetchStatus, function(state, box){
    renderGrid(state, box);
    renderAudit(state);
    return null;
  }, {emptyCopyKey: "no_data_yet"});
}

async function handleClick(ev){
  const btn = ev.currentTarget;
  const scope = btn.getAttribute("data-scope");
  const act   = btn.getAttribute("data-act");
  const body = scope === "GLOBAL" ? {} : {symbol: scope};
  var url;
  if(act === "activate"){
    const reason = (document.getElementById("ks-reason").value || "").trim();
    if(!reason){
      document.getElementById("ks-result").textContent =
        "Reason is required when activating.";
      return;
    }
    body.reason = reason;
    url = "/api/kill-switches/activate";
  } else {
    url = "/api/kill-switches/clear";
  }
  document.getElementById("ks-result").textContent = "Working...";
  const res = await postAction(url, body);
  if(res.status === 200 && res.body && res.body.ok){
    document.getElementById("ks-result").textContent =
      act === "activate" ? "Activated " + scope : "Cleared " + scope;
    document.getElementById("ks-reason").value = "";
    refresh();
  } else {
    document.getElementById("ks-result").textContent =
      "Action failed: " + esc((res.body && res.body.error) || ("HTTP " + res.status));
  }
}

refresh();
</script></body></html>"""


KILL_SWITCHES_PAGE = (_KILL_TEMPLATE
                      .replace("__BASE_CSS__", _BASE_CSS)
                      .replace("__SKELETON_CSS__", _SKELETON_CSS)
                      .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                      .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                      .replace("__NAV__", nav('kill-switches')))


# ---------------------------------------------------------------------------
# F012 -- /risk dashboard (Sprint 2)
# ---------------------------------------------------------------------------
#
# Three sections: budget headroom, broker health, live exposure
# (placeholder). Polls /api/risk/state every 30s via withStates().

_RISK_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Risk -- Blue Lock Trading Co.</title>
<style>__BASE_CSS__
__SKELETON_CSS__
.risk-wrap{max-width:1000px;margin:0 auto}
.risk-lead{color:var(--dim);margin:6px 0 14px}
.risk-section{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:16px 18px;margin:14px 0}
.risk-section h2{font-size:15px;margin:0 0 10px}
.risk-bar{background:var(--bg);border:1px solid var(--border);
  border-radius:6px;height:16px;position:relative;overflow:hidden}
.risk-bar .fill{height:100%;background:var(--green);transition:width .2s}
.risk-bar.warn .fill{background:var(--amber)}
.risk-bar.hot  .fill{background:var(--red)}
.risk-row{display:grid;grid-template-columns:140px 1fr 120px;gap:10px;
  align-items:center;margin:6px 0;font-size:13px}
.risk-row .label{color:var(--fg)}
.risk-row .num{color:var(--dim);text-align:right;font-variant-numeric:tabular-nums}
.risk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.risk-alias{background:var(--bg);border:1px solid var(--border);
  border-radius:6px;padding:10px 12px}
.risk-alias .badge{margin-left:6px}
.risk-alias .meta{color:var(--dim);font-size:12px;margin-top:4px}
.risk-updated{color:var(--dim);font-size:12px;margin-top:6px}
.risk-warn{background:rgba(210,153,34,.10);border:1px solid rgba(210,153,34,.4);
  border-left:3px solid var(--amber);border-radius:6px;padding:10px 12px;
  color:var(--fg);font-size:12.5px;margin:8px 0}
@media (max-width: 700px){
  .risk-row{grid-template-columns:100px 1fr;grid-auto-flow:dense}
  .risk-row .num{grid-column:2/3;text-align:left;color:var(--dim)}
  .risk-grid{grid-template-columns:1fr}
}
</style></head>
<body>
__NAV__
<div class="risk-wrap">
  <h1>Risk</h1>
  <div class="risk-lead">Pre-trade safety snapshot: your realised
  daily-loss budget, per-symbol and per-strategy caps, and each
  saved broker connection's health. Sprint 2 ships these as the
  third of the four safety checks (live-mode &rarr; kill-switch
  &rarr; <em>risk budget</em> &rarr; approval). Sprint 2 does not
  send any live orders.</div>

  <div class="risk-warn"><strong>Sprint 2 caveat.</strong> Live-mode is
  OFF by default. Values below reflect any manually-recorded fills in
  <code>risk_state.jsonl</code>; a fresh install shows all caps at
  full headroom, which is correct.</div>

  <div id="risk-live" class="risk-section">
    <h2>Live exposure</h2>
    <div id="risk-live-body"></div>
  </div>

  <div id="risk-budget" class="risk-section">
    <h2>Budget headroom</h2>
    <div id="risk-budget-body"></div>
  </div>

  <div id="risk-brokers" class="risk-section">
    <h2>Broker connections</h2>
    <div id="risk-brokers-body"></div>
  </div>

  <div id="risk-updated" class="risk-updated"></div>
</div>
<script>
__ERROR_COPY_JS__
__WITH_STATES_JS__

function esc(s){
  var d=document.createElement("div"); d.innerText=String(s==null?"":s);
  return d.innerHTML;
}
function fmt(x){ return (typeof x === "number") ? x.toFixed(2) : "0.00"; }

async function fetchState(){
  const r = await fetch("/api/risk/state", {cache: "no-store"});
  if(r.status === 401) return {__auth__: true};
  if(!r.ok) return {__error__: "HTTP " + r.status};
  return await r.json();
}

function barHtml(used, cap){
  cap = Number(cap) || 1;
  const pct = Math.min(100, Math.max(0, (used / cap) * 100));
  const cls = pct >= 90 ? "hot" : (pct >= 50 ? "warn" : "");
  return '<div class="risk-bar '+cls+'"><div class="fill" style="width:'+pct.toFixed(1)+'%"></div></div>';
}

function rowHtml(label, used, cap){
  const remaining = Math.max(0, cap - used);
  return '<div class="risk-row"><span class="label">'+esc(label)+'</span>'+
    barHtml(used, cap)+
    '<span class="num">'+fmt(remaining)+' / '+fmt(cap)+'</span></div>';
}

function renderBudget(state){
  const b = state.budget || {};
  const box = document.getElementById("risk-budget-body");
  var out = "";
  if(b.per_day){
    out += rowHtml("Per day",       b.per_day.used, b.per_day.cap);
  }
  const syms = b.per_symbol || {};
  const symKeys = Object.keys(syms).sort();
  if(symKeys.length === 0){
    out += '<div class="dim" style="margin:6px 0">No per-symbol usage today. Default cap: '+fmt(b.per_symbol_default||0)+'.</div>';
  } else {
    symKeys.forEach(function(k){
      out += rowHtml("Symbol "+k, syms[k].used, syms[k].cap);
    });
  }
  const strat = b.per_strategy || {};
  const stratKeys = Object.keys(strat).sort();
  if(stratKeys.length === 0){
    out += '<div class="dim" style="margin:6px 0">No per-strategy usage today. Default cap: '+fmt(b.per_strategy_default||0)+'.</div>';
  } else {
    stratKeys.forEach(function(k){
      out += rowHtml("Strategy "+k, strat[k].used, strat[k].cap);
    });
  }
  box.innerHTML = out;
}

function renderBrokers(state){
  const rows = state.brokers || [];
  const box = document.getElementById("risk-brokers-body");
  if(!rows.length){
    box.innerHTML = '<div class="dim">No broker aliases saved. '+
      '<a href="/settings/broker">Add one &rarr;</a></div>';
    return;
  }
  box.innerHTML = '<div class="risk-grid">'+rows.map(function(row){
    var badgeCls = row.alive ? "alive" : (row.reason === "not yet probed" ? "stale" : "down");
    var badgeText = row.alive ? "alive" : (row.reason === "not yet probed" ? "stale" : "down");
    return '<div class="risk-alias"><strong>'+esc(row.alias||"?")+'</strong>'+
      '<span class="badge '+esc(badgeCls)+'">'+esc(badgeText)+'</span>'+
      '<div class="meta">'+esc(row.reason||"")+
      (row.server ? ' &middot; '+esc(row.server) : '')+
      (row.account_type ? ' &middot; '+esc(row.account_type) : '')+
      '</div></div>';
  }).join("")+'</div>';
}

function renderLive(state){
  const box = document.getElementById("risk-live-body");
  const exposure = state.exposure || {open_positions: 0, notional_usd: 0};
  box.innerHTML = '<div class="risk-row"><span class="label">Open positions</span>'+
    '<span class="dim">Sprint 2 -- live-mode OFF, no live positions</span>'+
    '<span class="num">'+(exposure.open_positions || 0)+'</span></div>'+
    '<div class="risk-row"><span class="label">Notional (USD)</span>'+
    '<span class="dim">placeholder for future integration</span>'+
    '<span class="num">'+fmt(exposure.notional_usd || 0)+'</span></div>';
}

async function refresh(){
  var box = document.getElementById("risk-budget-body");
  await withStates(box, fetchState, function(state, box){
    renderLive(state);
    renderBudget(state);
    renderBrokers(state);
    document.getElementById("risk-updated").textContent =
      "Updated " + esc(state.as_of || "");
    return null;
  }, {emptyCopyKey: "no_data_yet"});
}

refresh();
setInterval(refresh, 30000);
</script></body></html>"""


RISK_PAGE = (_RISK_TEMPLATE
             .replace("__BASE_CSS__", _BASE_CSS)
             .replace("__SKELETON_CSS__", _SKELETON_CSS)
             .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
             .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
             .replace("__NAV__", nav('risk')))


# ---------------------------------------------------------------------------
# F013 -- Trade approvals + live-mode toggle pages
# ---------------------------------------------------------------------------
#
# `/approvals` renders the pending queue with big Approve / Reject
# buttons + a countdown timer per entry. `/settings/live-mode` renders
# the enable-live-mode CEREMONY: checkbox + typed-value confirmation +
# verbatim Legal disclaimer loaded from `/api/live-mode/warning`.
#
# Both pages ship default-OFF: live-mode default is OFF (D065), and
# the approvals queue starts empty. The queue is populated only via
# `/api/approvals/submit`, which Sprint 2 does NOT call from any live
# pathway (D065 SCAFFOLDING invariant).

_APPROVALS_TEMPLATE = r"""<!doctype html>
<html><head><meta charset=utf-8><title>Approvals - Blue Lock</title>
<style>__BASE_CSS____SKELETON_CSS__
.approvals-warn{border:1px solid var(--accent);border-radius:8px;
  padding:12px 14px;margin:0 0 16px 0;background:rgba(255,255,255,0.02)}
.approvals-warn p{margin:0 0 6px 0}
.approvals-warn p:last-child{margin-bottom:0}
.approvals-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.approval-card{border:1px solid var(--panel);border-radius:8px;
  padding:14px;background:var(--panel-solid,#1a1a20)}
.approval-card.pending{border-color:var(--accent)}
.approval-card h3{margin:0 0 6px 0;font-size:16px}
.approval-card .meta{color:var(--dim);font-size:12px;margin:4px 0}
.approval-card .params{display:grid;grid-template-columns:auto 1fr;
  gap:4px 8px;font-size:13px;margin:6px 0}
.approval-card .rationale{font-size:13px;font-style:italic;
  color:var(--dim);margin:6px 0}
.approval-card .countdown{font-family:monospace;color:var(--accent);
  margin:6px 0}
.approval-card .actions{display:flex;gap:8px;margin-top:8px}
.approval-card .actions button{flex:1;padding:10px;border:0;
  border-radius:6px;cursor:pointer;font-weight:bold}
.approval-card .approve{background:#2a7f4a;color:#fff}
.approval-card .reject{background:#a94a4a;color:#fff}
.approval-card .reject-reason{width:100%;margin-top:6px;padding:6px;
  background:transparent;color:inherit;border:1px solid var(--dim);
  border-radius:4px;font-family:inherit;font-size:13px}
.approval-card.approved{opacity:0.7;border-color:#2a7f4a}
.approval-card .execute{background:#8a6d1f;color:#fff;width:100%;
  margin-top:8px;padding:10px;border:0;border-radius:6px;
  cursor:pointer;font-weight:bold}
.approval-card .exec-note{font-size:12px;color:var(--dim);margin-top:8px}
.approval-card .exec-result{font-size:12px;font-family:monospace;
  margin-top:6px;word-break:break-all}
.exec-warn{border:1px solid #8a6d1f;border-radius:8px;
  padding:12px 14px;margin:0 0 16px 0;background:rgba(138,109,31,.08)}
.exec-warn p{margin:0 0 6px 0}
.exec-warn p:last-child{margin-bottom:0}
.approval-card.rejected{opacity:0.5;border-color:#a94a4a}
.approval-card.timed_out{opacity:0.4;border-color:var(--dim)}
.approval-card.approval_expired{opacity:0.4;border-color:var(--dim)}
.approval-card .status-pill{font-size:11px;text-transform:uppercase;
  padding:2px 6px;border-radius:3px;background:rgba(255,255,255,0.06)}
.approvals-section{margin:16px 0}
.approvals-section h2{margin:0 0 8px 0;font-size:15px}
@media (max-width: 700px){
  .approvals-grid{grid-template-columns:1fr}
}
</style></head>
<body>
__NAV__
<main>
<h1>Approvals queue</h1>
<div class="approvals-warn" id="warn-body">
<p class="dim">Loading warning...</p>
</div>

<div class="exec-warn" id="exec-warn" style="display:none"></div>

<div class="approvals-section">
<h2>Pending <span id="pending-count" class="dim"></span></h2>
<div id="pending-body" class="approvals-grid"></div>
</div>

<div class="approvals-section">
<h2>Recent (approved / rejected / timed out / expired)</h2>
<div id="recent-body" class="approvals-grid"></div>
</div>

<p class="dim" style="margin-top:20px;font-size:12px">
Sprint 2b caveat: approved entries can be executed against a DEMO
account only (F018 executor -- default disabled, demo-server
allowlist, 0.01-lot cap). No live pathway feeds proposals into
<code>submit()</code>; squad wiring is future-sprint work. Live-mode
default OFF at <a href="/settings/live-mode">/settings/live-mode</a>.
</p>
</main>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];
  });
}
function fmt(x){ return (typeof x === "number") ? x.toFixed(4) : "-"; }

function statusPill(s){
  return '<span class="status-pill">'+esc(s)+'</span>';
}

// F018 -- executor readiness, refreshed alongside the queue.
// States: disabled (default) / not-on-windows / ready.
var execState = {state: "disabled", enabled: false};

function cardHtml(entry, includeActions){
  const cls = "approval-card " + esc(entry.status);
  var actions = "";
  if(includeActions){
    actions = '<div class="actions">'+
      '<button class="approve" data-id="'+esc(entry.id)+'">Approve</button>'+
      '<button class="reject" data-id="'+esc(entry.id)+'">Reject</button>'+
      '</div>'+
      '<input class="reject-reason" data-id="'+esc(entry.id)+
      '" placeholder="Reason (optional; sent only on Reject)" />';
  }
  if(entry.status === "approved"){
    if(execState.state === "ready"){
      actions += '<button class="execute" data-id="'+esc(entry.id)+
        '">Execute (DEMO account)</button>'+
        '<div class="exec-result" data-exec-result="'+esc(entry.id)+
        '"></div>';
    } else if(execState.state === "not-on-windows"){
      actions += '<div class="exec-note">Executor enabled, but '+
        'MetaTrader5 is not available on this OS - run the platform '+
        'on the Windows VM to execute.</div>';
    } else {
      actions += '<div class="exec-note">Demo executor disabled '+
        '([live_executor] enabled = false).</div>';
    }
  }
  // A005: approved entries carry their own freshness deadline --
  // the countdown flips to the approved-TTL clock after approval.
  const timeoutEpoch = (entry.status === "approved")
    ? (entry.approved_expires_at_epoch || 0)
    : (entry.timeout_at_epoch || 0);
  const cdLabel = (entry.status === "approved")
    ? "approval expires in " : "timeout in ";
  const showCountdown = includeActions ||
    (entry.status === "approved" && timeoutEpoch > 0);
  const params = '<div class="params">'+
    '<span class="dim">side</span><span>'+esc(entry.side)+'</span>'+
    '<span class="dim">size</span><span>'+esc(entry.size)+'</span>'+
    '<span class="dim">entry</span><span>'+fmt(entry.entry)+'</span>'+
    '<span class="dim">stop</span><span>'+fmt(entry.stop)+'</span>'+
    '<span class="dim">TP</span><span>'+fmt(entry.take_profit)+'</span>'+
    '<span class="dim">worst</span><span>$'+fmt(
      (entry.risk_snapshot||{}).worst_case_loss)+'</span>'+
    '</div>';
  return '<div class="'+cls+'" data-id="'+esc(entry.id)+
    '" data-timeout="'+timeoutEpoch+'" data-cd-label="'+cdLabel+'">'+
    '<h3>'+esc(entry.symbol)+' '+statusPill(entry.status)+'</h3>'+
    '<div class="meta">'+esc(entry.source_agent)+' &middot; '+
      esc(entry.timestamp)+'</div>'+
    params+
    '<div class="rationale">'+esc(entry.rationale)+'</div>'+
    (showCountdown ? '<div class="countdown" data-cd="'+
      esc(entry.id)+'">--</div>' : "")+
    actions+'</div>';
}

async function fetchList(status){
  const r = await fetch("/api/approvals/list?status="+encodeURIComponent(status),
                        {cache:"no-store"});
  if(r.status === 401) return {__auth__: true};
  if(!r.ok) return {__error__: "HTTP " + r.status};
  return await r.json();
}

function wireActions(){
  document.querySelectorAll(".approve").forEach(function(btn){
    btn.onclick = async function(){
      const id = btn.getAttribute("data-id");
      await fetch("/api/approvals/"+encodeURIComponent(id)+"/approve",
                  {method:"POST"});
      refresh();
    };
  });
  document.querySelectorAll(".reject").forEach(function(btn){
    btn.onclick = async function(){
      const id = btn.getAttribute("data-id");
      const ta = document.querySelector('.reject-reason[data-id="'+id+'"]');
      const reason = ta ? ta.value : "";
      await fetch("/api/approvals/"+encodeURIComponent(id)+"/reject",
                  {method:"POST",
                   headers:{"Content-Type":"application/json"},
                   body: JSON.stringify({reason: reason})});
      refresh();
    };
  });
  document.querySelectorAll(".execute").forEach(function(btn){
    btn.onclick = async function(){
      const id = btn.getAttribute("data-id");
      if(!confirm("Send this order to the DEMO account? This is "+
                  "single-use: the approval is consumed whether the "+
                  "send fills or errors.")) return;
      btn.disabled = true;
      var out = {status: "error", reason: "request failed"};
      try{
        const r = await fetch("/api/executor/execute/"+
                              encodeURIComponent(id), {method:"POST"});
        out = await r.json();
      }catch(e){}
      const box = document.querySelector(
        '.exec-result[data-exec-result="'+id+'"]');
      if(box){
        box.textContent = out.status + ": " +
          (out.status === "filled" ? ("ticket " + out.ticket)
                                   : (out.reason || ""));
      }
      refresh();
    };
  });
}

async function loadExecutor(){
  // Readiness first (drives the button), warning copy second.
  try{
    const r = await fetch("/api/executor/status", {cache:"no-store"});
    if(r.ok) execState = await r.json();
  }catch(e){}
  const warnBox = document.getElementById("exec-warn");
  if(!warnBox) return;
  if(!execState.enabled){ warnBox.style.display = "none"; return; }
  try{
    const r = await fetch("/api/executor/warning", {cache:"no-store"});
    if(!r.ok) return;
    const j = await r.json();
    const paras = String(j.body||"").split(/\n\n+/).map(function(p){
      return "<p>"+esc(p)+"</p>";
    }).join("");
    if(paras){ warnBox.innerHTML = paras; warnBox.style.display = ""; }
  }catch(e){}
}

function tickCountdowns(){
  const now = Date.now() / 1000;
  document.querySelectorAll(".countdown[data-cd]").forEach(function(el){
    const card = el.closest(".approval-card");
    if(!card) return;
    const to = parseFloat(card.getAttribute("data-timeout") || "0");
    const label = card.getAttribute("data-cd-label") || "timeout in ";
    const s = Math.max(0, Math.floor(to - now));
    const mm = String(Math.floor(s/60)).padStart(2,"0");
    const ss = String(s%60).padStart(2,"0");
    el.textContent = label + mm + ":" + ss;
    if(s === 0) el.textContent = "expired -- reap on next poll";
  });
}

async function loadWarning(){
  const box = document.getElementById("warn-body");
  try{
    const r = await fetch("/api/approvals/warning", {cache:"no-store"});
    if(!r.ok){ box.innerHTML = '<p class="dim">Approval warning unavailable.</p>'; return; }
    const j = await r.json();
    const paras = String(j.body||"").split(/\n\n+/).map(function(p){
      return "<p>"+esc(p)+"</p>";
    }).join("");
    box.innerHTML = paras;
  }catch(e){
    box.innerHTML = '<p class="dim">Approval warning unavailable.</p>';
  }
}

async function refresh(){
  const pendingBox = document.getElementById("pending-body");
  const recentBox  = document.getElementById("recent-body");
  await withStates(pendingBox, function(){ return fetchList("pending"); },
    function(state){
      const rows = state.entries || [];
      document.getElementById("pending-count").textContent =
        rows.length ? "(" + rows.length + ")" : "(0)";
      pendingBox.innerHTML = rows.map(function(e){
        return cardHtml(e, true);
      }).join("");
      wireActions();
      tickCountdowns();
      return null;
    }, {emptyCopyKey: "no_data_yet"});

  await withStates(recentBox, function(){ return fetchList("all"); },
    function(state){
      const rows = (state.entries || []).filter(function(e){
        return e.status !== "pending";
      }).slice(0, 20);
      recentBox.innerHTML = rows.length ? rows.map(function(e){
        return cardHtml(e, false);
      }).join("") : '<div class="dim">Nothing resolved yet.</div>';
      wireActions();  // F018 Execute buttons live on approved cards here
      return null;
    }, {emptyCopyKey: "no_data_yet"});
}

loadWarning();
loadExecutor().then(refresh);
setInterval(refresh, 3000);
setInterval(loadExecutor, 15000);
setInterval(tickCountdowns, 1000);
</script></body></html>"""


APPROVALS_PAGE = (_APPROVALS_TEMPLATE
                  .replace("__BASE_CSS__", _BASE_CSS)
                  .replace("__SKELETON_CSS__", _SKELETON_CSS)
                  .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                  .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                  .replace("__NAV__", nav('approvals')))


_LIVE_MODE_TEMPLATE = r"""<!doctype html>
<html><head><meta charset=utf-8><title>Live mode - Blue Lock</title>
<style>__BASE_CSS____SKELETON_CSS__
.lm-state{font-size:22px;font-weight:bold;padding:12px 16px;
  border-radius:8px;display:inline-block;margin:8px 0}
.lm-state.on{background:#a94a4a;color:#fff}
.lm-state.off{background:var(--panel);color:var(--dim);
  border:1px solid var(--dim)}
.lm-warn{border:1px solid var(--accent);border-radius:8px;
  padding:14px 16px;margin:12px 0;background:rgba(255,255,255,0.02);
  max-height:360px;overflow-y:auto}
.lm-warn p{margin:0 0 8px 0}
.lm-warn p:last-child{margin-bottom:0}
.lm-ceremony{border:1px dashed var(--accent);border-radius:8px;
  padding:14px 16px;margin:12px 0}
.lm-ceremony label{display:block;margin:8px 0}
.lm-ceremony input[type=text]{width:100%;padding:8px;
  background:transparent;color:inherit;border:1px solid var(--dim);
  border-radius:4px;font-family:monospace;font-size:14px}
.lm-actions{display:flex;gap:8px;margin-top:12px}
.lm-actions button{padding:10px 16px;border:0;border-radius:6px;
  font-weight:bold;cursor:pointer}
.lm-enable{background:#a94a4a;color:#fff}
.lm-enable:disabled{opacity:0.4;cursor:not-allowed}
.lm-cancel{background:var(--panel);color:var(--dim);
  border:1px solid var(--dim)}
.lm-disable{background:#4a7f6a;color:#fff}
@media (max-width: 700px){
  .lm-actions{flex-direction:column}
}
</style></head>
<body>
__NAV__
<main>
<h1>Live mode</h1>
<p class="dim">
This toggle controls whether the platform is allowed to send live
orders to your broker. Default is OFF; enabling requires a
deliberate ceremony. Disabling is one click.
</p>

<div id="lm-current" class="lm-state off">Loading...</div>

<section id="lm-off-section" style="display:none">
  <h2>Enable live mode</h2>
  <div id="lm-warn" class="lm-warn">
    <p class="dim">Loading warning...</p>
  </div>
  <div class="lm-ceremony">
    <label>
      <input type="checkbox" id="lm-ack" />
      I understand this will place real orders with real money.
    </label>
    <label>
      Type <code>ENABLE LIVE MODE</code> to confirm:
      <input type="text" id="lm-confirm" placeholder="ENABLE LIVE MODE"
             autocomplete="off" />
    </label>
    <div class="lm-actions">
      <button id="lm-enable-btn" class="lm-enable" disabled>Enable</button>
      <a class="lm-cancel" href="/hq" style="text-decoration:none;
         display:inline-block;padding:10px 16px;border-radius:6px;
         border:1px solid var(--dim)">Cancel</a>
    </div>
  </div>
</section>

<section id="lm-on-section" style="display:none">
  <h2>Live mode is ON</h2>
  <p class="dim">
    The platform is authorised to send live orders to your broker
    subject to the approval queue at <a href="/approvals">/approvals</a>,
    the kill-switches at <a href="/settings/kill-switches">/settings/kill-switches</a>,
    and the risk budget at <a href="/risk">/risk</a>.
  </p>
  <div class="lm-actions">
    <button id="lm-disable-btn" class="lm-disable">Turn off live mode</button>
  </div>
</section>
</main>

<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];
  });
}
async function fetchStatus(){
  const r = await fetch("/api/live-mode/status", {cache:"no-store"});
  if(!r.ok) return {enabled: false, __error__: r.status};
  return await r.json();
}
async function loadWarning(){
  const box = document.getElementById("lm-warn");
  try{
    const r = await fetch("/api/live-mode/warning", {cache:"no-store"});
    if(!r.ok){ box.innerHTML = '<p class="dim">Warning unavailable.</p>'; return; }
    const j = await r.json();
    const paras = String(j.body||"").split(/\n\n+/).map(function(p){
      return "<p>"+esc(p)+"</p>";
    }).join("");
    box.innerHTML = paras;
  }catch(e){
    box.innerHTML = '<p class="dim">Warning unavailable.</p>';
  }
}
function updateEnableButton(){
  const ack = document.getElementById("lm-ack").checked;
  const conf = document.getElementById("lm-confirm").value.trim();
  document.getElementById("lm-enable-btn").disabled =
    !(ack && conf === "ENABLE LIVE MODE");
}
async function render(){
  const s = await fetchStatus();
  const cur = document.getElementById("lm-current");
  if(s.enabled){
    cur.className = "lm-state on";
    cur.textContent = "ON -- live orders are authorised";
    document.getElementById("lm-off-section").style.display = "none";
    document.getElementById("lm-on-section").style.display = "block";
  } else {
    cur.className = "lm-state off";
    cur.textContent = "OFF -- no live orders will be sent";
    document.getElementById("lm-off-section").style.display = "block";
    document.getElementById("lm-on-section").style.display = "none";
    loadWarning();
  }
}
document.addEventListener("change", function(e){
  if(e.target && e.target.id === "lm-ack") updateEnableButton();
});
document.addEventListener("input", function(e){
  if(e.target && e.target.id === "lm-confirm") updateEnableButton();
});
document.addEventListener("click", async function(e){
  if(e.target && e.target.id === "lm-enable-btn"){
    const ack = document.getElementById("lm-ack").checked;
    const conf = document.getElementById("lm-confirm").value.trim();
    const r = await fetch("/api/live-mode/enable", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({acknowledged: ack, confirmation: conf})});
    if(r.ok) render();
  } else if(e.target && e.target.id === "lm-disable-btn"){
    await fetch("/api/live-mode/disable", {method:"POST"});
    render();
  }
});
render();
</script></body></html>"""


LIVE_MODE_TOGGLE_PAGE = (_LIVE_MODE_TEMPLATE
                         .replace("__BASE_CSS__", _BASE_CSS)
                         .replace("__SKELETON_CSS__", _SKELETON_CSS)
                         .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
                         .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
                         .replace("__NAV__", nav('live-mode')))


# ---------------------------------------------------------------------------
# F014 -- Alerts stream page
# ---------------------------------------------------------------------------
#
# `/alerts` opens an EventSource to `/api/alerts/stream` and displays
# a rolling list of events (last 100, newest-first). Filter chips per
# event type + a "Send test alert" button that fires
# POST /api/alerts/test.

_ALERTS_TEMPLATE = r"""<!doctype html>
<html><head><meta charset=utf-8><title>Alerts - Blue Lock</title>
<style>__BASE_CSS____SKELETON_CSS__
.alerts-topbar{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px 0}
.alerts-chip{padding:6px 10px;border-radius:14px;background:var(--panel);
  color:var(--dim);border:1px solid var(--dim);cursor:pointer;font-size:12px}
.alerts-chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.alerts-actions{display:flex;gap:8px;margin:8px 0}
.alerts-actions button{padding:8px 12px;border:0;border-radius:6px;
  cursor:pointer;background:var(--accent);color:#fff;font-weight:bold}
.alerts-actions .connection{font-size:12px;color:var(--dim);
  align-self:center;margin-left:auto}
.alerts-actions .connection.live{color:var(--accent)}
.alerts-list{display:flex;flex-direction:column;gap:8px}
.alert-row{border:1px solid var(--panel);border-radius:6px;padding:10px 12px}
.alert-row .head{display:flex;justify-content:space-between;
  align-items:baseline;margin:0 0 4px 0}
.alert-row .type{font-weight:bold;text-transform:uppercase;font-size:12px}
.alert-row .ts{color:var(--dim);font-size:11px;font-family:monospace}
.alert-row .payload{font-family:monospace;font-size:12px;
  color:var(--dim);white-space:pre-wrap;word-break:break-all}
@media (max-width: 700px){
  .alerts-topbar{gap:6px}
  .alerts-actions{flex-direction:column;align-items:stretch}
  .alerts-actions .connection{margin-left:0}
}
</style></head>
<body>
__NAV__
<main>
<h1>Alerts</h1>
<p class="dim">
Live event stream (SSE). Filter by type below. Sprint 2 caveat:
Sprint 2 does not publish events from any live pathway -- only the
"Send test alert" button below produces events.
</p>

<div class="alerts-topbar" id="alerts-chips"></div>

<div class="alerts-actions">
  <button id="alerts-test-btn">Send test alert</button>
  <span id="alerts-connection" class="connection">connecting...</span>
</div>

<div id="alerts-list" class="alerts-list"></div>
</main>
<script>__ERROR_COPY_JS__
__WITH_STATES_JS__
const EVENT_TYPES = [
  "trade_fill","stop_hit","kill_switch_trip","risk_budget_breach",
  "approval_submitted","platform_down","watchdog_alert"
];
const ACTIVE = new Set(EVENT_TYPES);

function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];
  });
}

function renderChips(){
  const box = document.getElementById("alerts-chips");
  box.innerHTML = EVENT_TYPES.map(function(t){
    const on = ACTIVE.has(t) ? "on" : "";
    return '<span class="alerts-chip '+on+'" data-t="'+esc(t)+'">'+
      esc(t)+'</span>';
  }).join("");
  box.querySelectorAll(".alerts-chip").forEach(function(c){
    c.onclick = function(){
      const t = c.getAttribute("data-t");
      if(ACTIVE.has(t)) ACTIVE.delete(t); else ACTIVE.add(t);
      renderChips();
      renderList();
    };
  });
}

const EVENTS = [];

function addEvent(ev){
  EVENTS.unshift(ev);
  if(EVENTS.length > 100) EVENTS.length = 100;
  renderList();
}

function renderList(){
  const box = document.getElementById("alerts-list");
  const rows = EVENTS.filter(function(e){ return ACTIVE.has(e.type); });
  if(rows.length === 0){
    box.innerHTML = '<div class="dim">No events yet. Try "Send test alert".</div>';
    return;
  }
  box.innerHTML = rows.map(function(e){
    const p = JSON.stringify(e.payload || {}, null, 2);
    return '<div class="alert-row">'+
      '<div class="head">'+
      '<span class="type">'+esc(e.type)+'</span>'+
      '<span class="ts">'+esc(e.ts)+'</span>'+
      '</div>'+
      '<div class="payload">'+esc(p)+'</div>'+
      '</div>';
  }).join("");
}

function openStream(){
  const conn = document.getElementById("alerts-connection");
  try{
    const es = new EventSource("/api/alerts/stream?token="+
      encodeURIComponent(window.__BLUELOCK_TOKEN__ || ""));
    es.onopen = function(){
      conn.classList.add("live");
      conn.textContent = "connected";
    };
    es.onerror = function(){
      conn.classList.remove("live");
      conn.textContent = "reconnecting...";
    };
    EVENT_TYPES.forEach(function(t){
      es.addEventListener(t, function(msg){
        try{ addEvent(JSON.parse(msg.data)); }catch(e){}
      });
    });
  }catch(e){
    conn.textContent = "SSE unsupported (fallback poll)";
  }
}

document.addEventListener("click", async function(e){
  if(e.target && e.target.id === "alerts-test-btn"){
    await fetch("/api/alerts/test", {method:"POST"});
  }
});

renderChips();
renderList();
openStream();
</script></body></html>"""


ALERTS_PAGE = (_ALERTS_TEMPLATE
               .replace("__BASE_CSS__", _BASE_CSS)
               .replace("__SKELETON_CSS__", _SKELETON_CSS)
               .replace("__ERROR_COPY_JS__", _ERROR_COPY_JS)
               .replace("__WITH_STATES_JS__", _WITH_STATES_JS)
               .replace("__NAV__", nav('alerts')))
