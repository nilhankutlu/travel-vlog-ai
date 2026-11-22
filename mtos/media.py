"""ffmpeg / ffprobe / Pillow helpers."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd[:6]))}...\n{p.stderr[-2000:]}")
    return p


def probe(path: Path) -> dict:
    p = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(p.stdout)


def video_info(path: Path) -> dict:
    """Duration, display size (rotation aware), audio, and Apple QuickTime metadata."""
    info = probe(path)
    fmt = info.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    w, h = v.get("width", 0), v.get("height", 0)
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = int((v.get("tags") or {}).get("rotate", rot))
    if abs(rot) in (90, 270):
        w, h = h, w
    lat = lon = None
    loc = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
    if loc:
        m = re.match(r"([+-]\d+\.?\d*)([+-]\d+\.?\d*)", loc)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
    taken = tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
    return {
        "duration": float(fmt.get("duration") or v.get("duration") or 0),
        "width": w, "height": h, "has_audio": has_audio,
        "lat": lat, "lon": lon, "taken_at": _iso(taken),
        "content_id": tags.get("com.apple.quicktime.content.identifier"),
        "is_live_motion": "com.apple.quicktime.live-photo.auto" in tags
                          or "com.apple.quicktime.still-image-time" in json.dumps(info),
    }


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).isoformat()
    except ValueError:
        return s


def _gps_to_deg(v, ref):
    d, m, s = (float(x) for x in v)
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def photo_info(path: Path) -> dict:
    img = Image.open(path)
    exif = img.getexif()
    w, h = img.size
    if exif.get(0x0112, 1) in (5, 6, 7, 8):
        w, h = h, w
    out = {"width": w, "height": h, "lat": None, "lon": None, "taken_at": None, "content_id": None}
    ifd = exif.get_ifd(ExifTags.IFD.Exif)
    dt = ifd.get(36867) or exif.get(306)
    out["taken_at"] = _iso(dt)
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    try:
        if gps and 2 in gps and 4 in gps:
            out["lat"] = _gps_to_deg(gps[2], gps.get(1, "N"))
            out["lon"] = _gps_to_deg(gps[4], gps.get(3, "E"))
    except Exception:
        pass
    # Apple MakerNote content identifier (pairs HEIC with its Live Photo MOV) is
    # not exposed by Pillow; folder ingest pairs by filename instead.
    return out


def load_image(path: Path, max_px: int | None = None) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if max_px:
        img.thumbnail((max_px, max_px))
    return img


def extract_frame(video: Path, t: float, out: Path, max_px: int = 768) -> Path:
    run([FFMPEG, "-y", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale='min({max_px},iw)':-2", "-q:v", "3", str(out)])
    return out


def scene_changes(video: Path, threshold: float = 0.3) -> list[float]:
    p = run([FFMPEG, "-v", "info", "-i", str(video), "-vf",
             f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"], check=False)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", p.stderr)]


def pick_frame_times(video: Path, duration: float, n: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    if duration < 4:
        return [duration * f for f in (0.2, 0.75)][:max(1, min(n, 2))]
    cuts = scene_changes(video) if duration > 6 else []
    even = [duration * (i + 0.5) / n for i in range(n)]
    times = sorted(set([round(t, 2) for t in cuts[: n // 2]] + even))
    # thin out to n, keep spread
    while len(times) > n:
        gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        times.pop(gaps.index(min(gaps)) + 1)
    return times


def extract_audio(video: Path, out: Path, sr: int = 16000) -> Path:
    run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr), "-f", "wav", str(out)])
    return out


def contact_sheet(frames: list[tuple[float, Path]], out: Path, cell: int = 384) -> Path:
    """Tile frames into one labelled image so the vision model sees the whole clip at once."""
    from PIL import ImageDraw
    imgs = [(t, load_image(p, cell)) for t, p in frames]
    cols = 3 if len(imgs) > 4 else 2 if len(imgs) > 1 else 1
    rows = (len(imgs) + cols - 1) // cols
    cw = max(i.width for _, i in imgs)
    ch = max(i.height for _, i in imgs)
    sheet = Image.new("RGB", (cols * cw, rows * ch), "black")
    d = ImageDraw.Draw(sheet)
    for k, (t, im) in enumerate(imgs):
        x, y = (k % cols) * cw, (k // cols) * ch
        sheet.paste(im, (x, y))
        label = f"#{k + 1} t={t:.1f}s"
        d.rectangle([x, y, x + 9 * len(label) + 8, y + 22], fill="black")
        d.text((x + 4, y + 4), label, fill="yellow")
    sheet.save(out, quality=85)
    return out
