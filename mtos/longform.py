"""Long-form YouTube mode (e.g. DJI Osmo Pocket footage).

Builds ONE chronological 16:9 vlog edit from the catalog:
  * talking parts: whisper segments merged into blocks, dead air removed (jump cuts)
  * b-roll: best scenic / action / food moments placed between talking blocks
  * chapters: new chapter when the city / day changes or after a long time gap
  * cold open: the 4 strongest moments + title card
  * metadata: title options, description with YouTube chapter timestamps, tags, thumbnail text
Exports: the plan (rendered by render.py), an .srt for YouTube, and an FCP7 XML
timeline that opens in DaVinci Resolve / Premiere for manual fine-tuning."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from tqdm import tqdm

from . import media
from .catalog import Catalog
from .config import Config
from .director import Director, _hid

META_SCHEMA = {
    "type": "object",
    "properties": {
        "title_options": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "thumbnail_text": {"type": "string"},
        "chapter_titles": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title_options", "description", "tags", "thumbnail_text", "chapter_titles"],
}


def _ts(sec: float) -> str:
    sec = int(round(sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _dt(a) -> datetime | None:
    try:
        return datetime.fromisoformat(a.get("taken_at")) if a.get("taken_at") else None
    except ValueError:
        return None


class LongformDirector:
    def __init__(self, cfg: Config, cat: Catalog, use_llm: bool = True):
        self.cfg, self.cat = cfg, cat
        self.lf = {"target_minutes": 12, "max_minutes": 20, "broll_per_gap": 2, "chapter_gap_minutes": 90,
                   **(cfg.get("longform") or {})}
        self.use_llm = use_llm
        self.assets = sorted(cat.assets(), key=lambda a: (a.get("taken_at") or "", a["id"]))
        self.plans_dir = cfg.ws("plans")

    # ------------------------------------------------------------ material
    def _talk_blocks(self, a) -> list[dict]:
        if not Director._confident(a):
            return []
        segs = (a.get("transcript") or {}).get("segments") or []
        blocks = []
        for s in segs:
            st, en = max(0, s["start"] - 0.25), min(a["duration"] or s["end"], s["end"] + 0.35)
            if blocks and st - blocks[-1]["out"] < 1.0:  # small pause: keep talking flow
                blocks[-1]["out"] = en
                blocks[-1]["text"] += " " + s["text"]
            else:
                blocks.append({"in": st, "out": en, "text": s["text"]})
        return [b for b in blocks if b["out"] - b["in"] >= 1.2]

    def _items(self) -> list[dict]:
        items = []
        for a in self.assets:
            v = a.get("vision") or {}
            aes = (v.get("aesthetic_score") or 0) / 10
            base = {"asset_id": a["id"], "when": a.get("taken_at") or "", "loc": a.get("city") or a.get("place") or "",
                    "day": (a.get("taken_at") or "")[:10]}
            if a["kind"] == "video":
                talks = self._talk_blocks(a)
                for b in talks:
                    items.append({**base, "kind": "talk", "type": "video", "in": round(b["in"], 2),
                                  "out": round(b["out"], 2), "score": 0.7, "text": b["text"][:200]})
                ms = self.cat.moments("m.asset_id=? AND m.kind NOT IN ('speech')", (a["id"],))
                for m in ms:
                    if any(not (m["end"] < t["in"] or m["start"] > t["out"]) for t in talks):
                        continue
                    st = m["start"]
                    en = min(a["duration"] or m["end"], max(m["end"], st + 3.5), st + 6)
                    if en - st >= 1.5:
                        items.append({**base, "kind": "broll", "type": "video", "in": round(st, 2),
                                      "out": round(en, 2), "score": m["score"], "text": m["text"] or ""})
                if not talks and not ms and a["duration"]:
                    mid = a["duration"] / 2
                    items.append({**base, "kind": "broll", "type": "video", "in": round(max(0, mid - 2.5), 2),
                                  "out": round(min(a["duration"], mid + 2.5), 2), "score": 0.3 + 0.4 * aes,
                                  "text": v.get("summary") or ""})
            elif a["kind"] == "live" and a.get("video_path"):
                items.append({**base, "kind": "broll", "type": "video", "in": 0, "out": a["duration"] or 3,
                              "score": 0.35 + 0.4 * aes, "text": v.get("summary") or ""})
            elif a["kind"] == "photo" and aes >= 0.6:
                items.append({**base, "kind": "broll", "type": "photo", "in": 0, "out": 0, "dur": 3.0,
                              "score": 0.3 + 0.4 * aes, "text": v.get("summary") or ""})
        # de-duplicate overlapping b-roll windows of the same asset
        out = []
        for it in sorted(items, key=lambda i: -i["score"]):
            if it["kind"] == "broll" and any(o["asset_id"] == it["asset_id"] and o["kind"] == "broll" and
                                             not (it["out"] <= o["in"] or it["in"] >= o["out"]) for o in out):
                continue
            out.append(it)
        return sorted(out, key=lambda i: (i["when"], i["in"]))

    @staticmethod
    def _dur(it) -> float:
        return it.get("dur") or (it["out"] - it["in"])

    def _fit_budget(self, items: list[dict]) -> list[dict]:
        target = self.lf["target_minutes"] * 60
        maxd = self.lf["max_minutes"] * 60
        total = sum(self._dur(i) for i in items)
        if total <= maxd:
            return items
        keep = list(items)
        # 1) drop weakest b-roll, 2) then weakest talk blocks, until near target
        for kind in ("broll", "talk"):
            for it in sorted([i for i in keep if i["kind"] == kind], key=lambda i: i["score"]):
                if total <= target:
                    break
                keep.remove(it)
                total -= self._dur(it)
        return keep

    def _chapters(self, items: list[dict]) -> list[list[dict]]:
        chapters, cur, last = [], [], None
        gap = self.lf["chapter_gap_minutes"] * 60
        for it in items:
            t = _dt({"taken_at": it["when"]})
            new = bool(cur) and (it["loc"] != cur[-1]["loc"] or it["day"] != cur[-1]["day"] or
                                 (t and last and (t - last).total_seconds() > gap))
            if new:
                chapters.append(cur)
                cur = []
            cur.append(it)
            last = t or last
        if cur:
            chapters.append(cur)
        return chapters

    # ------------------------------------------------------------ plan
    def run(self, variant: int = 0) -> Path:
        assets = {a["id"]: a for a in self.assets}
        items = self._fit_budget(self._items())
        if not items:
            raise SystemExit("Kullanılabilir materyal yok — önce analyze çalıştırın.")
        chapters = self._chapters(items)
        meta = self._meta(chapters, assets)
        lang_tr = self.cfg["director"]["creator_language"] == "tr"

        def seg(it, **kw):
            a = assets[it["asset_id"]]
            v = a.get("vision") or {}
            cx = v.get("subject_x") if isinstance(v.get("subject_x"), (int, float)) else 0.5
            s = {"asset_id": a["id"], "type": it["type"], "kind": it["kind"],
                 "src": a["video_path"] if it["type"] == "video" else a["photo_path"],
                 "in": it["in"], "out": it["out"], "dur": round(self._dur(it), 2), "crop_x": cx,
                 "layout": "auto", "keep_audio": it["kind"] == "talk", "subtitles": [], "text": "",
                 "note": it.get("text", ""), "enabled": True, "kenburns": "in"}
            s.update(kw)
            return s

        segments = []
        # cold open: strongest non-talk moments, 2.5s each
        opener = sorted([i for i in items if i["kind"] == "broll"], key=lambda i: -i["score"])[:4]
        for it in opener:
            o = dict(it, out=min(it["out"], it["in"] + 2.5), dur=2.5 if it["type"] == "photo" else None)
            if o["type"] == "video":
                o.pop("dur")
            segments.append(seg(o, kind="open", chapter=-1, keep_audio=False))
        title = (meta.get("title_options") or ["Seyahat günlüğü" if lang_tr else "Travel diary"])[0]
        bg = opener[0] if opener else items[0]
        segments.append({"type": "card", "kind": "card", "text": title, "dur": 2.5, "chapter": -1,
                         "bg_asset": bg["asset_id"], "bg_src": assets[bg["asset_id"]]["video_path"] or
                         assets[bg["asset_id"]]["photo_path"], "bg_t": bg["in"], "enabled": True})
        titles = meta.get("chapter_titles") or []
        days = sorted({ch[0]["day"] for ch in chapters if ch[0]["day"]})
        seen: dict[str, int] = {}
        chapter_meta = []
        for ci, ch in enumerate(chapters):
            ctitle = titles[ci] if ci < len(titles) and titles[ci] and titles[ci] != ch[0]["loc"] else None
            if not ctitle:  # template name that stays unique: "Hong Kong · 2. gün", "Hong Kong · 2. gün (devam)"
                loc = ch[0]["loc"] or (f"Bölüm {ci + 1}" if lang_tr else f"Part {ci + 1}")
                day_n = days.index(ch[0]["day"]) + 1 if ch[0]["day"] in days else None
                base = f"{loc} · {day_n}. gün" if (day_n and len(days) > 1) else loc
                seen[base] = seen.get(base, 0) + 1
                ctitle = base if seen[base] == 1 else f"{base} ({'devam' if lang_tr else 'cont.'} {seen[base] - 1})"
            chapter_meta.append({"index": ci, "title": ctitle, "loc": ch[0]["loc"], "day": ch[0]["day"]})
            for k, it in enumerate(ch):
                s = seg(it, chapter=ci)
                if k == 0:
                    s.update(text=ctitle, text_style="lower")
                segments.append(s)
        plan = {"id": _hid("longform", variant, *[f"{s.get('asset_id')}:{s.get('in')}" for s in segments]),
                "format": "longform", "mode": "longform", "variant": variant,
                "lang": self.cfg["director"]["creator_language"],
                "title": title, "title_options": meta.get("title_options"), "hook_text": None, "outro_text": None,
                "music_mood": "chill", "chapters": chapter_meta, "segments": segments,
                "youtube": {"description": meta.get("description", ""), "tags": meta.get("tags", []),
                            "thumbnail_text": meta.get("thumbnail_text", "")},
                "created": datetime.now().isoformat(timespec="seconds")}
        refresh(plan)
        path = self.plans_dir / f"longform_{plan['id']}.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _meta(self, chapters, assets) -> dict:
        fallback = {"title_options": [], "description": "", "tags": [], "thumbnail_text": "",
                    "chapter_titles": [ch[0]["loc"] or ch[0]["day"] for ch in chapters]}
        if not self.use_llm:
            return fallback
        lang = self.cfg["director"]["creator_language"]
        lang_name = {"tr": "Turkish", "en": "English"}.get(lang, lang)
        lines = []
        for ci, ch in enumerate(chapters):
            talk = " ".join(i["text"] for i in ch if i["kind"] == "talk")[:500]
            vis = "; ".join(dict.fromkeys(i["text"][:80] for i in ch if i["kind"] == "broll"))[:400]
            lines.append(f"Chapter {ci + 1} | {ch[0]['loc']} | {ch[0]['day']} | "
                         f"{len(ch)} clips | what we said: {talk or '-'} | what we see: {vis or '-'}")
        prompt = ("You are editing a long-form YouTube travel vlog. Chapters in order:\n" + "\n".join(lines) +
                  f"\n\nReturn JSON: title_options (5 click-worthy but honest YouTube titles, <70 chars); "
                  f"description (3-5 sentences, no timestamps - they are added automatically); tags (15); "
                  f"thumbnail_text (max 4 words); chapter_titles (exactly {len(chapters)}, short, one per chapter). "
                  f"Everything in {lang_name}.")
        try:
            from .llm import Backend
            res = Backend(self.cfg, self.cat).text_json(prompt, META_SCHEMA, purpose="longform", max_tokens=3000)
            return {**fallback, **{k: v for k, v in res.items() if v}}
        except Exception as e:
            print(f"⚠️  LLM meta hatası: {e} — şablon kullanılıyor")
            return fallback


# ---------------------------------------------------------------- shared helpers
def refresh(plan: dict) -> dict:
    """Recompute durations, chapter start times and the YouTube description block
    after the plan was edited (segments toggled, chapter titles renamed)."""
    t = 0.0
    starts = {}
    for s in plan["segments"]:
        if not s.get("enabled", True):
            continue
        if s.get("type") == "video":
            s["dur"] = round(s["out"] - s["in"], 2)
        ch = s.get("chapter", -1)
        if ch >= 0 and ch not in starts:
            starts[ch] = t
        t += s["dur"]
    plan["duration"] = round(t, 2)
    lines = ["00:00 " + ("Giriş" if plan.get("lang", "tr") == "tr" else "Intro")]
    for c in plan.get("chapters") or []:
        if c["index"] in starts:
            c["start"] = round(starts[c["index"]], 2)
            if starts[c["index"]] >= 10:  # YouTube needs chapters >= 10s apart, first at 00:00
                lines.append(f"{_ts(starts[c['index']])} {c['title']}")
        else:
            c["start"] = None
    # chapter titles shown on screen follow edits
    titles = {c["index"]: c["title"] for c in plan.get("chapters") or []}
    seen = set()
    for s in plan["segments"]:
        ch = s.get("chapter", -1)
        if ch >= 0 and s.get("enabled", True) and ch not in seen:
            s["text"], s["text_style"] = titles.get(ch, s.get("text", "")), "lower"
            seen.add(ch)
        elif ch >= 0 and s.get("text_style") == "lower":
            s["text"] = ""
    yt = plan.setdefault("youtube", {})
    yt["chapters_block"] = "\n".join(lines)
    return plan


def make_srt(plan: dict, cat: Catalog) -> str:
    """Subtitles for the final timeline from word timestamps of the talking segments."""
    out, n, t0 = [], 1, 0.0
    for s in plan["segments"]:
        if not s.get("enabled", True):
            continue
        if s.get("type") == "video" and s.get("kind") == "talk":
            a = cat.asset(s["asset_id"])
            for c in Director._subs(a, s["in"], s["out"], max_words=7):
                a_, b_ = t0 + c["s"], t0 + c["e"]
                out.append(f"{n}\n{_srt(a_)} --> {_srt(b_)}\n{c['text']}\n")
                n += 1
        t0 += s["dur"]
    return "\n".join(out)


def _srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def export_xml(plan: dict, out: Path, fps: int = 30) -> Path:
    """FCP7 XML (xmeml v5): opens in DaVinci Resolve and Premiere Pro.
    Video + audio tracks with the real source files; title cards are left as gaps."""
    from xml.sax.saxutils import escape as e
    files, clips_v, clips_a = {}, [], []
    t = 0
    for i, s in enumerate(plan["segments"]):
        if not s.get("enabled", True):
            continue
        dur_f = int(round(s["dur"] * fps))
        if s.get("type") in ("video", "photo") and s.get("src"):
            src = s["src"]
            if src not in files:
                try:
                    info = media.video_info(Path(src)) if s["type"] == "video" else {"duration": 10, "width": 0,
                                                                                        "height": 0}
                except Exception:
                    info = {"duration": 0, "width": 0, "height": 0}
                files[src] = {"id": f"file-{len(files) + 1}", "dur": int(round((info["duration"] or 10) * fps)),
                              "w": info.get("width"), "h": info.get("height"), "first": True}
            f = files[src]
            fin = int(round(s["in"] * fps)) if s["type"] == "video" else 0
            ref = f'<file id="{f["id"]}"/>'
            if f["first"]:
                fdef = (f'<file id="{f["id"]}"><name>{e(Path(src).name)}</name>'
                        f'<pathurl>file://localhost{quote(str(Path(src).resolve()))}</pathurl>'
                        f'<rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate><duration>{f["dur"]}</duration>'
                        f'<media><video><samplecharacteristics><width>{f["w"]}</width><height>{f["h"]}</height>'
                        f'</samplecharacteristics></video><audio><channelcount>2</channelcount></audio></media></file>')
                f["first"] = False
            else:
                fdef = ref
            common = (f'<name>{e(Path(src).name)}</name><duration>{f["dur"]}</duration>'
                      f'<rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>'
                      f'<start>{t}</start><end>{t + dur_f}</end><in>{fin}</in><out>{fin + dur_f}</out>{fdef}')
            clips_v.append(f'<clipitem id="v{i}">{common}</clipitem>')
            if s["type"] == "video":
                clips_a.append(f'<clipitem id="a{i}">{common.replace(fdef, ref)}'
                               f'<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>'
                               f'</clipitem>')
        t += dur_f
    markers = "".join(
        f'<marker><name>{e(c["title"])}</name><in>{int(round(c["start"] * fps))}</in><out>-1</out></marker>'
        for c in plan.get("chapters") or [] if c.get("start") is not None)
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5"><sequence id="seq-1">'
           f'<name>{e(plan.get("title") or "MegaTravelOS")}</name><duration>{t}</duration>'
           f'<rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>{markers}'
           f'<media><video><format><samplecharacteristics><width>1920</width><height>1080</height>'
           f'</samplecharacteristics></format><track>{"".join(clips_v)}</track></video>'
           f'<audio><track>{"".join(clips_a)}</track></audio></media></sequence></xmeml>')
    out.write_text(xml, encoding="utf-8")
    return out


def run(cfg: Config, cat: Catalog, use_llm: bool = True) -> Path:
    existing = len(list(cfg.ws("plans").glob("longform_*.json")))
    p = LongformDirector(cfg, cat, use_llm).run(variant=existing)
    tqdm.write(f"🎬 Long-form plan: {p}")
    return p
