/* MegaTravelOS UI — vanilla JS, no build step. Routes: #/  #/p/<project>/<tab> */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const fmtDur = s => { s = Math.round(s || 0); const m = Math.floor(s / 60), r = s % 60; return m ? `${m}:${String(r).padStart(2,"0")}` : `${r}s`; };
const FORMAT_TR = {
  city_montage:"Şehir montajı", top5:"Top 5", pov_arrival:"POV", photo_dump:"Photo dump", category:"Kategori",
  day_vlog:"Günlük vlog", funny_single:"Komik an", funny_compilation:"Komik derleme", quote:"Alıntı",
  live_reel:"Live reel", single_hook:"Tek an + hook", split_compare:"Split-screen", trip_recap:"Tatil özeti",
  clip_full:"Tam klip", slowmo:"Yavaş çekim", loop:"Loop", wait_for_it:"Sonunu bekle",
  live_boomerang:"Boomerang", live_slowmo:"Live slow-mo", live_still_reveal:"Fotoğraf sandın",
  live_with_sound:"Live + ses", photo_single:"Tek fotoğraf", longform:"Long-form"
};
const KIND_TR = {video:"Video", live:"Live Photo", photo:"Fotoğraf"};
const SEG_TR = {talk:"Konuşma", broll:"B-roll", open:"Açılış", card:"Başlık"};

async function api(path, opts = {}) {
  const r = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body});
  if (!r.ok) { let d; try { d = (await r.json()).detail } catch { d = r.statusText } throw new Error(d); }
  return r.status === 204 ? null : r.json();
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600); }

const state = { projects: [], sys: null, proj: null, pollH: null, planFilter: "all", planSel: new Set(), mediaFilter: "all", lfSel: null };

// ------------------------------------------------------------------ sidebar
async function loadSidebar() {
  [state.projects, state.sys] = await Promise.all([api("/api/projects"), api("/api/system").catch(() => null)]);
  const cur = location.hash.split("/")[2];
  $("#projectList").innerHTML = state.projects.map(p => `<a href="#/p/${esc(p.name)}/genel" class="${p.name === cur ? "on" : ""}">
    <span>${esc(p.title)}</span><span class="badge ${p.mode}">${p.mode === "longform" ? "YouTube" : "Shorts"}</span></a>`).join("")
    || `<small>Henüz proje yok</small>`;
  const s = state.sys;
  $("#sys").innerHTML = s ? `
    <div class="${s.disk_free_gb < 10 ? "warn" : ""}">💾 Boş disk: ${s.disk_free_gb} GB${s.disk_free_gb < 10 ? " — az!" : ""}</div>
    <div>${s.ollama ? "🟢" : "🔴"} Ollama ${s.ollama ? `(${s.ollama_models.length} model)` : "çalışmıyor"}</div>
    <div>${s.ffmpeg ? "🟢" : "🔴"} ffmpeg</div>` : "";
}

// ------------------------------------------------------------------ router
async function route() {
  clearInterval(state.pollH);
  closeDrawer();
  const [, page, name, tab] = location.hash.split("/");
  await loadSidebar();
  if (page === "p" && name) return projectPage(decodeURIComponent(name), tab || "genel");
  homePage();
}
window.addEventListener("hashchange", route);

function homePage() {
  const ps = state.projects;
  $("#main").innerHTML = `<div class="head"><h1>Projeler</h1></div>
   ${ps.length ? `<div class="grid steps">${ps.map(p => `<a class="panel step" href="#/p/${esc(p.name)}/genel" style="text-decoration:none">
      <span class="badge ${p.mode}" style="align-self:flex-start">${p.mode === "longform" ? "Long-form YouTube" : "Shorts / Reels / TikTok"}</span>
      <b style="font-size:17px">${esc(p.title)}</b>${p.job ? `<small>Son iş: ${esc(p.job)}</small>` : ""}</a>`).join("")}</div>`
   : `<div class="empty"><p><b>İlk projeni oluştur.</b></p><p>Bir proje = bir medya kaynağı + bir mod. Örneğin "Hong Kong Shorts" (iPhone shared album) ve "Hong Kong Vlog" (Osmo Pocket klasörü).</p>
      <button class="btn primary" onclick="openNewProject()">+ Yeni proje</button></div>`}`;
}

