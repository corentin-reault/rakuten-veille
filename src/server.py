"""Rakuten veille dashboard — pure stdlib http.server serving the SQLite DB.

Serves:
  GET /                 -> single-page HTML UI (graph + summary + full table)
  GET /api/stats        -> {totals, daily:[{date, platform, count}], recent:[...]}
  GET /api/posts?q=&platform=&limit=&offset=
                        -> filtered rows for the full table

DB path from env DB_PATH (default /data/posts.db).
"""
import os, json, sqlite3, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DB_PATH", "/data/posts.db")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.execute("PRAGMA busy_timeout=20000")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plateforme TEXT,
    date TEXT,
    texte TEXT,
    auteur TEXT,
    url TEXT,
    mots_cles TEXT,
    content_hash TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_dedup ON posts(plateforme, content_hash);
CREATE INDEX IF NOT EXISTS idx_posts_plat_date ON posts(plateforme, date);
"""


def _ensure_schema():
    """Create the posts table if the DB is empty/new (mirrors store.py)."""
    try:
        c = sqlite3.connect(DB_PATH, timeout=20)
        c.executescript(_SCHEMA)
        c.commit()
        c.close()
    except Exception as e:
        print(f"[dashboard] init schema: {e}", file=sys.stderr)


def api_stats():
    conn = _conn()
    totals = dict(conn.execute(
        "SELECT plateforme, COUNT(*) FROM posts GROUP BY plateforme "
        "ORDER BY COUNT(*) DESC").fetchall())
    total = sum(totals.values())
    daily = [{"date": r[0], "platform": r[1], "count": r[2]}
             for r in conn.execute(
                 "SELECT substr(date,1,10) d, plateforme, COUNT(*) "
                 "FROM posts WHERE date!='' GROUP BY d, plateforme "
                 "ORDER BY d").fetchall()]
    recent = [{"date": r[0], "auteur": r[1], "texte": r[2], "url": r[3], "plateforme": r[4]}
              for r in conn.execute(
                  "SELECT date, auteur, texte, url, plateforme FROM posts "
                  "WHERE date!='' ORDER BY date DESC, id DESC LIMIT 25").fetchall()]
    conn.close()
    return {"total": total, "totals": totals, "daily": daily, "recent": recent}


def api_posts(q="", platform="", limit=500):
    conn = _conn()
    sql = "SELECT id, date, plateforme, auteur, texte, url, mots_cles FROM posts"
    conds, args = [], []
    if q:
        conds.append("(texte LIKE ? OR auteur LIKE ? OR mots_cles LIKE ?)")
        like = f"%{q}%"
        args += [like, like, like]
    if platform:
        conds.append("plateforme = ?")
        args.append(platform)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY date DESC, id DESC LIMIT ?"
    args.append(int(limit))
    cols = ["id", "date", "plateforme", "auteur", "texte", "url", "mots_cles"]
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Veille — fermeture Rakuten France</title>
<style>
  :root{--bg:#0b1220;--card:#121a2b;--border:#22304a;--text:#e6edf7;--muted:#8ea0c0;
        --acc:#38bdf8;--acc-bg:rgba(56,189,248,.1);}
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg);color:var(--text);line-height:1.45}
  .wrap{max-width:1180px;margin:0 auto;padding:max(18px,3vh) 16px 60px}
  h1{font-size:clamp(17px,4vw,22px);margin:0 0 4px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;overflow-wrap:break-word}
  h1 .dot{width:10px;height:10px;flex:0 0 10px;border-radius:50%;background:var(--ok,#34d399);box-shadow:0 0 10px var(--ok,#34d399)}
  .sub{color:var(--muted);font-size:clamp(12px,3vw,13px);margin:0 0 18px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin-bottom:20px}
  .cd{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:12px}
  .cd .n{font-size:clamp(20px,5vw,28px);font-weight:700;overflow-wrap:break-word}
  .cd .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;overflow-wrap:break-word}
  .cd.total{background:linear-gradient(160deg,rgba(56,189,248,.14),transparent);border-color:rgba(56,189,248,.4)}
  .cd.total .n{color:var(--acc)}
  .panel{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px;margin-bottom:20px}
  .panel h2{font-size:14px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);margin:0 0 12px}
  .chart-head{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px}
  .seg{display:inline-flex;background:#0b1220;border:1px solid var(--border);border-radius:10px;padding:3px;gap:2px}
  .seg label{position:relative;font-size:13px;padding:7px 14px;border-radius:8px;cursor:pointer;user-select:none;color:var(--muted);min-width:52px;text-align:center}
  .seg input{position:absolute;opacity:0;pointer-events:none}
  .seg input:checked + span{color:#fff}
  .seg label:has(input:checked){background:var(--acc-bg);color:#fff}
  .seg label:active{transform:scale(.98)}
  .chart-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .bar{cursor:pointer}
  .bar:hover{opacity:.85;stroke:#fff;stroke-width:1.5}
  #tip{position:fixed;z-index:50;pointer-events:none;opacity:0;transition:opacity .12s ease;
       background:#0f1930;border:1px solid var(--border);border-radius:10px;padding:8px 12px;
       font-size:12px;color:var(--text);box-shadow:0 6px 20px rgba(0,0,0,.45);max-width:220px}
  #tip.show{opacity:1}
  #tip .tip-p{font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px}
  #tip .tip-d{color:var(--muted);margin-top:2px}
  #tip .sw{width:10px;height:10px;border-radius:3px;display:inline-block;flex:0 0 10px}
  svg{display:block;min-width:480px;width:100%;height:auto}
  svg text{fill:var(--muted);font-size:10px;font-family:inherit}
  .lg{display:flex;flex-wrap:wrap;gap:8px 12px;font-size:12px;color:var(--muted)}
  .lg .s{display:inline-flex;align-items:center;gap:5px}
  .lg .sw{width:10px;height:10px;flex:0 0 10px;border-radius:3px;display:inline-block}
  .filt{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
  input[type=text],select{padding:10px 12px;background:#0b1220;border:1px solid var(--border);border-radius:10px;
               color:var(--text);font-size:15px;min-height:44px}
  select{appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="%238ea0c0"><path d="M6 9l6 6 6-6"/></svg>');background-repeat:no-repeat;background-position:right 12px center;padding-right:34px}
  .sc{overflow:auto;max-height:430px;border:1px solid var(--border);border-radius:10px;-webkit-overflow-scrolling:touch}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th{position:sticky;top:0;background:#0f1930;color:var(--muted);font-weight:600;z-index:1;
     text-align:left;padding:10px;border-bottom:1px solid var(--border);white-space:nowrap}
  td{padding:10px;border-bottom:1px solid var(--border);vertical-align:top;overflow-wrap:break-word;word-break:break-word}
  td.date{white-space:nowrap;color:var(--muted);font-variant-numeric:tabular-nums}
  a{color:var(--acc);text-decoration:none;word-break:break-all} a:hover{text-decoration:underline}
  .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;border:1px solid var(--border);white-space:nowrap}
  .muted{color:var(--muted)}
  tr:hover td{background:rgba(56,189,248,.04)}
  @media(prefers-reduced-motion:no-preference){.panel{animation:fade .4s ease}}
  @keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1}}
  @media(max-width:640px){
    .cards{grid-template-columns:repeat(2,1fr)}
    tr:hover td{background:none}
  }
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="dot"></span>Veille — fermeture Rakuten France</h1>
  <p class="sub" id="sub">Chargement…</p>
  <div class="cards" id="cards"></div>
  <div class="panel">
    <div class="chart-head">
      <h2 style="margin:0">Posts collectés</h2>
      <div class="seg" role="radiogroup" aria-label="Granularité du graphique">
        <label><input type="radio" name="gran" value="jour" checked onchange="setGran(this.value)"><span>Par jour</span></label>
        <label><input type="radio" name="gran" value="mois" onchange="setGran(this.value)"><span>Par mois</span></label>
      </div>
    </div>
    <div class="lg" id="legend" style="margin-bottom:12px"></div>
    <div class="chart-scroll"><svg id="chart" role="img" aria-label="Histogramme des posts par période et plateforme" viewBox="0 0 1000 320" preserveAspectRatio="xMidYMid meet"></svg></div>
    <div id="tip" role="tooltip"></div>
  </div>
  <div class="panel">
    <h2>Derniers posts</h2>
    <div class="filt">
      <input id="q" type="text" placeholder="Recherche (texte, auteur, mot-clé)" oninput="debouncedLoad()" enterkeyhint="search">
      <select id="platform" onchange="loadPosts()"><option value="">Toutes les plateformes</option></select>
    </div>
    <div class="sc"><table id="postsTbl">
      <thead><tr><th>Date</th><th>Plateforme</th><th>Auteur</th><th>Texte</th><th>Mot-clé</th></tr></thead>
      <tbody id="postsBody"><tr><td colspan="5" class="muted">…</td></tr></tbody>
    </table></div>
  </div>
</div>
<script>
const COLS={google_news:'#86d3ee',bluesky:'#0ea5e9',x:'#38bdf8',linkedin:'#6366f1',
    instagram:'#e8796c',tiktok:'#22d55e',facebook:'#3b82f6',reddit:'#f472b6',mastodon:'#a78bfa'};
const LABELS={google_news:'Google News',instagram:'Instagram',tiktok:'TikTok',facebook:'Facebook',x:'X',linkedin:'LinkedIn',bluesky:'Bluesky',reddit:'Reddit',mastodon:'Mastodon'};
const platName=p=>LABELS[p]||p;
const fmt=n=>n.toLocaleString('fr-FR');
const MONTHS=['janv','févr','mars','avr','mai','juin','juil','août','sept','oct','nov','déc'];
let gran='jour';

async function load(){
  const s=await (await fetch('/api/stats')).json();
  document.getElementById('sub').textContent=s.total+' posts collectés · mise à jour hebdomadaire';
  renderCards(s);
  renderLegend(s);
  draw(s);
  loadPosts();
  const sel=document.getElementById('platform');
  Object.keys(s.totals).sort().forEach(p=>{
    const o=document.createElement('option');o.value=p;o.textContent=platName(p);sel.appendChild(o);
  });
}
function renderCards(s){
  const plats=Object.entries(s.totals).sort((a,b)=>b[1]-a[1]);
  let html=`<div class="cd total"><div class="n">${fmt(s.total)}</div><div class="l">Total</div></div>`;
  plats.forEach(([p,n])=>{ html+=`<div class="cd"><div class="n">${fmt(n)}</div><div class="l">${platName(p)}</div></div>`; });
  document.getElementById('cards').innerHTML=html;
}
function renderLegend(s){
  const by={}; s.daily.forEach(d=>{ by[d.platform]=(by[d.platform]||0)+d.count; });
  const html=Object.keys(by).sort((a,b)=>by[b]-by[a]).map(p=>{
    const c=COLS[p]||'#94a3b8';
    return '<span class="s"><span class="sw" style="background:'+c+'"></span>'+platName(p)+'</span>';}).join('');
  document.getElementById('legend').innerHTML=html;
}
function buckets(s){
  const by={};
  s.daily.forEach(d=>{
    const key = gran==='mois' ? d.date.slice(0,7) : d.date.slice(0,10);
    (by[d.platform]=by[d.platform]||{})[key]=(by[d.platform][key]||0)+d.count;
  });
  const labels=[...new Set(s.daily.map(d=> gran==='mois' ? d.date.slice(0,7) : d.date.slice(0,10)))].sort();
  return {by,labels};
}
function axisLabel(k){
  if(gran==='mois'){ const [y,m]=k.split('-'); return MONTHS[+m-1]+' '+y; }
  return k.slice(5); // MM-DD
}
function periodTitle(k){
  if(gran==='mois'){ const [y,m]=k.split('-'); return MONTHS[+m-1]+' '+y; }
  const [y,m,d]=k.split('-');
  return d+' '+MONTHS[+m-1]+' '+y;
}
function draw(s){
  const {by,labels}=buckets(s);
  const W=1000,H=320,padL=34,padB=34,padT=10,padR=8;
  const svg=document.getElementById('chart');
  const colored=Object.keys(by).filter(p=>labels.some(d=>by[p][d]));
  // Stacked chart: the scale must fit the tallest STACK (sum of all platforms
  // in a bucket), otherwise bars above the tallest single platform are clipped
  // off the top and become invisible (e.g. Reddit under Google News in month view).
  let max=0;
  labels.forEach(d=>{ let tot=0; colored.forEach(p=>{ tot+=by[p][d]||0; }); max=Math.max(max,tot); });
  max=Math.max(max,1);
  const plotW=W-padL-padR, plotH=H-padT-padB;
  let html='';
  for(let i=0;i<=4;i++){
    const y=padT+plotH-(i/4)*plotH;
    html+=`<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="#1b273b" stroke-width="1"/>`;
    html+=`<text x="${padL-6}" y="${y+3}" text-anchor="end">${Math.round(max*i/4)}</text>`;
  }
  if(labels.length===0){
    html+='<text x="'+W/2+'" y="'+H/2+'" text-anchor="middle" class="muted">Aucune donnée</text>';
  }
  const n=labels.length;
  const slot=plotW/n;
  const bw=Math.max(slot*0.55, Math.min(slot*0.7, 40));
  labels.forEach((d,i)=>{
    const x=padL+slot*(i+0.5);
    let runY=padT+plotH;
    colored.forEach(p=>{
      const c=by[p][d]||0; if(!c) return;
      const y1=runY, h=(c/max)*plotH, y2=runY-h;
      html+=`<rect class="bar" data-p="${p}" data-period="${d}" data-n="${c}"
        x="${x-bw/2}" y="${y2}" width="${bw}" height="${h}" rx="2" fill="${COLS[p]||'#94a3b8'}"/>`;
      runY=y2;
    });
  });
  const maxLabels = gran==='mois' ? 24 : 18;
  labels.forEach((d,i)=>{
    if(n>maxLabels && i%Math.max(1,Math.floor(n/maxLabels))!==0) return;
    const x=padL+slot*(i+0.5);
    html+=`<text x="${x}" y="${H-10}" text-anchor="middle">${axisLabel(d)}</text>`;
  });
  const last=labels[n-1];
  html+=`<text x="${padL}" y="${H-26}" text-anchor="start" class="muted" font-size="9">${gran==='mois'?'par mois':'par jour'}</text>`;
  if(last) html+=`<text x="${W-padR}" y="${H-26}" text-anchor="end" class="muted" font-size="9">${last}</text>`;
  svg.innerHTML=html;
  wireTooltip();
}
const tipEl=()=>document.getElementById('tip');
function wireTooltip(){
  const svg=document.getElementById('chart');
  const tip=tipEl();
  if(!tip) return;
  svg.querySelectorAll('rect.bar').forEach(rect=>{
    rect.addEventListener('mousemove',e=>{
      const p=rect.getAttribute('data-p');
      const period=rect.getAttribute('data-period');
      const n=rect.getAttribute('data-n');
      const col=COLS[p]||'#94a3b8';
      tip.innerHTML=`<div class="tip-p"><span class="sw" style="background:${col}"></span>${platName(p)}</div>
        <div class="tip-d">${periodTitle(period)} · ${fmt(+n)} post${n==1?'':'s'}</div>`;
      tip.classList.add('show');
      const pad=14;
      let x=e.clientX+pad, y=e.clientY+pad;
      const r=tip.getBoundingClientRect();
      if(x+r.width>window.innerWidth-8) x=e.clientX-r.width-pad;
      if(y+r.height>window.innerHeight-8) y=e.clientY-r.height-pad;
      tip.style.left=x+'px'; tip.style.top=y+'px';
    });
    rect.addEventListener('mouseleave',()=>tip.classList.remove('show'));
  });
}
function setGran(v){ gran=v; load(); }
function debouncedLoad(){ clearTimeout(window._ql); window._ql=setTimeout(loadPosts,300); }
async function loadPosts(){
  const q=document.getElementById('q').value;
  const p=document.getElementById('platform').value;
  const t=document.getElementById('postsBody');
  t.innerHTML='<tr><td colspan="5" class="muted">…</td></tr>';
  try{
    const r=await fetch('/api/posts?q='+encodeURIComponent(q)+'&platform='+encodeURIComponent(p)+'&limit=150');
    const rows=await r.json();
    if(!rows.length){t.innerHTML='<tr><td colspan="5" class="muted">Aucun résultat</td></tr>';return;}
    t.innerHTML=rows.map(rw=>{
      const d=(rw.date||'').slice(0,10);
      const txt=(rw.texte||'').replace(/</g,'&lt;');
      const a=(rw.auteur||'').replace(/</g,'&lt;');
      const url=rw.url?`<a href="${rw.url}" target="_blank" rel="noopener">🔗</a>`:'';
      const mot=(rw.mots_cles||'').replace(/</g,'&lt;');
      return `<tr><td class="date">${d}</td>
        <td><span class="badge">${platName(rw.plateforme)}</span></td>
        <td>${a} ${url}</td>
        <td>${txt}</td><td class="muted">${mot}</td></tr>`;
    }).join('');
  }catch(e){ t.innerHTML='<tr><td colspan="5" class="muted">Erreur de chargement</td></tr>'; }
}
load();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # no-store: the UI is a single served HTML string with inline JS/CSS and
        # no asset versioning. Never cache it so nav/rebuild changes always show.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            self._send(200, "text/html; charset=utf-8", HTML.encode())
        elif path == "/api/stats":
            self._send(200, "application/json", json.dumps(api_stats()).encode())
        elif path == "/api/posts":
            qs = parse_qs(parsed.query)
            q = qs.get("q", [""])[0]
            p = qs.get("platform", [""])[0]
            lim = int(qs.get("limit", ["150"])[0])
            self._send(200, "application/json",
                       json.dumps(api_posts(q, p, lim)).encode())
        elif path in ("/healthz", "/livez"):
            self._send(200, "text/plain", b"ok")
        else:
            self._send(404, "text/plain", b"not found")

    def log_message(self, *a):
        pass


def main():
    _ensure_schema()
    try:
        conn = _conn()
        conn.execute("SELECT COUNT(*) FROM posts").fetchone()
        conn.close()
    except Exception as e:
        print(f"[dashboard] DB introuvable à {DB_PATH}: {e}", file=sys.stderr)
        print("[dashboard] Attente du premier run du CronJob...", file=sys.stderr)
    print(f"[dashboard] serveur sur {HOST}:{PORT}, db={DB_PATH}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()