"""Per-asset deep analysis: audio (speech + events) and vision, merged into
timestamped 'moments' the director can cut from."""
from __future__ import annotations

import traceback
from pathlib import Path

from tqdm import tqdm

from . import media
from .catalog import Catalog
from .config import Config
from .llm import Backend

CATEGORIES = ["food", "drink", "street", "city", "landmark", "nature", "beach", "mountain", "water",
              "transport", "airport", "hotel", "nightlife", "shopping", "market", "museum", "people",
              "selfie", "group", "animal", "sunset", "night", "funny", "adventure", "culture",
              "sport", "music", "art", "other"]
MOMENT_KINDS = ["funny", "scenic", "action", "food", "people", "reaction", "hook", "detail"]

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "place_guess": {"type": "string"},
        "categories": {"type": "array", "items": {"type": "string", "enum": CATEGORIES}},
        "people_count": {"type": "integer"},
        "mood": {"type": "string"},
        "humor_score": {"type": "integer"},
        "humor_reason": {"type": "string"},
        "hook_score": {"type": "integer"},
        "aesthetic_score": {"type": "integer"},
        "visible_text": {"type": "string"},
        "subject_x": {"type": "number"},
        "overlay_ideas": {"type": "array", "items": {"type": "string"}},
        "moments": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "frame": {"type": "integer"},
                "kind": {"type": "string", "enum": MOMENT_KINDS},
                "score": {"type": "integer"},
                "description": {"type": "string"},
            },
            "required": ["frame", "kind", "score", "description"],
        }},
    },
    "required": ["summary", "categories", "humor_score", "hook_score", "aesthetic_score",
                 "subject_x", "moments", "mood", "overlay_ideas", "place_guess",
                 "people_count", "humor_reason", "visible_text"],
}

PROMPT = """You are a social-media video editor reviewing raw travel footage for short vertical videos
(Instagram Reels, TikTok, YouTube Shorts). Look carefully at THIS specific media and describe only what you
actually see. {what}

Context we already know (may be empty):
- Location metadata: {place}
- Date: {date}
- Apple Photos labels: {labels}
- Spoken audio transcript: {transcript}
- Detected sounds: {events}

Return JSON:
- summary: 1-2 sentences, concrete: who/what/where/what happens.
- place_guess: recognizable landmark, venue or city if you can tell, else "".
- categories: all that apply from the allowed list.
- people_count: number of clearly visible people.
- mood: one or two words.
- humor_score 0-10: how funny/absurd/relatable this is (use transcript + sounds; 0 if nothing funny).
- humor_reason: why (or "").
- hook_score 0-10: would the first second stop someone scrolling?
- aesthetic_score 0-10: visual quality / cinematic feel.
- visible_text: any signs, menus or text readable in the image (or "").
- subject_x: horizontal position 0.0 (left) - 1.0 (right) of the main subject, used to crop to 9:16.
- overlay_ideas: 2-4 short punchy on-screen text ideas in {lang} (max 8 words each) that fit this footage.
- moments: notable moments; frame = the #number label of the tile{frame_note}; kind from the allowed list;
  score 0-10; description short.
"""


def _norm(v, lo=0, hi=10):
    try:
        return max(lo, min(hi, float(v))) / hi
    except (TypeError, ValueError):
        return 0.0