// ------------------------------------------------------------------ project
async function projectPage(name, tab) {
  let p;
  try { p = await api(`/api/projects/${name}`); } catch (e) { $("#main").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  state.proj = p;
  const lf = p.mode === "longform";
  const tabs = [["genel","Genel"],["medya",`Medya (${p.stats.assets})`],[lf ? "kurgu" : "planlar", lf ? "Kurgu" : `Planlar (${p.stats.plans})`],["ciktilar",`Çıktılar (${p.stats.outputs})`],["ayarlar","Ayarlar"]];
  $("#main").innerHTML = `<div class="head"><h1>${esc(p.project.title || name)}</h1>
    <span class="badge ${p.mode}">${lf ? "Long-form YouTube · 16:9" : "Shorts · 9:16"}</span></div>
    <nav class="tabs">${tabs.map(([k, l]) => `<a href="#/p/${name}/${k}" class="${k === tab ? "on" : ""}">${l}</a>`).join("")}</nav>
    <section id="tab"></section>`;
  const f = {genel: tabGenel, medya: tabMedya, planlar: tabPlanlar, kurgu: tabKurgu, ciktilar: tabCiktilar, ayarlar: tabAyarlar}[tab] || tabGenel;
  await f(p);
}

// ---------------- Genel (pipeline)
function tabGenel(p) {
  const s = p.stats, lf = p.mode === "longform";
  const src = p.project.source || {};
  const srcTxt = src.type === "photos" ? `Photos · ${(src.photos?.shared_albums || []).join(", ") || "tüm shared album'ler"}` : (src.folder || "klasör seçilmedi");
  $("#tab").innerHTML = `
  <div class="grid steps">
    <div class="panel step"><span class="n">1 · MEDYAYI AL</span><span class="big">${s.assets}</span>
      <small>${Object.entries(s.kinds).map(([k, v]) => `${v} ${KIND_TR[k] || k}`).join(" · ") || "henüz yok"}</small>
      <small title="${esc(srcTxt)}">Kaynak: ${esc(srcTxt.length > 46 ? "…" + srcTxt.slice(-44) : srcTxt)}</small>
      <div class="row"><button class="btn primary small" data-step="ingest">Medyayı tara</button></div></div>
    <div class="panel step"><span class="n">2 · ANALİZ (ses + görüntü)</span><span class="big">${s.vision_done}/${s.assets}</span>
      <small>Ses: ${s.audio_done}/${s.assets} · ${s.moments} moment${s.errors ? ` · <span style="color:var(--bad)">${s.errors} hata</span>` : ""}</small>
      <small>${s.cities.length ? "📍 " + esc(s.cities.join(", ")) : ""}</small>
      <div class="row"><button class="btn primary small" data-step="analyze" ${s.assets ? "" : "disabled"}>Analiz et</button></div></div>
    <div class="panel step"><span class="n">3 · ${lf ? "KURGU" : "PLANLAR"}</span><span class="big">${s.plans}</span>
      <small>${lf ? "Kronolojik YouTube kurgusu: bölümler, cold open, b-roll" : "Konseptler + senaryo + caption (lokal LLM)"}</small>
      <div class="row">${lf ? `<button class="btn primary small" data-step="longform" ${s.vision_done ? "" : "disabled"}>Kurgu oluştur</button>`
        : `<button class="btn primary small" data-step="direct" ${s.vision_done ? "" : "disabled"}>Planla (LLM)</button>
           <button class="btn small" data-step="direct_fast" ${s.vision_done ? "" : "disabled"} title="Şablonlarla, saniyeler içinde">Hızlı planla</button>`}</div></div>
    <div class="panel step"><span class="n">4 · RENDER</span><span class="big">${s.outputs}</span>
      <small>Henüz render edilmemiş tüm planlar</small>
      <div class="row"><button class="btn primary small" data-step="render" ${s.plans ? "" : "disabled"}>Hepsini render et</button>
      <a class="btn small" href="#/p/${p.name}/${lf ? "kurgu" : "planlar"}">Seçerek…</a></div></div>
  </div>
  <div class="panel" style="margin-top:14px" id="jobPanel"></div>`;
  $$("[data-step]").forEach(b => b.onclick = () => runJob(p.name, {step: b.dataset.step, label: b.textContent.trim()}));
  renderJob(p.job);
  pollJob(p.name);
}

async function runJob(name, body) {
  try { const j = await api(`/api/projects/${name}/jobs`, {method: "POST", body}); toast("Başladı: " + j.label);
    if (!location.hash.endsWith("/genel")) location.hash = `#/p/${name}/genel`; else { renderJob(j); pollJob(name); } }
  catch (e) { toast("⚠️ " + e.message); }
}
function renderJob(j) {
  const el = $("#jobPanel"); if (!el) return;
  if (!j) { el.innerHTML = `<h3>İş kuyruğu</h3><small>Bir adımı başlattığında ilerleme ve log burada görünür. Analiz ve render uzun sürebilir; sayfayı kapatsan da arka planda devam eder.</small>`; return; }
  const st = {running:["run","çalışıyor"], done:["ok","bitti"], failed:["bad","hata"], stopped:["bad","durduruldu"]}[j.status];
  const pr = j.progress || {};
  el.innerHTML = `<div class="row" style="justify-content:space-between"><h3 style="margin:0">${esc(j.label)}</h3>
     <div class="row"><span class="badge ${st[0]}">${st[1]}</span>${j.status === "running" ? `<button class="btn small danger" id="stopJob">Durdur</button>` : ""}</div></div>
    ${pr.total ? `<div style="margin-top:10px"><small>${esc(pr.label)} — ${pr.n}/${pr.total}</small><div class="bar"><i style="width:${pr.pct}%"></i></div></div>` : ""}
    <pre class="log" id="log">${esc(j.log.join("\n"))}</pre>`;
  const log = $("#log"); log.scrollTop = log.scrollHeight;
  const sb = $("#stopJob"); if (sb) sb.onclick = () => api(`/api/projects/${state.proj.name}/job/stop`, {method: "POST"});
}
function pollJob(name) {
  clearInterval(state.pollH);
  let wasRunning = state.proj?.job?.status === "running";
  state.pollH = setInterval(async () => {
    const j = await api(`/api/projects/${name}/job`).catch(() => null);
    renderJob(j);
    if (j && j.status !== "running") { clearInterval(state.pollH); if (wasRunning) { toast(j.status === "done" ? "✅ Bitti" : "⚠️ İş " + j.status); projectPage(name, "genel"); } }
    wasRunning = j?.status === "running";
  }, 1500);
}

// ---------------- Medya
async function tabMedya(p) {
  const items = await api(`/api/projects/${p.name}/assets`);
  const filters = [["all","Hepsi"],["video","Video"],["live","Live Photo"],["photo","Fotoğraf"],["todo","Analiz bekleyen"],["funny","Komik"],["err","Hatalı"]];
  const f = state.mediaFilter;
  const shown = items.filter(a => f === "all" || a.kind === f || (f === "todo" && !(a.audio && a.vision)) || (f === "funny" && (a.humor >= 5 || a.events.includes("laughter"))) || (f === "err" && a.error));
  $("#tab").innerHTML = `<div class="toolbar"><div class="chips">${filters.map(([k, l]) => `<button class="chip ${k === f ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}</div>
    <span class="mut">${shown.length} medya</span></div>
    ${shown.length ? `<div class="grid cards">${shown.map(a => `<div class="card" data-id="${esc(a.id)}">
      <div class="th ${a.kind === "video" ? "" : "sq"}" style="background-image:url('/api/projects/${p.name}/assets/${encodeURIComponent(a.id)}/thumb')">
        <div class="ov"><span class="badge">${KIND_TR[a.kind]}</span>${a.duration ? `<span class="badge">${fmtDur(a.duration)}</span>` : ""}
        ${a.events.includes("laughter") ? `<span class="badge">😂</span>` : ""}</div></div>
      <div class="b"><span class="t">${esc(a.summary || a.id)}</span>
      <small>${esc(a.city || "")} ${a.vision ? "· ✓ analiz" : "· analiz bekliyor"}${a.error ? " · ⚠️" : ""}</small></div></div>`).join("")}</div>`
    : `<div class="empty">Burada medya yok. Genel sekmesinden "Medyayı tara".</div>`}`;
  $$("[data-f]").forEach(b => b.onclick = () => { state.mediaFilter = b.dataset.f; tabMedya(p); });
  $$(".card[data-id]").forEach(c => c.onclick = () => mediaDrawer(p, items.find(a => a.id === c.dataset.id)));
}
function mediaDrawer(p, a) {
  const src = `/api/projects/${p.name}/assets/${encodeURIComponent(a.id)}/media`;
  openDrawer(`<h2>${esc(a.id)}</h2>
    ${a.kind === "photo" ? `<img class="prev" src="/api/projects/${p.name}/assets/${encodeURIComponent(a.id)}/thumb">` : `<video src="${src}" controls playsinline preload="metadata"></video>`}
    <dl class="kv" style="margin-top:14px">
      <dt>Tür</dt><dd>${KIND_TR[a.kind]}${a.duration ? " · " + fmtDur(a.duration) : ""}</dd>
      <dt>Yer / tarih</dt><dd>${esc([a.place, a.city].filter(Boolean).join(", ") || "-")} · ${esc((a.taken_at || "").replace("T", " ").slice(0, 16))}</dd>
      <dt>Görüntü</dt><dd>${esc(a.summary || "-")}</dd>
      <dt>Kategoriler</dt><dd>${esc(a.categories.join(", ") || "-")}</dd>
      <dt>Puanlar</dt><dd>Mizah ${a.humor ?? "-"} · Hook ${a.hook ?? "-"} · Estetik ${a.aesthetic ?? "-"}</dd>
      <dt>Sesler</dt><dd>${esc(a.events.join(", ") || "-")}</dd>
      <dt>Konuşma</dt><dd>${a.transcript ? `${esc(a.transcript)}<br><small>dil: ${esc(a.lang)} (güven ${a.lang_prob}) ${a.lang_prob < .8 ? "— düşük güven, altyazı/alıntı için kullanılmaz" : ""}</small>` : "-"}</dd>
      ${a.error ? `<dt>Hata</dt><dd style="color:var(--bad)">${esc(a.error)}</dd>` : ""}
    </dl>
    <div class="row" style="margin-top:14px"><button class="btn small" id="reAn">Bu medyayı yeniden analiz et</button></div>`);
  $("#reAn").onclick = () => { closeDrawer(); runJob(p.name, {step: "analyze", ids: [a.id], label: "Analiz: " + a.id}); };
}

// ---------------- Planlar (Shorts)
async function tabPlanlar(p) {
  const plans = await api(`/api/projects/${p.name}/plans`);
  const fmts = [...new Set(plans.map(x => x.format))];
  const f = state.planFilter;
  const shown = plans.filter(x => f === "all" || (f === "todo" ? !x.rendered : x.format === f));
  const sel = state.planSel;
  $("#tab").innerHTML = `<div class="toolbar">
      <div class="chips"><button class="chip ${f === "all" ? "on" : ""}" data-f="all">Hepsi (${plans.length})</button>
      <button class="chip ${f === "todo" ? "on" : ""}" data-f="todo">Render bekleyen</button>
      ${fmts.map(k => `<button class="chip ${k === f ? "on" : ""}" data-f="${k}">${FORMAT_TR[k] || k} (${plans.filter(x => x.format === k).length})</button>`).join("")}</div></div>
    <div class="toolbar"><button class="btn small" id="selAll">Görünenleri seç</button><button class="btn small" id="selNone">Seçimi temizle</button>
      <button class="btn primary small" id="renderSel" ${sel.size ? "" : "disabled"}>Seçilenleri render et (${sel.size})</button></div>
    ${shown.length ? `<div class="grid cards">${shown.map(x => `<div class="card" data-id="${x.id}">
      <input type="checkbox" class="sel" data-sel="${x.id}" ${sel.has(x.id) ? "checked" : ""} aria-label="seç">
      <div class="th" style="${x.first_asset ? `background-image:url('/api/projects/${p.name}/assets/${encodeURIComponent(x.first_asset)}/thumb')` : ""}">
        <div class="ov"><span class="badge">${FORMAT_TR[x.format] || x.format}</span><span class="badge">${fmtDur(x.duration)}</span>
        ${x.rendered ? `<span class="badge">${x.stale ? "✎ değişti" : "✓ render"}</span>` : ""}</div></div>
      <div class="b"><span class="t">${esc(x.hook_text || x.title || "")}</span><small>${esc(x.loc || "")} · ${x.segments} klip</small></div></div>`).join("")}</div>`
    : `<div class="empty">Plan yok. Genel sekmesinden "Planla".</div>`}`;
  $$("[data-f]").forEach(b => b.onclick = () => { state.planFilter = b.dataset.f; tabPlanlar(p); });
  $$("[data-sel]").forEach(c => { c.onclick = e => e.stopPropagation(); c.onchange = () => { c.checked ? sel.add(c.dataset.sel) : sel.delete(c.dataset.sel); tabPlanlar(p); }; });
  $("#selAll").onclick = () => { shown.forEach(x => sel.add(x.id)); tabPlanlar(p); };
  $("#selNone").onclick = () => { sel.clear(); tabPlanlar(p); };
  $("#renderSel").onclick = () => { runJob(p.name, {step: "render_force", plans: [...sel], label: `Render (${sel.size} video)`}); sel.clear(); };
  $$(".card[data-id]").forEach(c => c.onclick = () => planDrawer(p, c.dataset.id));
}
async function planDrawer(p, id) {
  const d = await api(`/api/projects/${p.name}/plans/${id}`);
  const c = d.captions || {};
  const rendered = (await api(`/api/projects/${p.name}/plans`)).find(x => x.id === id);
  openDrawer(`<h2>${esc(FORMAT_TR[d.format] || d.format)} · ${fmtDur(d.duration)}</h2>
    ${rendered?.video ? `<video src="${rendered.video}?t=${Date.now()}" controls playsinline style="max-height:50vh"></video>` : `<small>Henüz render edilmedi.</small>`}
    <div class="form" style="margin-top:14px">
      <label>Hook (ilk 3 sn ekranda)<input id="eHook" value="${esc(d.hook_text)}"></label>
      <label>Kapanış yazısı<input id="eOutro" value="${esc(d.outro_text)}"></label>
      <label>Müzik modu<select id="eMood">${["upbeat","chill","cinematic","funny","emotional","none"].map(m => `<option ${m === d.music_mood ? "selected" : ""}>${m}</option>`).join("")}</select></label>
    </div>
    <h3 style="margin-top:16px">Klipler</h3>
    ${d.segments.map((s, i) => `<div class="seg"><input type="checkbox" data-en="${i}" ${s.enabled !== false ? "checked" : ""} aria-label="kullan">
       <img src="/api/projects/${p.name}/assets/${encodeURIComponent(s.asset_id)}/thumb" alt="">
       <div><input data-tx="${i}" value="${esc(s.text || "")}" placeholder="ekran yazısı (opsiyonel)">
       <div class="meta">${s.type === "photo" ? "fotoğraf" : `${s.in}s → ${s.out}s`} · ${fmtDur(s.dur)}${s.fx ? " · " + esc(Object.keys(s.fx).join(", ")) : ""}${s.subtitles?.length ? " · altyazılı" : ""}</div></div></div>`).join("")}
    <h3 style="margin-top:16px">Caption'lar</h3>
    <div class="grid">
      <label>Instagram<textarea id="eIg">${esc(c.instagram_caption)}</textarea></label>
      <label>TikTok<textarea id="eTt">${esc(c.tiktok_caption)}</textarea></label>
      <label>YouTube Shorts başlığı<input id="eYt" value="${esc(c.youtube_title)}"></label>
      <label>Hashtag'ler<input id="eTags" value="${esc((c.hashtags || []).join(" "))}"></label>
    </div>
    <div class="row" style="margin-top:16px;justify-content:space-between">
      <button class="btn danger small" id="pDel">Planı sil</button>
      <div class="row"><button class="btn" id="pSave">Kaydet</button><button class="btn primary" id="pRender">Kaydet ve render et</button></div></div>`);
  const collect = () => ({hook_text: $("#eHook").value, outro_text: $("#eOutro").value, music_mood: $("#eMood").value,
    captions: {...c, instagram_caption: $("#eIg").value, tiktok_caption: $("#eTt").value, youtube_title: $("#eYt").value,
      hashtags: $("#eTags").value.split(/\s+/).filter(Boolean).map(h => h.startsWith("#") ? h : "#" + h)},
    segments: d.segments.map((s, i) => ({text: $(`[data-tx="${i}"]`).value, enabled: $(`[data-en="${i}"]`).checked}))});
  $("#pSave").onclick = async () => { await api(`/api/projects/${p.name}/plans/${id}`, {method: "PUT", body: collect()}); toast("Kaydedildi"); };
  $("#pRender").onclick = async () => { await api(`/api/projects/${p.name}/plans/${id}`, {method: "PUT", body: collect()}); closeDrawer(); runJob(p.name, {step: "render_force", plans: [id], label: "Render: " + (FORMAT_TR[d.format] || d.format)}); };
  $("#pDel").onclick = async () => { if (!confirm("Plan çöp kutusuna (plans_trash) taşınsın mı?")) return; await api(`/api/projects/${p.name}/plans/${id}`, {method: "DELETE"}); closeDrawer(); tabPlanlar(p); };
}

// ---------------- Kurgu (Long-form)
async function tabKurgu(p) {
  const plans = (await api(`/api/projects/${p.name}/plans`)).filter(x => x.format === "longform");
  if (!plans.length) {
    $("#tab").innerHTML = `<div class="empty"><p><b>Henüz kurgu yok.</b></p><p>Analiz bittikten sonra kronolojik bir YouTube kurgusu oluşturulur: konuşmalardaki boşluklar kesilir, aralara b-roll girer, şehir/gün değişince yeni bölüm başlar.</p>
      <button class="btn primary" id="mk" ${p.stats.vision_done ? "" : "disabled"}>Kurgu oluştur</button></div>`;
    $("#mk").onclick = () => runJob(p.name, {step: "longform", label: "Kurgu oluştur"});
    return;
  }
  const id = state.lfSel && plans.find(x => x.id === state.lfSel) ? state.lfSel : plans[0].id;
  state.lfSel = id;
  const d = await api(`/api/projects/${p.name}/plans/${id}`);
  const yt = d.youtube || {};
  const total = d.duration || 1;
  const segs = d.segments;
  const byCh = {};
  segs.forEach((s, i) => { (byCh[s.chapter ?? -1] ||= []).push([s, i]); });
  const thumbOf = s => s.asset_id ? `/api/projects/${p.name}/assets/${encodeURIComponent(s.asset_id)}/thumb` : (s.bg_asset ? `/api/projects/${p.name}/assets/${encodeURIComponent(s.bg_asset)}/thumb` : "");
  const segRow = ([s, i]) => `<div class="seg ${s.enabled === false ? "off" : ""}"><input type="checkbox" data-en="${i}" ${s.enabled !== false ? "checked" : ""} aria-label="kullan">
      <img src="${thumbOf(s)}" alt="">
      <div><span class="k ${s.kind}">${SEG_TR[s.kind] || s.kind}</span>${s.type === "card" ? esc(s.text) : `<span class="meta">${s.type === "photo" ? "fotoğraf" : `${s.in}s → ${s.out}s`} · ${fmtDur(s.dur)}</span>`}
      <div class="meta">${esc((s.note || "").slice(0, 140))}</div></div></div>`;
  $("#tab").innerHTML = `
   <div class="toolbar"><select id="lfPick" style="width:auto">${plans.map(x => `<option value="${x.id}" ${x.id === id ? "selected" : ""}>${esc(x.title || x.id)} · ${fmtDur(x.duration)}${x.rendered ? " ✓" : ""}</option>`).join("")}</select>
     <button class="btn small" id="lfNew">+ Yeni versiyon</button><span class="mut">Toplam ${fmtDur(total)} · ${segs.filter(s => s.enabled !== false).length} klip · ${(d.chapters || []).length} bölüm</span></div>
   <div class="timeline" title="mavi: konuşma · yeşil: b-roll · mor: açılış · turuncu: başlık">${segs.filter(s => s.enabled !== false).map(s => `<i class="${s.kind}" style="width:${(s.dur / total * 100).toFixed(3)}%" title="${esc(SEG_TR[s.kind])} ${fmtDur(s.dur)}"></i>`).join("")}</div>
   <div class="split">
    <div class="panel">
      <h3>Zaman çizelgesi</h3><small>İşareti kaldırdığın klip kurgudan çıkar. Bölüm adları videoda alt yazı bandı olarak görünür.</small>
      <div class="chapter"><div class="chapter-h"><b>Açılış</b><small>cold open + başlık kartı</small></div>${(byCh[-1] || []).map(segRow).join("")}</div>
      ${(d.chapters || []).map(c => `<div class="chapter"><div class="chapter-h"><input data-ch="${c.index}" value="${esc(c.title)}"><small>${c.start != null ? fmtDur(c.start) : "-"}</small></div>
        ${(byCh[c.index] || []).map(segRow).join("")}</div>`).join("")}
    </div>
    <div class="panel" style="align-self:start">
      ${plans.find(x => x.id === id)?.video ? `<video src="${plans.find(x => x.id === id).video}?t=${Date.now()}" controls style="width:100%;border-radius:10px;background:#000;margin-bottom:12px"></video>` : ""}
      <h3>YouTube bilgileri</h3>
      <div class="grid">
        <label>Başlık<input id="lTitle" list="titleOpts" value="${esc(d.title)}"><datalist id="titleOpts">${(d.title_options || []).map(t => `<option value="${esc(t)}">`).join("")}</datalist></label>
        <label>Açıklama<textarea id="lDesc">${esc(yt.description)}</textarea></label>
        <label>Bölümler (açıklamaya otomatik eklenir)<pre class="cap">${esc(yt.chapters_block || "")}</pre></label>
        <label>Etiketler<input id="lTags" value="${esc((yt.tags || []).join(", "))}"></label>
        <label>Thumbnail yazısı<input id="lThumb" value="${esc(yt.thumbnail_text)}"></label>
      </div>
      <div class="row" style="margin-top:14px">
        <button class="btn" id="lSave">Kaydet</button>
        <button class="btn primary" id="lRender">Kaydet ve render et (16:9)</button></div>
      <div class="row" style="margin-top:8px">
        <a class="btn small" href="/api/projects/${p.name}/plans/${id}/export?kind=xml">DaVinci / Premiere XML</a>
        <a class="btn small" href="/api/projects/${p.name}/plans/${id}/export?kind=srt">Altyazı (.srt)</a></div>
      <small style="display:block;margin-top:8px">XML'i DaVinci Resolve'da File → Import → Timeline ile aç: kesimler hazır gelir, ince ayarı orada yaparsın.</small>
    </div></div>`;
  $("#lfPick").onchange = e => { state.lfSel = e.target.value; tabKurgu(p); };
  $("#lfNew").onclick = () => runJob(p.name, {step: "longform", label: "Yeni kurgu versiyonu"});
  const collect = () => ({title: $("#lTitle").value,
    youtube: {...yt, description: $("#lDesc").value, tags: $("#lTags").value.split(",").map(x => x.trim()).filter(Boolean), thumbnail_text: $("#lThumb").value},
    chapters: (d.chapters || []).map(c => ({...c, title: $(`[data-ch="${c.index}"]`).value})),
    segments: segs.map((s, i) => ({enabled: $(`[data-en="${i}"]`).checked}))});
  const save = async () => { await api(`/api/projects/${p.name}/plans/${id}`, {method: "PUT", body: collect()}); };
  $$("[data-en]").forEach(cb => cb.onchange = async () => { await save(); tabKurgu(p); });
  $("#lSave").onclick = async () => { await save(); toast("Kaydedildi"); tabKurgu(p); };
  $("#lRender").onclick = async () => { await save(); runJob(p.name, {step: "render_force", plans: [id], label: "Long-form render"}); };
}

// ---------------- Çıktılar
async function tabCiktilar(p) {
  const outs = await api(`/api/projects/${p.name}/outputs`);
  $("#tab").innerHTML = outs.length ? `<div class="grid out">${outs.map((o, i) => `<div class="card">
      <div class="th ${o.format === "longform" ? "wide" : ""}"><video src="${o.video}" ${o.poster ? `poster="${o.poster}"` : ""} controls preload="none" playsinline></video></div>
      <div class="b"><div class="row" style="justify-content:space-between"><b>${FORMAT_TR[o.format] || o.format}</b><small>${o.size_mb} MB</small></div>
        <details><summary>Caption / açıklama</summary><pre class="cap" id="cap${i}">${esc(o.captions)}</pre>
        <button class="btn small" data-copy="${i}">Kopyala</button></details>
        <div class="row"><a class="btn small" href="${o.video}" download>MP4 indir</a>${o.extras.map(e => `<a class="btn small" href="${e}" download>${e.endsWith(".srt") ? "SRT" : "XML"}</a>`).join("")}</div></div></div>`).join("")}</div>`
    : `<div class="empty">Henüz çıktı yok.</div>`;
  $$("[data-copy]").forEach(b => b.onclick = () => { navigator.clipboard.writeText($("#cap" + b.dataset.copy).textContent); toast("Kopyalandı"); });
}

// ---------------- Ayarlar
function tabAyarlar(p) {
  const s = p.settings, models = state.sys?.ollama_models || [];
  const opt = (list, cur) => [...new Set([cur, ...list])].filter(Boolean).map(m => `<option ${m === cur ? "selected" : ""}>${esc(m)}</option>`).join("");
  const src = s.source || {};
  $("#tab").innerHTML = `<form id="setForm" class="form">
   <fieldset><legend>Kaynak</legend>
     <label>Tür<select name="source.type"><option value="folder" ${src.type === "folder" ? "selected" : ""}>Klasör</option><option value="photos" ${src.type === "photos" ? "selected" : ""}>Photos (shared album)</option></select></label>
     <label>Klasör yolu<input name="source.folder" value="${esc(src.folder || "")}"></label>
     <label>Shared album'ler (virgülle)<input name="source.photos.shared_albums" value="${esc((src.photos?.shared_albums || []).join(", "))}"></label>
     <label class="check"><input type="checkbox" name="source.copy_media" ${src.copy_media ? "checked" : ""}> Dosyaları kopyala</label>
     <small>Photos için terminale/uygulamaya Full Disk Access gerekir.</small></fieldset>
   <fieldset><legend>Analiz (lokal)</legend>
     <label>Görüntü modeli<select name="analysis.ollama.vision_model">${opt(models, s.analysis.ollama.vision_model)}</select></label>
     <label>Metin modeli<select name="analysis.ollama.text_model">${opt(models, s.analysis.ollama.text_model)}</select></label>
     <label>Whisper modeli<select name="analysis.whisper_model">${opt(["large-v3-turbo","medium","small"], s.analysis.whisper_model)}</select></label>
     <label>Konuşma dili<select name="analysis.language">${[["","Otomatik"],["tr","Türkçe"],["en","İngilizce"]].map(([v, l]) => `<option value="${v}" ${(s.analysis.language || "") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
     <label>Videodan kare sayısı<input type="number" name="analysis.frames_per_video" value="${s.analysis.frames_per_video}" min="2" max="12"></label></fieldset>
   <fieldset><legend>Senaryo</legend>
     <label>Ekran yazısı dili<select name="director.creator_language">${["tr","en"].map(l => `<option ${l === s.director.creator_language ? "selected" : ""}>${l}</option>`).join("")}</select></label>
     <label>Caption dilleri (virgülle)<input name="director.caption_languages" value="${esc((s.director.caption_languages || []).join(", "))}"></label>
     ${p.mode === "shorts" ? `<label>Konsept başına varyant<input type="number" name="director.variants_per_concept" value="${s.director.variants_per_concept}" min="1" max="5"></label>
     <label>Min / max süre (sn)<div class="row"><input type="number" name="director.min_duration" value="${s.director.min_duration}" style="width:45%"><input type="number" name="director.max_duration" value="${s.director.max_duration}" style="width:45%"></div></label>`
     : `<label>Hedef süre (dk)<input type="number" name="longform.target_minutes" value="${s.longform?.target_minutes ?? 12}"></label>
        <label>En fazla (dk)<input type="number" name="longform.max_minutes" value="${s.longform?.max_minutes ?? 20}"></label>
        <label>Bölüm arası boşluk (dk)<input type="number" name="longform.chapter_gap_minutes" value="${s.longform?.chapter_gap_minutes ?? 90}"></label>`}</fieldset>
   <fieldset><legend>Render</legend>
     <label>Müzik klasörü<input name="render.music_dir" value="${esc(s.render.music_dir || "")}"><small>music/&lt;upbeat|chill|cinematic|funny|emotional&gt;/*.mp3 — telifsiz parçalar</small></label>
     <label>Müzik seviyesi (0-1)<input type="number" step="0.05" name="render.music_volume" value="${s.render.music_volume}"></label>
     <label>Watermark<input name="render.watermark" value="${esc(s.render.watermark || "")}" placeholder="@kullaniciadin"></label>
     <label class="check"><input type="checkbox" name="render.burn_subtitles" ${s.render.burn_subtitles ? "checked" : ""}> Altyazıyı videoya göm</label></fieldset>
   <div class="actions" style="grid-column:1/-1"><button class="btn primary">Kaydet</button></div></form>`;
  $("#setForm").onsubmit = async e => {
    e.preventDefault();
    const body = {};
    for (const el of e.target.elements) {
      if (!el.name) continue;
      let v = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
      if (/shared_albums|caption_languages/.test(el.name)) v = v.split(",").map(x => x.trim()).filter(Boolean);
      if (el.name === "analysis.language" && v === "") v = null;
      const keys = el.name.split("."); let o = body;
      keys.slice(0, -1).forEach(k => o = o[k] ||= {}); o[keys.at(-1)] = v;
    }
    await api(`/api/projects/${p.name}/settings`, {method: "PUT", body}); toast("Ayarlar kaydedildi");
  };
}

// ------------------------------------------------------------------ drawer & new project
function openDrawer(html) { $("#drawerBody").innerHTML = html; $("#drawer").hidden = $("#drawerBg").hidden = false; }
function closeDrawer() { $("#drawer").hidden = $("#drawerBg").hidden = true; $$("#drawerBody video").forEach(v => v.pause()); }
$("#drawerClose").onclick = closeDrawer; $("#drawerBg").onclick = closeDrawer;
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

function openNewProject() { $("#npForm").reset(); syncNp(); $("#newProject").showModal(); }
$("#newProjectBtn").onclick = openNewProject;
function syncNp() {
  const f = $("#npForm").elements;
  const photos = f.source_type.value === "photos", lf = f.mode.value === "longform";
  const fm = $("#npForm"); $(".src-folder", fm).hidden = photos; $(".src-photos", fm).hidden = !photos; $(".lf-only", fm).hidden = !lf;
}
$("#npForm").addEventListener("change", syncNp);
$("#newProject").addEventListener("close", async () => {
  if ($("#newProject").returnValue !== "ok") return;
  const f = $("#npForm").elements;
  const body = {title: f.title.value, mode: f.mode.value, source_type: f.source_type.value, folder: f.folder.value.trim(),
    shared_albums: f.shared_albums.value.split(",").map(x => x.trim()).filter(Boolean), copy_media: f.copy_media.checked,
    target_minutes: f.target_minutes.value, max_minutes: f.max_minutes.value};
  try { const r = await api("/api/projects", {method: "POST", body}); toast("Proje oluşturuldu"); location.hash = `#/p/${r.name}/genel`; }
  catch (e) { toast("⚠️ " + e.message); }
});

route();
