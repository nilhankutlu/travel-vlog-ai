"""The director: turns the moment database into MANY video plans.

1. Concept generators (deterministic) find every angle in the material:
   per city, per day, per category, every funny moment, every good quote,
   photo dumps, live-photo reels, split-screen comparisons, top-N lists...
2. An LLM (local or Claude) writes the script for each concept: picks/orders
   clips, hook text, on-screen text, captions + hashtags per platform, music mood.
   Without an LLM, templates fill these in.
3. Each concept is written to plans/<id>.json, ready for the renderer."""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from .catalog import Catalog
from .config import Config

MUSIC_MOODS = ["upbeat", "chill", "cinematic", "funny", "emotional", "none"]

CAT_TITLES = {
    "food": ("{city}'de yediğim her şey", "Everything I ate in {city}"),
    "transport": ("{city}'de ulaşım deneyimi", "Getting around {city}"),
    "sunset": ("{city} gün batımları", "{city} sunsets hit different"),
    "night": ("{city} geceleri", "{city} at night"),
    "street": ("{city} sokakları", "Walking the streets of {city}"),
    "landmark": ("{city}'de mutlaka gör", "Must-see spots in {city}"),
    "nature": ("{city} doğası", "Nature in {city}"),
    "market": ("{city} pazarları", "{city} markets"),
    "nightlife": ("{city} gece hayatı", "{city} nightlife"),
    "museum": ("{city} müzeleri", "Museums of {city}"),
    "shopping": ("{city}'de alışveriş", "Shopping in {city}"),
    "people": ("{city}'de biz", "Us in {city}"),
    "beach": ("{city} plajları", "{city} beaches"),
    "funny": ("{city}'de komik anlar", "Funny moments in {city}"),
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook_text": {"type": "string"},
        "clip_order": {"type": "array", "items": {"type": "integer"}},
        "clip_texts": {"type": "array", "items": {"type": "string"}},
        "outro_text": {"type": "string"},
        "music_mood": {"type": "string", "enum": MUSIC_MOODS},
        "instagram_caption": {"type": "string"},
        "tiktok_caption": {"type": "string"},
        "youtube_title": {"type": "string"},
        "youtube_description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "hook_text", "clip_order", "clip_texts", "outro_text", "music_mood",
                 "instagram_caption", "tiktok_caption", "youtube_title", "youtube_description", "hashtags"],
}

SYSTEM = """You are a viral short-form travel video creator and editor (Reels / TikTok / Shorts).
You write scroll-stopping hooks, short on-screen text, and native-sounding captions.
Rules: hooks max 8 words; on-screen texts max 6 words or empty ""; captions conversational, 1-3 short
lines plus a question or CTA; 5-12 relevant hashtags without spaces. Never invent facts that contradict
the clip descriptions. Write on-screen text in {lang}. Captions: write in {caption_langs} (if two
languages, first line in the first language, then a line in the second)."""


def _hid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def _day(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).date().isoformat()
    except ValueError:
        return ts[:10]