class Analyzer:
    def __init__(self, cfg: Config, cat: Catalog):
        self.cfg, self.cat = cfg, cat
        self.a = cfg["analysis"]
        self.frames_dir = cfg.ws("cache", "frames")
        self.audio_dir = cfg.ws("cache", "audio")
        self.models_dir = cfg.ws("models")
        self._tr = self._ev = self._llm = None

    # lazy model loading
    @property
    def transcriber(self):
        if self._tr is None:
            from .audio import Transcriber
            print(f"🎙️  Whisper yükleniyor: {self.a['whisper_model']}")
            self._tr = Transcriber(self.a["whisper_model"], self.a["whisper_compute"],
                                   self.a.get("language"), self.models_dir / "whisper")
        return self._tr

    @property
    def events(self):
        if self._ev is None and self.a.get("audio_events"):
            try:
                from .audio import EventDetector
                self._ev = EventDetector(self.models_dir)
            except Exception as e:
                print(f"⚠️  Ses olayı modeli yüklenemedi ({e}); sadece transkript kullanılacak.")
                self.a["audio_events"] = False
        return self._ev

    @property
    def llm(self):
        if self._llm is None:
            self._llm = Backend(self.cfg, self.cat)
        return self._llm

    # ------------------------------------------------------------------
    def run(self, only: str | None = None, redo: bool = False, limit: int | None = None):
        where = "1=1" if redo else "(analyzed_audio=0 OR analyzed_vision=0)"
        if only:
            where += f" AND kind='{only}'"
        assets = self.cat.assets(where)[:limit]
        # audio first for everything (one model in memory), then vision
        for a in tqdm(assets, desc="🎧 Ses"):
            if redo or not a["analyzed_audio"]:
                self._safe(self.audio, a)
        for a in tqdm(assets, desc="👁️  Görüntü"):
            a = self.cat.asset(a["id"])
            if redo or not a["analyzed_vision"]:
                self._safe(self.vision, a)
            self.build_moments(self.cat.asset(a["id"]))

    def _safe(self, fn, a):
        try:
            fn(a)
        except Exception as e:
            self.cat.update(a["id"], error=f"{fn.__name__}: {e}")
            tqdm.write(f"⚠️  {a['id']} {fn.__name__}: {e}")
            if self.cfg.data.get("debug"):
                traceback.print_exc()

    # ------------------------------------------------------------------
    def audio(self, a: dict):
        if not a["video_path"] or not a["has_audio"]:
            self.cat.update(a["id"], analyzed_audio=1)
            return
        wav = media.extract_audio(Path(a["video_path"]), self.audio_dir / f"{a['id']}.wav")
        from .audio import loudness_peaks
        tr = self.transcriber(wav)
        ev = self.events(wav) if self.events else []
        ev += loudness_peaks(wav)
        self.cat.update(a["id"], transcript=tr, audio_events=ev, analyzed_audio=1)
        wav.unlink(missing_ok=True)

    def vision(self, a: dict):
        max_px = self.a["max_image_px"]
        frame_times: list[float] = []
        if a["kind"] == "photo" or (a["kind"] == "live" and a["photo_path"]):
            img = self.frames_dir / f"{a['id']}.jpg"
            media.load_image(Path(a["photo_path"]), max_px).save(img, quality=85)
            images, what, note = [img], "It is a single photo" + (
                " (a Live Photo: a 3-second clip exists too)." if a["kind"] == "live" else "."), \
                " (use 1 for a single photo)"
            frame_times = [a["duration"] / 2 if a["kind"] == "live" else 0]
        else:
            n = self.a["frames_per_video"]
            frame_times = media.pick_frame_times(Path(a["video_path"]), a["duration"], n)
            frames = [(t, media.extract_frame(Path(a["video_path"]), t,
                                              self.frames_dir / f"{a['id']}_{i}.jpg", max_px))
                      for i, t in enumerate(frame_times)]
            sheet = media.contact_sheet(frames, self.frames_dir / f"{a['id']}_sheet.jpg",
                                        cell=max_px // 2)
            images = [sheet]
            what = (f"It is a {a['duration']:.0f}-second video shown as a grid of {len(frames)} frames "
                    f"in time order; each tile is labelled #number and its timestamp.")
            note = ""
        tr = a.get("transcript") or {}
        prompt = PROMPT.format(
            what=what,
            place=", ".join(x for x in [a.get("place"), a.get("city"), a.get("country")] if x) or "unknown",
            date=a.get("taken_at") or "unknown",
            labels=", ".join((a.get("apple_labels") or [])[:20]) or "none",
            transcript=(tr.get("text") or "none")[:1500],
            events=", ".join(sorted({e["label"] for e in (a.get("audio_events") or [])})) or "none",
            lang=self.cfg["director"]["creator_language"], frame_note=note)
        res = self.llm.vision_json(images, prompt, VISION_SCHEMA)
        res["_frame_times"] = frame_times
        self.cat.update(a["id"], vision=res, analyzed_vision=1, error=None)

    # ------------------------------------------------------------------
    def build_moments(self, a: dict):
        v = a.get("vision") or {}
        dur = a.get("duration") or 0
        cats = v.get("categories") or []
        base_tags = list(dict.fromkeys(cats + [v.get("mood", "")]))
        humor, hook, aes = (_norm(v.get(k)) for k in ("humor_score", "hook_score", "aesthetic_score"))
        moments = []

        if a["kind"] == "photo":
            moments.append({"start": 0, "end": 0, "kind": "photo", "score": 0.5 * aes + 0.3 * hook + 0.2 * humor,
                            "text": v.get("summary"), "tags": base_tags})
        elif a["kind"] == "live":
            moments.append({"start": 0, "end": dur, "kind": "funny" if humor >= 0.6 else "live",
                            "score": 0.4 * aes + 0.3 * hook + 0.3 * humor, "text": v.get("summary"),
                            "tags": base_tags})
        else:
            times = v.get("_frame_times") or []
            for m in v.get("moments") or []:
                i = int(m.get("frame", 1)) - 1
                if not 0 <= i < len(times):
                    continue
                t = times[i]
                moments.append({"start": round(max(0, t - 1.5), 2), "end": round(min(dur, t + 2.5), 2),
                                "kind": m.get("kind", "scenic"),
                                "score": 0.6 * _norm(m.get("score")) + 0.2 * aes + 0.2 * hook,
                                "text": m.get("description"), "tags": base_tags})
            if not moments and dur:
                moments.append({"start": 0, "end": min(dur, 6), "kind": "scenic", "score": 0.5 * aes + 0.2 * hook,
                                "text": v.get("summary"), "tags": base_tags})

        # audio-driven moments
        segs = (a.get("transcript") or {}).get("segments") or []
        for e in a.get("audio_events") or []:
            if e["label"] in ("laughter", "scream", "shout", "cheering", "gasp", "loud"):
                # include the few seconds BEFORE the laugh: that's usually the joke
                s, t = max(0, e["start"] - 3.5), min(dur or e["end"] + 1, e["end"] + 1.0)
                quote = " ".join(x["text"] for x in segs if x["end"] >= s and x["start"] <= t)
                moments.append({"start": round(s, 2), "end": round(t, 2),
                                "kind": "funny" if e["label"] in ("laughter", "cheering") else "reaction",
                                "score": min(1.0, 0.5 + 0.5 * e["score"] + 0.2 * humor),
                                "text": quote or e["label"], "tags": base_tags + [e["label"]]})
        for s in segs:
            words = len(s["text"].split())
            if words >= 3:
                moments.append({"start": max(0, s["start"] - 0.3), "end": min(dur or s["end"], s["end"] + 0.4),
                                "kind": "speech", "score": min(1.0, 0.3 + 0.03 * words + 0.4 * humor),
                                "text": s["text"], "tags": base_tags + ["speech"]})
        if a["kind"] != "photo" and hook >= 0.7 and dur:
            moments.append({"start": 0, "end": min(dur, 3), "kind": "hook", "score": hook,
                            "text": v.get("summary"), "tags": base_tags})
        for m in moments:
            m["score"] = round(m["score"], 3)
        self.cat.replace_moments(a["id"], moments)
