"""Static review page: every rendered video with its captions, filterable by
format, plus a 'keep' checkbox list you can copy out. Open outputs/index.html."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .config import Config

PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MegaTravelOS çıktıları</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--mut:#6b6a66;--acc:#e4572e;--line:#e3e1dc}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1f1f1d;--ink:#f1efe9;--mut:#a3a19b;--line:#33322f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);padding:14px 16px;border-bottom:1px solid var(--line);z-index:2}
h1{margin:0 0 8px;font-size:19px}.f{display:flex;gap:6px;flex-wrap:wrap}
.f button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:99px;padding:4px 11px;cursor:pointer}
.f button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px;padding:16px}
.c{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
video{width:100%;aspect-ratio:9/16;background:#000;display:block}
.b{padding:10px 12px}.t{font-weight:650}.m{color:var(--mut);font-size:13px}
details{margin-top:6px}pre{white-space:pre-wrap;font:12.5px/1.4 ui-monospace,monospace;margin:6px 0 0}
label{display:flex;gap:6px;align-items:center;margin-top:8px;font-size:14px}
#keep{font-size:13px;color:var(--mut);margin-top:6px}
</style></head><body><header><h1>🎬 {n} video</h1><div class="f" id="f"></div><div id="keep"></div></header>
<main id="g">{cards}</main>
<script>
const fm=[...new Set([...document.querySelectorAll('.c')].map(c=>c.dataset.f))];const f=document.getElementById('f');
let cur='hepsi';function draw(){f.innerHTML='';['hepsi',...fm].forEach(x=>{const b=document.createElement('button');
b.textContent=x;b.className=x===cur?'on':'';b.onclick=()=>{cur=x;draw()};f.appendChild(b)});
document.querySelectorAll('.c').forEach(c=>c.style.display=(cur==='hepsi'||c.dataset.f===cur)?'':'none')}draw();
let keep={};try{keep=JSON.parse(localStorage.getItem('keep')||'{}')}catch(e){}
function upd(){const k=Object.keys(keep).filter(x=>keep[x]);document.getElementById('keep').textContent=k.length?('Seçilenler ('+k.length+'): '+k.join(', ')):''}
document.querySelectorAll('input[type=checkbox]').forEach(i=>{i.checked=!!keep[i.value];i.onchange=()=>{keep[i.value]=i.checked;
try{localStorage.setItem('keep',JSON.stringify(keep))}catch(e){}upd()}});upd();
</script></body></html>"""


def build(cfg: Config) -> Path:
    out_dir = cfg.ws("outputs")
    cards = []
    for mp4 in sorted(out_dir.rglob("*.mp4")):
        plan_p = cfg.ws("plans") / f"{mp4.stem}.json"
        plan = json.loads(plan_p.read_text(encoding="utf-8")) if plan_p.exists() else {}
        txt = mp4.with_suffix(".txt")
        cap = txt.read_text(encoding="utf-8") if txt.exists() else ""
        rel = mp4.relative_to(out_dir).as_posix()
        poster = mp4.with_suffix(".jpg").relative_to(out_dir).as_posix()
        cards.append(
            f'<div class="c" data-f="{html.escape(plan.get("format", mp4.parent.name))}">'
            f'<video src="{html.escape(rel)}" poster="{html.escape(poster)}" controls preload="none" playsinline></video>'
            f'<div class="b"><div class="t">{html.escape(plan.get("title") or mp4.stem)}</div>'
            f'<div class="m">{html.escape(str(plan.get("format")))} · {html.escape(str(plan.get("loc")))} · '
            f'{plan.get("duration", "?")}s</div>'
            f'<details><summary>Caption</summary><pre>{html.escape(cap)}</pre></details>'
            f'<label><input type="checkbox" value="{html.escape(mp4.stem)}"> paylaşılacak</label></div></div>')
    page = out_dir / "index.html"
    page.write_text(PAGE.replace("{n}", str(len(cards))).replace("{cards}", "\n".join(cards)), encoding="utf-8")
    return page