class Director:
    def __init__(self, cfg: Config, cat: Catalog, use_llm: bool = True):
        self.cfg, self.cat = cfg, cat
        self.d = cfg["director"]
        self.use_llm = use_llm and self.d.get("use_llm", True)
        self.plans_dir = cfg.ws("plans")
        self.assets = {a["id"]: a for a in cat.assets()}
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            from .llm import Backend
            self._llm = Backend(self.cfg, self.cat)
        return self._llm

    # ================================================================ concepts
    def concepts(self) -> list[dict]:
        ms = [m for m in self.cat.moments() if m["asset_id"] in self.assets]
        for m in ms:
            a = self.assets[m["asset_id"]]
            m["loc"] = a.get("city") or (a.get("vision") or {}).get("place_guess") or a.get("place") or "Trip"
            m["day"] = _day(a.get("taken_at"))
        out: list[dict] = []

        def add(fmt, moments, **kw):
            moments = self._dedupe(moments)
            if moments:
                out.append({"format": fmt, "moments": moments, **kw})

        visual = [m for m in ms if m["kind"] not in ("speech",)]
        by_loc = defaultdict(list)
        for m in visual:
            by_loc[m["loc"]].append(m)
        by_country = defaultdict(list)
        for m in visual:
            by_country[self.assets[m["asset_id"]].get("country") or "all"].append(m)

        # --- location reels
        for loc, lst in by_loc.items():
            if len({m["asset_id"] for m in lst}) >= 4:
                add("city_montage", sorted(lst, key=lambda m: -m["score"])[:14], loc=loc)
                add("top5", sorted(lst, key=lambda m: -m["score"])[:5], loc=loc)
                add("pov_arrival", sorted(lst, key=lambda m: m["day"] or "")[:8], loc=loc)
            photos = [m for m in lst if m["asset_kind"] == "photo" or m["kind"] in ("photo", "live")]
            if len(photos) >= 4:
                add("photo_dump", sorted(photos, key=lambda m: -m["score"])[:12], loc=loc)
            # --- category reels inside a location
            by_cat = defaultdict(list)
            for m in lst:
                for t in m.get("tags") or []:
                    by_cat[t].append(m)
            for c, cl in by_cat.items():
                if c in CAT_TITLES and len({m["asset_id"] for m in cl}) >= 3:
                    add("category", sorted(cl, key=lambda m: -m["score"])[:10], loc=loc, category=c)

        # --- whole-trip category reels
        all_cat = defaultdict(list)
        for m in visual:
            for t in m.get("tags") or []:
                all_cat[t].append(m)
        for c, cl in all_cat.items():
            if c in CAT_TITLES and len({m["loc"] for m in cl}) >= 2 and len(cl) >= 4:
                add("category", sorted(cl, key=lambda m: -m["score"])[:12], loc="Trip", category=c)

        # --- day vlogs
        by_day = defaultdict(list)
        for m in visual:
            if m["day"]:
                by_day[m["day"]].append(m)
        for day, lst in by_day.items():
            if len({m["asset_id"] for m in lst}) >= 5:
                lst = sorted(lst, key=lambda m: (self.assets[m["asset_id"]].get("taken_at") or "", m["start"]))
                add("day_vlog", lst[:16], loc=lst[0]["loc"], day=day)

        # --- funny: every single funny moment + compilations
        funny = [m for m in ms if m["kind"] in ("funny", "reaction") or "funny" in (m.get("tags") or [])]
        funny.sort(key=lambda m: -m["score"])
        for m in funny:
            if m["score"] >= 0.55 and m["asset_kind"] != "photo":
                add("funny_single", [m], loc=m["loc"])
        for ctry, lst in {**by_country, "all": visual}.items():
            f = [m for m in funny if m in lst]
            if len({m["asset_id"] for m in f}) >= 3:
                add("funny_compilation", f[:8], loc=ctry if ctry != "all" else "Trip")

        # --- quotes (speech)
        for m in sorted([m for m in ms if m["kind"] == "speech"], key=lambda m: -m["score"]):
            if m["score"] >= 0.45 and len((m["text"] or "").split()) >= 4:
                add("quote", [m], loc=m["loc"])

        # --- live photo reel
        live = [m for m in visual if m["asset_kind"] == "live"]
        if len(live) >= 4:
            add("live_reel", sorted(live, key=lambda m: -m["score"])[:12], loc="Trip")

        # --- hook-first single clips (best visual moments)
        for m in sorted([m for m in visual if m["asset_kind"] != "photo"], key=lambda m: -m["score"])[:20]:
            if m["score"] >= 0.6:
                add("single_hook", [m], loc=m["loc"])

        # --- split-screen comparisons (location A vs B, or day vs night)
        locs = [l for l in by_loc if len(by_loc[l]) >= 3]
        for i in range(len(locs)):
            for j in range(i + 1, len(locs)):
                a = sorted(by_loc[locs[i]], key=lambda m: -m["score"])[:4]
                b = sorted(by_loc[locs[j]], key=lambda m: -m["score"])[:4]
                add("split_compare", a + b, loc=f"{locs[i]} vs {locs[j]}", split=len(a))
        night = [m for m in visual if "night" in (m.get("tags") or [])]
        day_ = [m for m in visual if "night" not in (m.get("tags") or []) and m["score"] >= 0.5]
        if len(night) >= 3 and len(day_) >= 3:
            add("split_compare", day_[:4] + night[:4], loc="Day vs Night", split=4)

        # --- whole trip recap
        if len({m["asset_id"] for m in visual}) >= 6:
            add("trip_recap", sorted(visual, key=lambda m: -m["score"])[:20], loc="Trip")

        # --- per-asset products: every single video / Live Photo / good photo becomes several videos
        best: dict[str, dict] = {}
        for m in ms:
            if m["kind"] != "speech" and (m["asset_id"] not in best or m["score"] > best[m["asset_id"]]["score"]):
                best[m["asset_id"]] = m
        for aid, m in best.items():
            a = self.assets[aid]
            v = a.get("vision") or {}
            aes = (v.get("aesthetic_score") or 0) / 10
            humor = (v.get("humor_score") or 0) / 10
            talky = bool((a.get("transcript") or {}).get("text"))
            if a["kind"] == "video":
                add("clip_full", [m], loc=m["loc"], single=True)
                if aes >= 0.6 or m["kind"] in ("scenic", "action"):
                    add("slowmo", [m], loc=m["loc"], single=True)
                    add("loop", [m], loc=m["loc"], single=True)
                if humor >= 0.5 or m["kind"] in ("funny", "reaction"):
                    add("wait_for_it", [m], loc=m["loc"], single=True)
            elif a["kind"] == "live":
                add("live_boomerang", [m], loc=m["loc"], single=True)
                add("live_slowmo", [m], loc=m["loc"], single=True)
                if a.get("photo_path"):
                    add("live_still_reveal", [m], loc=m["loc"], single=True)
                if talky or humor >= 0.5:
                    add("live_with_sound", [m], loc=m["loc"], single=True)
            elif a["kind"] == "photo" and aes >= 0.6:
                add("photo_single", [m], loc=m["loc"], single=True)

        # variants (single-asset products get variants too: different hook / overlay text)
        res = []
        for c in out:
            n_var = self.d.get("variants_per_concept", 1) if (len(c["moments"]) > 2 or c.get("single")) else 1
            for v in range(n_var):
                cc = dict(c, variant=v)
                if v and len(c["moments"]) > 1:
                    rnd = random.Random(v)
                    ms_ = c["moments"][:]
                    head, tail = ms_[:1], ms_[1:]
                    rnd.shuffle(tail)
                    cc["moments"] = head + tail
                cc["id"] = _hid(c["format"], c.get("loc"), c.get("category"), c.get("day"),
                                *[f"{m['asset_id']}:{m['start']}" for m in c["moments"]], v)
                res.append(cc)
        return res

    @staticmethod
    def _dedupe(moments):
        """One moment per asset+overlap window."""
        out = []
        for m in moments:
            if any(o["asset_id"] == m["asset_id"] and not (m["end"] < o["start"] or m["start"] > o["end"])
                   for o in out):
                continue
            out.append(m)
        return out

    # ================================================================ planning
    def run(self, max_concepts: int | None = None) -> list[Path]:
        concepts = self.concepts()
        print(f"💡 {len(concepts)} konsept bulundu.")
        if max_concepts:
            concepts = concepts[:max_concepts]
        written = []
        for c in tqdm(concepts, desc="✍️  Senaryolar"):
            path = self.plans_dir / f"{c['format']}_{c['id']}.json"
            if path.exists():
                written.append(path)
                continue
            script = None
            if self.use_llm:
                try:
                    script = self.write_script(c)
                except Exception as e:
                    tqdm.write(f"⚠️  LLM senaryo hatası ({c['format']}): {e} — şablon kullanılıyor")
            plan = self.build_plan(c, script or self.template_script(c))
            path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(path)
        return written

    def _clip_lines(self, c) -> str:
        lines = []
        for i, m in enumerate(c["moments"]):
            a = self.assets[m["asset_id"]]
            v = a.get("vision") or {}
            line = (f"[{i}] {m['kind']} | {a['kind']} | {m['loc']} | score {m['score']:.2f} | "
                    f"{(m['text'] or v.get('summary') or '')[:160]}")
            q = (a.get("transcript") or {}).get("text")
            if q and m["kind"] in ("speech", "funny", "reaction"):
                line += f' | says: "{q[:160]}"'
            if v.get("humor_reason"):
                line += f" | funny because: {v['humor_reason'][:100]}"
            lines.append(line)
        return "\n".join(lines)

    FORMAT_BRIEFS = {
        "city_montage": "fast-cut cinematic montage of {loc}, beat-synced, 1-2s per clip",
        "top5": "countdown 'Top 5 in {loc}' - clip_texts should be '5. ...' down to '1. ...'",
        "pov_arrival": "'POV: you just arrived in {loc}' storytelling in chronological order",
        "photo_dump": "'{loc} photo dump' with Ken Burns motion, aesthetic, chill",
        "category": "themed reel about {category} in {loc}",
        "day_vlog": "'a day in {loc}' vlog ({day}), chronological, short labels like time or activity",
        "funny_single": "single funny moment from {loc}: setup text on top, let the clip + audio deliver the punchline",
        "funny_compilation": "funny moments compilation from {loc}",
        "quote": "a memorable thing someone said in {loc}; subtitles carry it, hook teases it",
        "live_reel": "Live Photos come alive: many 2-3s moving moments",
        "single_hook": "one strong visual moment from {loc} with a curiosity hook",
        "split_compare": "split-screen comparison: {loc} (top vs bottom)",
        "trip_recap": "whole trip recap, emotional, best moments",
        "clip_full": "one single clip from {loc} posted on its own: strong hook, let it play",
        "slowmo": "one clip from {loc} in cinematic slow motion; dreamy, aesthetic text",
        "loop": "a short seamless loop (forward-backward) from {loc}; satisfying, rewatchable",
        "wait_for_it": "'wait for it' format: tease at the start, the clip ends on a freeze frame at the punchline",
        "live_boomerang": "a Live Photo from {loc} turned into a boomerang loop",
        "live_slowmo": "a Live Photo from {loc} in slow motion, nostalgic",
        "live_still_reveal": "starts as a still photo from {loc}, then it comes alive (Live Photo motion)",
        "live_with_sound": "a Live Photo from {loc} with its original sound/speech, subtitles",
        "photo_single": "one beautiful photo from {loc} with slow zoom and a story-style text",
    }

    # visual effect per format (renderer applies them)
    FORMAT_FX = {
        "slowmo": {"speed": 0.5}, "live_slowmo": {"speed": 0.5},
        "loop": {"boomerang": 3}, "live_boomerang": {"boomerang": 2},
        "wait_for_it": {"freeze_end": 1.5},
    }

    def write_script(self, c) -> dict:
        lang = self.d["creator_language"]
        sys = SYSTEM.format(lang=lang, caption_langs=" and ".join(self.d["caption_languages"]))
        brief = self.FORMAT_BRIEFS[c["format"]].format(loc=c.get("loc"), category=c.get("category"),
                                                      day=c.get("day"))
        prompt = (f"Video format: {brief}.\nTarget length {self.d['min_duration']}-{self.d['max_duration']}s.\n"
                  f"Variant #{c['variant'] + 1} (make it feel different from other variants).\n\n"
                  f"Available clips:\n{self._clip_lines(c)}\n\n"
                  "Return JSON: title; hook_text (first 2 seconds, on screen); clip_order = indexes of the "
                  "clips to use in order (you may drop weak ones, keep at least 1); clip_texts = one short "
                  "on-screen text per clip in clip_order (\"\" for none); outro_text (short CTA or punchline); "
                  "music_mood; instagram_caption; tiktok_caption; youtube_title (<70 chars); "
                  "youtube_description; hashtags.")
        s = self.llm.text_json(prompt, PLAN_SCHEMA, system=sys, purpose="director", max_tokens=3000)
        n = len(c["moments"])
        s["clip_order"] = [i for i in dict.fromkeys(s.get("clip_order") or []) if isinstance(i, int) and 0 <= i < n] \
            or list(range(n))
        return s

    def template_script(self, c) -> dict:
        loc = c.get("loc") or "Trip"
        tr = self.d["creator_language"] == "tr"
        fmt = c["format"]
        hooks = {
            "city_montage": (f"{loc} günlüğü", f"This is {loc}"),
            "top5": (f"{loc}'de en iyi 5 an", f"Top 5 moments in {loc}"),
            "pov_arrival": (f"POV: {loc}'ye yeni geldin", f"POV: you just landed in {loc}"),
            "photo_dump": (f"{loc} photo dump", f"{loc} photo dump"),
            "day_vlog": (f"{loc}'de bir gün", f"A day in {loc}"),
            "funny_single": ("Bunu beklemiyordum 😂", "Did not expect this 😂"),
            "funny_compilation": (f"{loc}'de en komik anlarımız", f"Our funniest moments in {loc}"),
            "quote": ("Sonuna kadar izle 😅", "Wait for it 😅"),
            "live_reel": ("Live Photos canlanıyor", "Live Photos, but alive"),
            "single_hook": ("Burası gerçek mi?", "Is this place real?"),
            "split_compare": (f"{loc}", f"{loc}"),
            "trip_recap": ("Bu tatil unutulmaz", "A trip to remember"),
            "clip_full": (f"{loc}'de bu oldu", f"This happened in {loc}"),
            "slowmo": (f"{loc}, yavaş çekimde", f"{loc} in slow motion"),
            "loop": ("Bunu izlemeyi bırakamıyorum", "Can't stop watching this"),
            "wait_for_it": ("Sonunu bekle...", "Wait for it..."),
            "live_boomerang": ("Live Photo ama canlı", "Live Photo, but make it move"),
            "live_slowmo": ("O an, yavaş çekimde", "That moment, slowed down"),
            "live_still_reveal": ("Fotoğraf sandın değil mi?", "You thought this was a photo"),
            "live_with_sound": ("Sesi aç 🔊", "Sound on 🔊"),
            "photo_single": (f"{loc}'den bir kare", f"One frame from {loc}"),
        }
        if fmt == "category":
            hook = CAT_TITLES[c["category"]][0 if tr else 1].format(city=loc)
        else:
            hook = hooks.get(fmt, (loc, loc))[0 if tr else 1]
        if c.get("single"):  # vary single-asset products with the vision model's own text ideas
            ideas = (self.assets[c["moments"][0]["asset_id"]].get("vision") or {}).get("overlay_ideas") or []
            if c["variant"] and len(ideas) >= c["variant"]:
                hook = ideas[c["variant"] - 1]
        n = len(c["moments"])
        texts = [""] * n
        if fmt == "top5":
            texts = [f"{n - i}." for i in range(n)]
        mood = {"funny_single": "funny", "funny_compilation": "funny", "quote": "none", "photo_dump": "chill",
                "trip_recap": "emotional", "city_montage": "upbeat"}.get(fmt, "upbeat")
        tag = loc.replace(" ", "").replace(",", "")
        return {"title": hook, "hook_text": hook, "clip_order": list(range(n)), "clip_texts": texts,
                "outro_text": "Kaydet, sonra lazım olur 📌" if tr else "Save this for later 📌",
                "music_mood": mood,
                "instagram_caption": f"{hook} ✈️\nSen olsan ilk nereye giderdin?",
                "tiktok_caption": f"{hook} ✈️",
                "youtube_title": hook[:70], "youtube_description": hook,
                "hashtags": [f"#{tag}", "#travel", "#seyahat", "#travelreels", "#gezi", "#shorts"]}

    # ---------------------------------------------------------------- plan
    def build_plan(self, c, s) -> dict:
        fmt = c["format"]
        order = s["clip_order"]
        texts = s.get("clip_texts") or []
        fast = fmt in ("city_montage", "live_reel", "trip_recap", "top5", "photo_dump", "category", "split_compare")
        max_d = self.d["max_duration"]
        segs, total = [], 0.0
        split_n = c.get("split")
        if c.get("single"):
            segs, total = self._single_segments(c, texts[0] if texts else "")
        elif split_n:  # pair clip i of side A with clip i of side B
            pairs = list(zip(c["moments"][:split_n], c["moments"][split_n:]))
            for k, (ma, mb) in enumerate(pairs):
                sa, sb = self._seg(ma, 2.5), self._seg(mb, 2.5)
                d = min(sa["dur"], sb["dur"])
                sa["dur"] = sb["dur"] = d
                sa["out"] = sa["in"] + d if sa["type"] == "video" else 0
                sb["out"] = sb["in"] + d if sb["type"] == "video" else 0
                sa.update(layout="split", split_with=sb, text=texts[k] if k < len(texts) else "")
                segs.append(sa)
                total += d
        else:
            for k, i in enumerate(order):
                m = c["moments"][i]
                cap = 1.8 if fast else (8.0 if fmt in ("funny_single", "quote", "single_hook") else 4.0)
                if fmt in ("funny_single", "quote"):
                    cap = 15.0
                seg = self._seg(m, cap)
                seg["text"] = texts[k] if k < len(texts) else ""
                if total + seg["dur"] > max_d:
                    break
                segs.append(seg)
                total += seg["dur"]
        # single short clip: widen the window around the moment up to the minimum duration
        if total < self.d["min_duration"] and fmt in ("funny_single", "quote", "single_hook") and segs:
            seg = segs[0]
            a = self.assets[seg["asset_id"]]
            if seg["type"] == "video" and a["duration"]:
                extra = self.d["min_duration"] - total
                seg["in"] = max(0, seg["in"] - extra * 0.6)
                seg["out"] = min(a["duration"], seg["out"] + extra * 0.4)
                seg["dur"] = round(seg["out"] - seg["in"], 2)
                seg["subtitles"] = self._subs(a, seg["in"], seg["out"])
                total = seg["dur"]
        mood = s.get("music_mood", "upbeat")
        if fmt in ("funny_single", "quote") and any(sg["keep_audio"] for sg in segs):
            mood = "none" if fmt == "quote" else mood
        return {
            "id": c["id"], "format": fmt, "variant": c["variant"], "loc": c.get("loc"),
            "category": c.get("category"), "day": c.get("day"),
            "title": s.get("title"), "hook_text": s.get("hook_text"), "outro_text": s.get("outro_text"),
            "music_mood": mood, "duration": round(total, 2),
            "segments": segs,
            "captions": {k: s.get(k) for k in ("instagram_caption", "tiktok_caption", "youtube_title",
                                               "youtube_description", "hashtags")},
            "created": datetime.now().isoformat(timespec="seconds"),
        }

    def _single_segments(self, c, text: str) -> tuple[list[dict], float]:
        """Segments for products made from ONE asset (video / Live Photo / photo)."""
        fmt, m = c["format"], c["moments"][0]
        a = self.assets[m["asset_id"]]
        dur_a = a.get("duration") or 0
        fx = dict(self.FORMAT_FX.get(fmt, {}))
        segs = []
        if fmt == "photo_single":
            seg = self._seg(dict(m, kind="photo"), 10)
            seg.update(dur=6.0, kenburns="in", text=text)
            return [seg], 6.0
        if fmt == "live_still_reveal":
            still = self._seg(dict(m, kind="photo"), 10)
            still.update(src=a["photo_path"], dur=1.6, kenburns="in")
            segs.append(still)
        if fmt == "clip_full":
            mm = dict(m, start=0, end=dur_a)
            seg = self._seg(mm, float(self.d["max_duration"]))
            seg["keep_audio"] = bool(a["has_audio"])
            seg["subtitles"] = self._subs(a, seg["in"], seg["out"])
        elif a["kind"] == "live" or fmt.startswith("live_"):
            mm = dict(m, start=0, end=dur_a, kind="live")
            seg = self._seg(mm, 10)
            seg["keep_audio"] = fmt == "live_with_sound" and bool(a["has_audio"])
            seg["subtitles"] = self._subs(a, seg["in"], seg["out"]) if fmt == "live_with_sound" else []
        elif fmt in ("slowmo", "loop"):
            seg = self._seg(m, 3.0 if fmt == "slowmo" else 2.0)
            seg["keep_audio"], seg["subtitles"] = False, []
        else:  # wait_for_it: the moment with some lead-in, ending on the punchline
            seg = self._seg(dict(m, start=max(0, m["start"] - 3)), 12.0)
            seg["keep_audio"] = bool(a["has_audio"])
            seg["subtitles"] = self._subs(a, seg["in"], seg["out"])
        src_len = seg["out"] - seg["in"]
        speed = fx.get("speed", 1.0)
        out_len = src_len / speed * (2 * fx["boomerang"] if fx.get("boomerang") else 1) + fx.get("freeze_end", 0)
        seg.update(fx=fx, dur=round(out_len, 2), text=text if fmt != "live_still_reveal" else "")
        if speed != 1:
            seg["subtitles"] = [dict(s, s=s["s"] / speed, e=s["e"] / speed) for s in seg["subtitles"]]
        segs.append(seg)
        return segs, round(sum(s["dur"] for s in segs), 2)

    def _seg(self, m, cap: float) -> dict:
        a = self.assets[m["asset_id"]]
        v = a.get("vision") or {}
        crop_x = v.get("subject_x")
        crop_x = 0.5 if not isinstance(crop_x, (int, float)) or not 0 <= crop_x <= 1 else crop_x
        if a["kind"] == "photo" or (m["kind"] == "photo"):
            return {"asset_id": a["id"], "type": "photo", "src": a["photo_path"], "in": 0, "out": 0,
                    "dur": min(2.2, cap) if cap < 3 else 2.8, "crop_x": crop_x, "keep_audio": False,
                    "layout": "auto", "subtitles": [], "kenburns": random.choice(["in", "out", "left", "right"])}
        start, end = float(m["start"]), float(m["end"] or a["duration"])
        if end - start > cap:
            mid = (start + end) / 2 if m["kind"] not in ("funny", "speech", "reaction") else start + cap / 2
            start, end = max(0, mid - cap / 2), min(a["duration"], mid + cap / 2)
        if end - start < 1.0:
            end = min(a["duration"], start + 1.5)
        talky = m["kind"] in ("funny", "speech", "reaction") or bool((a.get("transcript") or {}).get("text"))
        return {"asset_id": a["id"], "type": "video", "src": a["video_path"], "in": round(start, 2),
                "out": round(end, 2), "dur": round(end - start, 2), "crop_x": crop_x,
                "keep_audio": bool(a["has_audio"]) and talky, "layout": "auto",
                "subtitles": self._subs(a, start, end) if talky else []}

    @staticmethod
    def _subs(a, start, end, max_words=4) -> list[dict]:
        words = [w for s in (a.get("transcript") or {}).get("segments") or [] for w in s.get("words") or []]
        words = [w for w in words if w["e"] > start and w["s"] < end]
        subs, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= max_words or w["w"].strip().endswith((".", "?", "!", ",")):
                subs.append(cur)
                cur = []
        if cur:
            subs.append(cur)
        return [{"s": round(max(0, c[0]["s"] - start), 2), "e": round(min(end, c[-1]["e"]) - start, 2),
                 "text": " ".join(w["w"].strip() for w in c)} for c in subs]
