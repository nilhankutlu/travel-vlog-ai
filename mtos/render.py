"""Plan -> 1080x1920 mp4 with ffmpeg.

Text is drawn with Pillow into transparent PNGs and overlaid, so this works
with any ffmpeg build (no drawtext/libass needed) and on any OS."""
from __future__ import annotations

import json
import random
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from tqdm import tqdm

from . import media
from .config import Config

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def _font_path(cfg) -> str | None:
    p = cfg["render"].get("font")
    if p and Path(p).exists():
        return p
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


class TextPainter:
    def __init__(self, cfg: Config, W: int, H: int):
        self.W, self.H = W, H
        self.font_path = _font_path(cfg)

    def font(self, size):
        return ImageFont.truetype(self.font_path, size) if self.font_path else ImageFont.load_default(size)

    def _wrap(self, text, font, max_w):
        words, lines, cur = text.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if font.getlength(t) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def png(self, text: str, out: Path, style: str = "caption") -> Path | None:
        text = EMOJI_RE.sub("", text or "").strip()
        if not text:
            return None
        W, H = self.W, self.H
        spec = {  # size, y-center (fraction of H), box?
            "hook": (84, 0.20, True), "clip": (64, 0.25, False), "sub": (62, 0.66, False),
            "outro": (76, 0.45, True), "mark": (34, 0.93, False),
        }[style]
        size, yc, box = spec
        font = self.font(size)
        lines = self._wrap(text.upper() if style in ("hook", "clip") else text, font, W * 0.82)
        while len(lines) > 4 and size > 36:
            size -= 6
            font = self.font(size)
            lines = self._wrap(text, font, W * 0.82)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        lh = int(size * 1.18)
        y = int(H * yc - lh * len(lines) / 2)
        for ln in lines:
            tw = font.getlength(ln)
            x = int((W - tw) / 2)
            if box:
                pad = int(size * 0.28)
                d.rounded_rectangle([x - pad, y - pad // 2, x + tw + pad, y + lh - pad // 4],
                                    radius=pad, fill=(255, 255, 255, 235))
                d.text((x, y), ln, font=font, fill=(10, 10, 10, 255))
            else:
                fill = (255, 230, 0, 255) if style == "sub" else (255, 255, 255, 255)
                d.text((x, y), ln, font=font, fill=fill, stroke_width=max(3, size // 12),
                       stroke_fill=(0, 0, 0, 255))
            y += lh
        img.save(out)
        return out


# ---------------------------------------------------------------- photos
def photo_frame(src: Path, out: Path, W: int, H: int, crop_x: float = 0.5, scale: float = 2.0) -> Path:
    """Prepare a 9:16 still at `scale`x output size (for smooth Ken Burns).
    Landscape photos are placed on a blurred copy of themselves instead of being cropped hard."""
    img = media.load_image(src)
    TW, TH = int(W * scale), int(H * scale)
    ar = img.width / img.height
    if ar > 0.8:  # landscape / square -> blurred background fill
        bg = ImageOps.fit(img, (TW // 8, TH // 8)).filter(ImageFilter.GaussianBlur(6)).resize((TW, TH))
        bg = Image.blend(bg, Image.new("RGB", bg.size, "black"), 0.25)
        fg = img.copy()
        fg.thumbnail((TW, TH))
        if fg.width < TW:
            fg = fg.resize((TW, int(TW / ar)))
        bg.paste(fg, (0, (TH - fg.height) // 2))
        bg.save(out, quality=92)
    else:
        ImageOps.fit(img, (TW, TH), centering=(crop_x, 0.5)).save(out, quality=92)
    return out


# ---------------------------------------------------------------- renderer
class Renderer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        r = cfg["render"]
        self.W, self.H, self.fps = r["width"], r["height"], r["fps"]
        self.painter = TextPainter(cfg, self.W, self.H)
        self.music_dir = cfg.path(r.get("music_dir"))
        self.out_dir = cfg.ws("outputs")

    def _enc(self):
        r = self.cfg["render"]
        return ["-c:v", "libx264", "-preset", r["preset"], "-crf", str(r["crf"]), "-pix_fmt", "yuv420p",
                "-r", str(self.fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]

    def _video_chain(self, label_in: str, seg: dict, src_ar: float, label_out: str) -> str:
        W, H = self.W, self.H
        cx = seg.get("crop_x", 0.5)
        layout = seg.get("layout", "auto")
        if layout == "auto":
            layout = "blur" if src_ar > 1.05 else "full"
        if layout == "blur":
            return (f"[{label_in}]split[bga][fga];"
                    f"[bga]scale={W // 8}:{H // 8}:force_original_aspect_ratio=increase,crop={W // 8}:{H // 8},"
                    f"boxblur=6:2,scale={W}:{H},eq=brightness=-0.08[bg];"
                    f"[fga]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{label_out}]")
        return (f"[{label_in}]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}:x='(iw-{W})*{cx:.3f}':y='(ih-{H})/2',setsar=1[{label_out}]")

    def _src_ar(self, seg) -> float:
        try:
            i = media.video_info(Path(seg["src"]))
            return i["width"] / max(1, i["height"])
        except Exception:
            return 9 / 16

    def _input_args(self, seg: dict, tmp: Path, k: int, half: bool = False) -> tuple[list[str], str, float]:
        """Returns ffmpeg input args, a filter chain producing [v{k}] and the source aspect ratio."""
        W, H = self.W, (self.H // 2 if half else self.H)
        dur = seg["dur"]
        if seg["type"] == "photo":
            frame = photo_frame(Path(seg["src"]), tmp / f"ph{k}.jpg", W, H, seg.get("crop_x", 0.5))
            n = max(1, int(dur * self.fps))
            kb = seg.get("kenburns", "in")
            z = {"in": "min(1+0.10*on/{n},1.10)", "out": "1.10-0.10*on/{n}"}.get(kb, "1.08").format(n=n)
            x = {"left": "(iw-iw/zoom)*(1-on/{n})", "right": "(iw-iw/zoom)*on/{n}"}.get(
                kb, "iw/2-(iw/zoom/2)").format(n=n)
            chain = (f"[{k}:v]zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={self.fps},"
                     f"setsar=1,trim=duration={dur}[v{k}]")
            return ["-loop", "1", "-framerate", str(self.fps), "-t", f"{dur}", "-i", str(frame)], chain, W / H
        src_len = (seg["out"] - seg["in"]) if seg.get("out") else dur
        args = ["-ss", f"{seg['in']}", "-t", f"{src_len:.3f}", "-i", seg["src"]]
        ar = self._src_ar(seg)
        if half:
            chain = (f"[{k}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                     f"crop={W}:{H}:x='(iw-{W})*{seg.get('crop_x', 0.5):.3f}':y='(ih-{H})/2',setsar=1[pre{k}]")
        else:
            chain = self._video_chain(f"{k}:v", seg, ar, f"pre{k}")
        chain += f";[pre{k}]{self._fx_chain(seg.get('fx') or {}, src_len, k)}[v{k}]"
        return args, chain, ar

    def _fx_chain(self, fx: dict, src_len: float, k: int) -> str:
        """Speed change, boomerang loop and freeze-frame, as one filter chain."""
        speed = float(fx.get("speed", 1.0))
        parts = [f"setpts=PTS/{speed}" if speed != 1 else "setpts=PTS-STARTPTS", f"fps={self.fps}"]
        chain = ",".join(parts)
        if fx.get("boomerang"):
            n = int(fx["boomerang"])
            frames = int(2 * src_len / speed * self.fps) + 2
            chain += (f",split[bf{k}][br{k}];[br{k}]reverse[brv{k}];[bf{k}][brv{k}]concat=n=2:v=1:a=0,"
                      f"loop=loop={n - 1}:size={frames}:start=0,setpts=N/{self.fps}/TB")
        if fx.get("freeze_end"):
            chain += f",tpad=stop_mode=clone:stop_duration={fx['freeze_end']}"
        return chain

    def render_segment(self, seg: dict, tmp: Path, idx: int) -> Path:
        out = tmp / f"seg{idx:03d}.mp4"
        dur = seg["dur"]
        inputs, chains = [], []
        a_args, chain, _ = self._input_args(seg, tmp, 0, half=seg.get("layout") == "split")
        inputs += a_args
        chains.append(chain)
        vlabel = "v0"
        if seg.get("layout") == "split" and seg.get("split_with"):
            b_args, chain_b, _ = self._input_args(seg["split_with"], tmp, 1, half=True)
            inputs += b_args
            chains.append(chain_b)
            chains.append(f"[v0][v1]vstack=inputs=2,setsar=1[vs]")
            vlabel = "vs"
        n_in = sum(1 for a in inputs if a == "-i")
        # text overlays for this segment
        overlays = []
        if seg.get("text"):
            p = self.painter.png(seg["text"], tmp / f"t{idx}.png", "clip")
            if p:
                overlays.append((p, 0, dur))
        if self.cfg["render"].get("burn_subtitles"):
            for j, s in enumerate(seg.get("subtitles") or []):
                p = self.painter.png(s["text"], tmp / f"s{idx}_{j}.png", "sub")
                if p:
                    overlays.append((p, s["s"], max(s["e"], s["s"] + 0.4)))
        for p, _, _ in overlays:
            inputs += ["-i", str(p)]
        cur = vlabel
        for j, (p, s, e) in enumerate(overlays):
            nxt = f"o{j}"
            chains.append(f"[{cur}][{n_in + j}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'[{nxt}]")
            cur = nxt
        # audio: original (speech/laughs) or quiet ambience, or silence
        has_audio = False
        fx = seg.get("fx") or {}
        if seg["type"] == "video" and not fx.get("boomerang"):  # reversed audio sounds wrong: mute loops
            try:
                has_audio = media.video_info(Path(seg["src"]))["has_audio"]
            except Exception:
                pass
        if has_audio:
            vol = 1.0 if seg.get("keep_audio") else 0.18
            speed = float(fx.get("speed", 1.0))
            tempo = f"atempo={max(0.5, min(2.0, speed))}," if speed != 1 else ""
            chains.append(f"[0:a]{tempo}volume={vol},aresample=48000,aformat=channel_layouts=stereo,"
                          f"apad,atrim=duration={dur}[a]")
        else:
            inputs += ["-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo"]
            chains.append(f"[{n_in + len(overlays)}:a]atrim=duration={dur}[a]")
        cmd = [media.FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains),
               "-map", f"[{cur}]", "-map", "[a]", "-t", f"{dur}", *self._enc(), str(out)]
        media.run(cmd)
        return out

    def pick_music(self, mood: str, plan_id: str) -> Path | None:
        if not mood or mood == "none" or not self.music_dir or not self.music_dir.exists():
            return None
        files = [p for p in (self.music_dir / mood).glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")]
        files = files or [p for p in self.music_dir.rglob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav")]
        return random.Random(plan_id).choice(files) if files else None

    def render(self, plan: dict, out: Path) -> Path:
        with tempfile.TemporaryDirectory(prefix="mtos_") as td:
            tmp = Path(td)
            segs = [self.render_segment(s, tmp, i) for i, s in enumerate(plan["segments"])]
            lst = tmp / "list.txt"
            lst.write_text("".join(f"file '{p}'\n" for p in segs))
            body = tmp / "body.mp4"
            media.run([media.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                       "-c", "copy", str(body)])
            total = sum(s["dur"] for s in plan["segments"])

            inputs = ["-i", str(body)]
            chains, cur, n = [], "0:v", 1
            ov = []
            hook = self.painter.png(plan.get("hook_text"), tmp / "hook.png", "hook")
            if hook:
                ov.append((hook, 0, min(2.8, total)))
            outro = self.painter.png(plan.get("outro_text"), tmp / "outro.png", "outro")
            if outro and total > 6:
                ov.append((outro, total - 2.2, total))
            wm = self.cfg["render"].get("watermark")
            if wm:
                p = self.painter.png(wm, tmp / "wm.png", "mark")
                ov.append((p, 0, total))
            for j, (p, s, e) in enumerate(ov):
                inputs += ["-i", str(p)]
                chains.append(f"[{cur}][{n}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'[ov{j}]")
                cur, n = f"ov{j}", n + 1
            if not chains:
                chains.append("[0:v]null[ov]")
                cur = "ov"
            music = self.pick_music(plan.get("music_mood"), plan["id"])
            if music:
                mv = self.cfg["render"]["music_volume"]
                inputs += ["-stream_loop", "-1", "-i", str(music)]
                chains.append(f"[{n}:a]atrim=duration={total},volume={mv},afade=t=in:d=0.5,"
                              f"afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5,aformat=channel_layouts=stereo[m]")
                chains.append("[0:a]asplit[voice][sc]")
                chains.append("[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
                chains.append("[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
            else:
                chains.append("[0:a]loudnorm=I=-14:TP=-1.5[a]")
            out.parent.mkdir(parents=True, exist_ok=True)
            media.run([media.FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains),
                       "-map", f"[{cur}]", "-map", "[a]", "-t", f"{total:.2f}", *self._enc(),
                       "-movflags", "+faststart", str(out)])
            media.extract_frame(out, min(1.0, total / 2), out.with_suffix(".jpg"), 540)
        return out


def captions_text(plan: dict) -> str:
    c = plan.get("captions") or {}
    tags = " ".join(c.get("hashtags") or [])
    return (f"# {plan.get('title')}\nformat: {plan['format']}  |  {plan.get('loc')}  |  {plan['duration']}s"
            f"  |  müzik: {plan.get('music_mood')}\n\n"
            f"== Instagram Reels ==\n{c.get('instagram_caption')}\n\n{tags}\n\n"
            f"== TikTok ==\n{c.get('tiktok_caption')}\n\n{tags}\n\n"
            f"== YouTube Shorts ==\nBaşlık: {c.get('youtube_title')}\n{c.get('youtube_description')}\n\n"
            f"{tags} #shorts\n")


def render_all(cfg: Config, cat, limit=None, plan_id=None, force=False):
    r = Renderer(cfg)
    plans = sorted(cfg.ws("plans").glob("*.json"))
    if plan_id:
        plans = [p for p in plans if plan_id in p.stem]
    done = 0
    for p in tqdm(plans[:limit] if limit else plans, desc="🎞️  Render"):
        plan = json.loads(p.read_text(encoding="utf-8"))
        if not plan.get("segments"):
            continue
        out = r.out_dir / plan["format"] / f"{p.stem}.mp4"
        if out.exists() and not force:
            continue
        try:
            r.render(plan, out)
            out.with_suffix(".txt").write_text(captions_text(plan), encoding="utf-8")
            done += 1
        except Exception as e:
            tqdm.write(f"⚠️  {p.stem}: {str(e)[:600]}")
    print(f"✅ {done} video render edildi → {r.out_dir}")
