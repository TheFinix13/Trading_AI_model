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


HUB_PAGE = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading platform</title><style>{_BASE_CSS}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}}
.tile{{background:var(--panel);border:1px solid var(--border);border-radius:12px;
  padding:22px 24px;display:block;color:var(--fg)}}
.tile:hover{{border-color:var(--accent);text-decoration:none}}
.tile h2{{margin:0 0 6px;font-size:18px}}
.tile p{{margin:6px 0 0;color:var(--dim);font-size:13.5px}}
</style></head><body>
<h1>Multi-pair trading platform</h1>
<div class="sub">next-gen line &middot; v1 trades on demo MT5 &middot; v2 is simulation-only research until graduated</div>
{nav('hub')}
<div class="tiles">
<a class="tile" href="/v1"><h2>v1 &mdash; Zones agent <span class="badge alive">live &middot; demo MT5</span></h2>
<p>The H4 supply/demand zones agent running on the VM (main branch).
Open positions, day PnL, guards, kill switches, and a live decision feed
of every signal it evaluated, blocked, or traded. Auto-refreshes every 10&nbsp;s.</p></a>
<a class="tile" href="/v2"><h2>v2 &mdash; Blue Lock squad <span class="badge sim">sim-only</span></h2>
<p>The M001 multi-agent ensemble as a football match: agents positioned on a
pitch, proposals as passes and shots, aggregator tackles, Sentinel wall,
goals on winning trades. Plays back walk-forward replay evidence today; the
same page will tail a live paper-mode stream when the squad graduates.</p></a>
</div>
</body></html>"""


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


V2_PAGE = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue Lock squad — pitch (v2)</title>
<style>{_BASE_CSS}
.layout{{display:grid;grid-template-columns:minmax(420px,1.4fr) minmax(320px,1fr);gap:16px}}
@media (max-width: 900px){{ .layout{{grid-template-columns:1fr}} }}
#pitchwrap{{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px}}
#pitch{{width:100%;height:auto;display:block;border-radius:8px}}
.controls{{display:flex;gap:10px;align-items:center;margin:10px 0 4px;flex-wrap:wrap}}
.controls button{{background:#21262d;color:var(--fg);border:1px solid var(--border);
  border-radius:8px;padding:6px 16px;font-size:13px;cursor:pointer}}
.controls button:hover{{border-color:var(--accent)}}
.controls select{{background:#21262d;color:var(--fg);border:1px solid var(--border);
  border-radius:8px;padding:5px 10px;font-size:13px}}
#clock{{font-variant-numeric:tabular-nums;font-weight:700;font-size:15px}}
#score{{font-size:15px}} #score b{{color:var(--green)}}
.side .card{{margin-bottom:14px}}
.tkr{{max-height:340px;overflow-y:auto}}
.tk{{display:flex;gap:8px;padding:3px 0;border-bottom:1px solid #1c2129;font-size:12.3px;align-items:baseline}}
.tk:last-child{{border-bottom:none}}
.tk .t{{color:var(--dim);white-space:nowrap;font-variant-numeric:tabular-nums;font-size:11px}}
.tk .who{{font-weight:700;white-space:nowrap}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid var(--border)}}
th{{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
tr:last-child td{{border-bottom:none}}
.gflash{{position:fixed;left:50%;top:38%;transform:translate(-50%,-50%);
  font-size:54px;font-weight:900;color:var(--green);text-shadow:0 0 30px rgba(63,185,80,.8);
  opacity:0;pointer-events:none;transition:opacity .2s;z-index:50;letter-spacing:.1em}}
</style></head><body>
<h1>Blue Lock squad — the pitch <span class="dim">v2 · M001 ensemble</span>
 <span class="badge sim">sim-only — not trading real lots</span></h1>
<div class="sub">Walk-forward replay played as a match: passes are proposals, tackles are
aggregator rejections, the wall is Sentinel, goals are winning trades. Live paper-mode
stream plugs into this same page when the squad graduates.</div>
{nav('v2')}
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
  <svg id="pitch" viewBox="0 0 100 130" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="side">
  <div class="card"><h2 style="margin:0 0 8px;font-size:15px">Match ticker</h2><div class="tkr" id="ticker"></div></div>
  <div class="card"><h2 style="margin:0 0 8px;font-size:15px">League table (this match)</h2>
    <table id="league"><tr><th>Player</th><th>Props</th><th>Blocked</th><th>Trades</th><th>Goals</th><th>Pips</th><th>TQS</th></tr></table></div>
</div>
</div>
<div class="gflash" id="gflash">GOAL!</div>
<script>
const NS="http://www.w3.org/2000/svg";
let roster={{}}, events=[], cursor=0, playing=false, timer=null, goals=0, misses=0;
function esc(x){{ const d=document.createElement("div"); d.innerText=String(x); return d.innerHTML; }}
function el(tag,attrs){{ const e=document.createElementNS(NS,tag);
  for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }}

function drawPitch(){{
  const svg=document.getElementById("pitch"); svg.innerHTML="";
  svg.appendChild(el("rect",{{x:0,y:0,width:100,height:130,fill:"var(--pitch)",rx:2}}));
  // outline + halfway + centre circle + boxes (y grows toward opponent goal at top? we use top=goal)
  const line={{stroke:"var(--line)","stroke-width":0.5,fill:"none"}};
  svg.appendChild(el("rect",{{x:3,y:3,width:94,height:124,...line}}));
  svg.appendChild(el("line",{{x1:3,y1:65,x2:97,y2:65,...line}}));
  svg.appendChild(el("circle",{{cx:50,cy:65,r:10,...line}}));
  svg.appendChild(el("rect",{{x:30,y:3,width:40,height:14,...line}}));   // opponent box (top)
  svg.appendChild(el("rect",{{x:30,y:113,width:40,height:14,...line}})); // own box
  svg.appendChild(el("rect",{{x:40,y:1,width:20,height:2,fill:"#e6edf3",opacity:.85}})); // goal
  const g=el("g",{{id:"anim"}}); svg.appendChild(g);
  for(const [aid,r] of Object.entries(roster)){{
    const px=r.x, py=130-(r.y*1.2)-5;   // roster y grows toward goal; goal is at top
    const pg=el("g",{{id:"pl_"+aid,transform:`translate(${{px}},${{py}})`,style:"cursor:default"}});
    pg.appendChild(el("circle",{{r:3.4,fill:r.color,stroke:"#0d1117","stroke-width":0.5}}));
    const num=el("text",{{y:1.2,"text-anchor":"middle","font-size":3,fill:"#0d1117","font-weight":"800"}});
    num.textContent=r.num; pg.appendChild(num);
    const nm=el("text",{{y:6.6,"text-anchor":"middle","font-size":2.6,fill:"#e6edf3"}});
    nm.textContent=r.name; pg.appendChild(nm);
    const halo=el("circle",{{r:3.4,fill:"none",stroke:r.color,"stroke-width":0,id:"halo_"+aid}});
    pg.appendChild(halo);
    svg.appendChild(pg);
  }}
}}
function playerPos(aid){{ const r=roster[aid];
  return r? [r.x, 130-(r.y*1.2)-5] : [50,65]; }}
function pulse(aid,color){{
  const h=document.getElementById("halo_"+aid); if(!h) return;
  h.setAttribute("stroke",color); h.setAttribute("stroke-width",1.4); h.setAttribute("r",3.4);
  let r=3.4; const iv=setInterval(()=>{{ r+=0.9; h.setAttribute("r",r);
    h.setAttribute("stroke-width",Math.max(0,1.4-(r-3.4)*0.18));
    if(r>10){{clearInterval(iv); h.setAttribute("stroke-width",0);}} }},30);
}}
function ball(from,to,color,dashed){{
  const g=document.querySelector("#anim");
  const ln=el("line",{{x1:from[0],y1:from[1],x2:from[0],y2:from[1],stroke:color,
    "stroke-width":0.7,opacity:0.9,...(dashed?{{"stroke-dasharray":"1.5 1.2"}}:{{}})}});
  g.appendChild(ln);
  const b=el("circle",{{cx:from[0],cy:from[1],r:1.2,fill:"#fff",stroke:color,"stroke-width":0.5}});
  g.appendChild(b);
  const steps=14; let i=0;
  const iv=setInterval(()=>{{ i++;
    const x=from[0]+(to[0]-from[0])*i/steps, y=from[1]+(to[1]-from[1])*i/steps;
    b.setAttribute("cx",x); b.setAttribute("cy",y);
    ln.setAttribute("x2",x); ln.setAttribute("y2",y);
    if(i>=steps){{ clearInterval(iv);
      setTimeout(()=>{{b.remove(); ln.style.transition="opacity .6s"; ln.style.opacity=0;
        setTimeout(()=>ln.remove(),700);}},150); }} }},22);
}}
function goalFlash(){{ const f=document.getElementById("gflash");
  f.style.opacity=1; setTimeout(()=>f.style.opacity=0,900); }}

function tick(ev){{
  const tk=document.getElementById("ticker");
  const r=roster[ev.agent]||{{name:ev.agent,color:"#8b949e"}};
  let msg="", color=r.color;
  if(ev.type==="proposal") msg=`proposes ${{ev.dir.toUpperCase()}} ${{ev.symbol}} (conv ${{ev.conviction}})`;
  else if(ev.type==="blocked") msg=ev.rule?`blocked by SENTINEL — ${{ev.reason}}`:
    `tackled by ${{(roster[ev.by]||{{name:ev.by}}).name}} on ${{ev.symbol}}`;
  else if(ev.type==="open") msg=`SHOT — ${{ev.dir.toUpperCase()}} ${{ev.symbol}} executed`;
  else if(ev.type==="close") msg=ev.goal?
    `GOAL! +${{ev.pnl_pips}} pips on ${{ev.symbol}} (${{ev.exit_reason}}${{ev.tqs!=null?", TQS "+ev.tqs:""}})`:
    `miss — ${{ev.pnl_pips}} pips on ${{ev.symbol}} (${{ev.exit_reason}})`;
  const div=document.createElement("div"); div.className="tk";
  div.innerHTML=`<span class="t">${{esc((ev.t||"").slice(0,16))}}</span>`+
    `<span class="who" style="color:${{color}}">${{esc(r.name)}}</span><span>${{esc(msg)}}</span>`;
  tk.prepend(div);
  while(tk.children.length>80) tk.lastChild.remove();
}}

function animate(ev){{
  const p=playerPos(ev.agent);
  if(ev.type==="proposal"){{ pulse(ev.agent,"#58a6ff"); ball(p,[50,30],"#58a6ff",true); }}
  else if(ev.type==="blocked"){{
    const q=ev.rule? [50,110] : playerPos(ev.by);
    pulse(ev.agent,"#f85149"); ball(p,q,"#f85149",true);
    if(!ev.rule) pulse(ev.by,"#d29922");
  }}
  else if(ev.type==="open"){{ pulse(ev.agent,"#3fb950"); ball(p,[50,8],"#3fb950",false); }}
  else if(ev.type==="close"){{
    if(ev.goal){{ goals++; pulse(ev.agent,"#3fb950"); ball([50,8],[50,2],"#3fb950",false); goalFlash(); }}
    else {{ misses++; pulse(ev.agent,"#8b949e"); }}
    document.getElementById("goals").innerText=goals;
    document.getElementById("misses").innerText=misses;
  }}
}}

function step(){{
  if(cursor>=events.length){{ setPlaying(false); return; }}
  const ev=events[cursor++];
  document.getElementById("clock").innerText=(ev.t||"").slice(0,16)+
    `  ·  ${{cursor}}/${{events.length}}`;
  animate(ev); tick(ev);
}}
function setPlaying(on){{
  playing=on;
  document.getElementById("play").innerHTML=on?"&#10074;&#10074; Pause":"&#9654; Play";
  if(timer){{clearInterval(timer); timer=null;}}
  if(on){{ const evps=Number(document.getElementById("speed").value);
    timer=setInterval(step, 1000/evps); }}
}}

function renderLeague(summary){{
  const tbl=document.getElementById("league");
  tbl.querySelectorAll("tr:not(:first-child)").forEach(r=>r.remove());
  const rows=Object.entries(summary.per_agent||{{}})
    .sort((a,b)=>b[1].pips-a[1].pips);
  for(const [aid,d] of rows){{
    const r=roster[aid]||{{name:aid,color:"#8b949e"}};
    const tr=document.createElement("tr");
    tr.innerHTML=`<td style="color:${{r.color}};font-weight:700">${{esc(r.name)}}</td>`+
      `<td>${{d.proposals}}</td><td>${{d.blocked}}</td><td>${{d.trades}}</td>`+
      `<td>${{d.goals}}</td><td class="${{d.pips>=0?'ok':'bad'}}">${{d.pips}}</td>`+
      `<td>${{d.mean_tqs??"—"}}</td>`;
    tbl.appendChild(tr);
  }}
}}

async function loadMatch(id){{
  setPlaying(false); events=[]; cursor=0; goals=0; misses=0;
  document.getElementById("ticker").innerHTML="";
  document.getElementById("goals").innerText="0";
  document.getElementById("misses").innerText="0";
  document.getElementById("clock").innerText="loading…";
  const s=await (await fetch(`/api/v2/match/${{id}}/summary`)).json();
  roster=s.roster||{{}}; drawPitch(); renderLeague(s);
  // Page through the whole timeline (chunked to keep responses small).
  let cur=0, total=1;
  while(cur<total){{
    const d=await (await fetch(`/api/v2/match/${{id}}/events?cursor=${{cur}}&limit=2000`)).json();
    events=events.concat(d.events); total=d.total; cur=d.next_cursor;
    if(!d.events.length) break;
    document.getElementById("clock").innerText=`loaded ${{cur}}/${{total}} events…`;
  }}
  document.getElementById("clock").innerText=`ready · ${{events.length}} events`;
}}

async function init(){{
  const data=await (await fetch("/api/v2/matches")).json();
  const sel=document.getElementById("match");
  if(!data.matches.length){{
    document.getElementById("clock").innerText="no replay caches found";
    drawPitch(); return;
  }}
  for(const m of data.matches){{
    const o=document.createElement("option"); o.value=m.id; o.textContent=m.label;
    sel.appendChild(o);
  }}
  sel.onchange=()=>loadMatch(sel.value);
  document.getElementById("play").onclick=()=>setPlaying(!playing);
  document.getElementById("speed").onchange=()=>{{ if(playing){{setPlaying(false);setPlaying(true);}} }};
  await loadMatch(data.matches[0].id);
}}
init();
</script></body></html>"""
