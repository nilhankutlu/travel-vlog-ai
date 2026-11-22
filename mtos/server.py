"""Local web UI + JSON API.  Run:  mtos serve   →  http://localhost:8765

Long jobs (ingest / analyze / plan / render) run as `python -m mtos.cli -p <project> ...`
subprocesses, so a crash never takes the UI down; their output is streamed into
a per-project log and progress is parsed from the tqdm bars."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config as config_mod
from . import media
from .catalog import Catalog

ROOT = config_mod.ROOT
WEB = Path(__file__).parent / "web"
CFG_PATH: str | None = None

app = FastAPI(title="MegaTravelOS")
app.mount("/static", StaticFiles(directory=WEB), name="static")


# ================================================================ helpers
def proots() -> Path:
    return config_mod.projects_root(CFG_PATH)


def pcfg(name: str):
    if not (proots() / name / "project.yaml").exists():
        raise HTTPException(404, f"proje yok: {name}")
    return config_mod.load(CFG_PATH, name)


def pcat(name: str) -> Catalog:
    return Catalog(pcfg(name).workspace / "catalog.db")


def safe_file(name: str, rel: str) -> Path:
    base = (proots() / name).resolve()
    p = (base / rel).resolve()
    if base not in p.parents and p != base:
        raise HTTPException(403)
    if not p.exists():
        raise HTTPException(404)
    return p


# ================================================================ jobs
def pipeline_python() -> str:
    """The UI can run from a small venv; heavy jobs (whisper, YAMNet, osxphotos) use the full one.
    Override with MTOS_PIPELINE_PYTHON."""
    env = os.environ.get("MTOS_PIPELINE_PYTHON")
    if env:
        return env
    for cand in (Path.home() / ".venvs" / "mtos" / "bin" / "python", ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


class Job:
    def __init__(self, project: str, cmd: list[str], label: str):
        self.project, self.cmd, self.label = project, cmd, label
        self.log: deque[str] = deque(maxlen=600)
        self.progress: dict = {}
        self.status = "running"
        self.started = time.time()
        self.ended = None
        env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"}
        args = [pipeline_python(), "-m", "mtos.cli"] + (["-c", CFG_PATH] if CFG_PATH else []) + \
               ["-p", project] + cmd
        self.proc = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, bufsize=0, start_new_session=True)
        threading.Thread(target=self._pump, daemon=True).start()

    _bar = re.compile(r"^(?P<label>.*?):\s+(?P<pct>\d+)%\|.*?\|\s*(?P<n>\d+)/(?P<tot>\d+)")

    def _pump(self):
        buf = b""
        while True:
            ch = self.proc.stdout.read(1)
            if not ch:
                break
            if ch in (b"\n", b"\r"):
                line = buf.decode("utf-8", "replace").rstrip()
                buf = b""
                if not line:
                    continue
                m = self._bar.match(line)
                if m:
                    self.progress = {"label": m["label"].strip(), "pct": int(m["pct"]),
                                     "n": int(m["n"]), "total": int(m["tot"])}
                    if ch == b"\r":
                        continue
                self.log.append(line)
            else:
                buf += ch
        rc = self.proc.wait()
        self.status = "done" if rc == 0 else ("stopped" if rc < 0 else "failed")
        self.ended = time.time()

    def stop(self):
        if self.status == "running":
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def view(self):
        return {"label": self.label, "cmd": self.cmd, "status": self.status, "progress": self.progress,
                "log": list(self.log)[-250:], "started": self.started, "ended": self.ended}


JOBS: dict[str, Job] = {}


# ================================================================ pages
@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


# ================================================================ system
@app.get("/api/system")
def system():
    base = config_mod.load(CFG_PATH)
    du = shutil.disk_usage(base.workspace)
    models = []
    try:
        import ollama
        models = [m.model for m in ollama.Client(host=base["analysis"]["ollama"]["host"]).list().models]
    except Exception:
        pass
    return {"disk_free_gb": round(du.free / 1e9, 2), "disk_total_gb": round(du.total / 1e9, 1),
            "workspace": str(base.workspace), "ollama_models": models,
            "ffmpeg": bool(shutil.which("ffmpeg")), "ollama": bool(models)}


# ================================================================ projects
@app.get("/api/projects")
def projects():
    out = []
    for d in sorted(proots().iterdir()):
        if (d / "project.yaml").exists():
            p = yaml.safe_load((d / "project.yaml").read_text(encoding="utf-8")) or {}
            out.append({"name": d.name, "title": p.get("title") or d.name, "mode": p.get("mode", "shorts"),
                        "job": JOBS[d.name].status if d.name in JOBS else None})
    return out


@app.post("/api/projects")
def create_project(body: dict = Body(...)):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "isim gerekli")
    name = config_mod.slug(title)
    if (proots() / name / "project.yaml").exists():
        raise HTTPException(409, "bu isimde proje var")
    mode = body.get("mode", "shorts")
    src = {"type": body.get("source_type", "folder"), "folder": body.get("folder") or None,
           "copy_media": bool(body.get("copy_media", False)),
           "photos": {"shared_albums": body.get("shared_albums") or [], "albums": body.get("albums") or [],
                      "include_own_library": bool(body.get("include_own_library", False))}}
    pdata = {"title": title, "mode": mode, "created": datetime.now().isoformat(timespec="seconds"),
             "source": src}
    if mode == "longform":
        pdata["longform"] = {"target_minutes": int(body.get("target_minutes") or 12),
                             "max_minutes": int(body.get("max_minutes") or 20)}
    config_mod.save_project(CFG_PATH, name, pdata)
    return {"name": name}


@app.get("/api/projects/{name}")
def project(name: str):
    cfg = pcfg(name)
    cat = Catalog(cfg.workspace / "catalog.db")
    assets = cat.assets()
    plans = list(cfg.ws("plans").glob("*.json"))
    outputs = list(cfg.ws("outputs").rglob("*.mp4"))
    pdata = yaml.safe_load((cfg.workspace / "project.yaml").read_text(encoding="utf-8"))
    kinds = {}
    for a in assets:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    return {"name": name, "project": pdata, "mode": cfg.mode,
            "settings": {k: cfg.data.get(k) for k in ("analysis", "director", "render", "longform", "source")},
            "stats": {"assets": len(assets), "kinds": kinds,
                      "audio_done": sum(a["analyzed_audio"] for a in assets),
                      "vision_done": sum(a["analyzed_vision"] for a in assets),
                      "errors": sum(1 for a in assets if a["error"]),
                      "moments": len(cat.moments()), "plans": len(plans), "outputs": len(outputs),
                      "cities": sorted({a["city"] for a in assets if a["city"]})},
            "job": JOBS[name].view() if name in JOBS else None}


@app.put("/api/projects/{name}/settings")
def save_settings(name: str, body: dict = Body(...)):
    pfile = proots() / name / "project.yaml"
    pdata = yaml.safe_load(pfile.read_text(encoding="utf-8")) or {}
    pdata = config_mod._merge(pdata, body)
    pfile.write_text(yaml.safe_dump(pdata, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True}


# ================================================================ jobs api
STEPS = {
    "ingest": ["ingest"], "analyze": ["analyze"], "direct": ["direct"], "direct_fast": ["direct", "--no-llm"],
    "longform": ["longform"], "render": ["render"], "render_force": ["render", "--force"],
}


@app.post("/api/projects/{name}/jobs")
def start_job(name: str, body: dict = Body(...)):
    pcfg(name)
    if name in JOBS and JOBS[name].status == "running":
        raise HTTPException(409, "bu projede çalışan bir iş var")
    step = body.get("step")
    if step not in STEPS:
        raise HTTPException(400, "bilinmeyen adım")
    cmd = list(STEPS[step])
    for pid in body.get("plans") or []:
        cmd += ["--plan", str(pid)]
    if body.get("limit"):
        cmd += ["--limit", str(int(body["limit"]))]
    for aid in body.get("ids") or []:
        cmd += ["--id", str(aid)]
    JOBS[name] = Job(name, cmd, body.get("label") or step)
    return JOBS[name].view()


@app.get("/api/projects/{name}/job")
def job(name: str):
    return JOBS[name].view() if name in JOBS else None


@app.post("/api/projects/{name}/job/stop")
def stop_job(name: str):
    if name in JOBS:
        JOBS[name].stop()
    return {"ok": True}


# ================================================================ assets
@app.get("/api/projects/{name}/assets")
def assets(name: str):
    cat = pcat(name)
    out = []
    for a in cat.assets():
        v = a.get("vision") or {}
        tr = a.get("transcript") or {}
        out.append({"id": a["id"], "kind": a["kind"], "city": a["city"], "place": a["place"],
                    "taken_at": a["taken_at"], "duration": a["duration"],
                    "audio": bool(a["analyzed_audio"]), "vision": bool(a["analyzed_vision"]), "error": a["error"],
                    "summary": v.get("summary"), "categories": v.get("categories") or [],
                    "humor": v.get("humor_score"), "hook": v.get("hook_score"), "aesthetic": v.get("aesthetic_score"),
                    "transcript": tr.get("text"), "lang": tr.get("language"), "lang_prob": tr.get("lang_prob"),
                    "events": sorted({e["label"] for e in a.get("audio_events") or [] if e["label"] != "speech"})})
    return out


@app.get("/api/projects/{name}/assets/{aid}/thumb")
def thumb(name: str, aid: str):
    cfg = pcfg(name)
    cache = cfg.ws("cache", "thumbs") / f"{aid}.jpg"
    if not cache.exists():
        a = Catalog(cfg.workspace / "catalog.db").asset(aid)
        if not a:
            raise HTTPException(404)
        try:
            if a.get("photo_path"):
                media.load_image(Path(a["photo_path"]), 420).save(cache, quality=80)
            else:
                media.extract_frame(Path(a["video_path"]), min(1.0, (a["duration"] or 2) / 2), cache, 420)
        except Exception:
            raise HTTPException(404)
    return FileResponse(cache, headers={"Cache-Control": "max-age=86400"})


@app.get("/api/projects/{name}/assets/{aid}/media")
def asset_media(name: str, aid: str):
    a = pcat(name).asset(aid)
    if not a:
        raise HTTPException(404)
    p = a.get("video_path") or a.get("photo_path")
    if not p or not Path(p).exists():
        raise HTTPException(404)
    if Path(p).suffix.lower() in (".heic", ".heif"):
        return thumb(name, aid)
    return FileResponse(p)


# ================================================================ plans
def _plan_path(name: str, pid: str) -> Path:
    cfg = pcfg(name)
    hits = list(cfg.ws("plans").glob(f"*{pid}.json"))
    if not hits:
        raise HTTPException(404)
    return hits[0]


def _out_for(cfg, plan_path: Path, fmt: str) -> Path:
    return cfg.ws("outputs") / fmt / f"{plan_path.stem}.mp4"


@app.get("/api/projects/{name}/plans")
def plans(name: str):
    cfg = pcfg(name)
    out = []
    for p in sorted(cfg.ws("plans").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        segs = [s for s in d.get("segments", []) if s.get("enabled", True)]
        mp4 = _out_for(cfg, p, d.get("format", "x"))
        out.append({"id": d["id"], "file": p.stem, "format": d.get("format"), "title": d.get("title"),
                    "hook_text": d.get("hook_text"), "loc": d.get("loc"), "duration": d.get("duration"),
                    "segments": len(segs), "first_asset": next((s.get("asset_id") for s in segs if s.get("asset_id")),
                                                               None),
                    "rendered": mp4.exists(), "stale": mp4.exists() and p.stat().st_mtime > mp4.stat().st_mtime,
                    "video": f"/files/{name}/outputs/{d.get('format')}/{p.stem}.mp4" if mp4.exists() else None})
    return out


@app.get("/api/projects/{name}/plans/{pid}")
def plan(name: str, pid: str):
    return json.loads(_plan_path(name, pid).read_text(encoding="utf-8"))


@app.put("/api/projects/{name}/plans/{pid}")
def save_plan(name: str, pid: str, body: dict = Body(...)):
    p = _plan_path(name, pid)
    d = json.loads(p.read_text(encoding="utf-8"))
    for k in ("title", "hook_text", "outro_text", "music_mood", "captions", "youtube", "chapters", "title_options"):
        if k in body:
            d[k] = body[k]
    if "segments" in body:  # only editable fields per segment
        for s, new in zip(d["segments"], body["segments"]):
            for k in ("text", "enabled", "in", "out", "keep_audio"):
                if k in new:
                    s[k] = new[k]
    if d.get("format") == "longform":
        from .longform import refresh
        refresh(d)
    else:
        d["duration"] = round(sum(s["dur"] for s in d["segments"] if s.get("enabled", True)), 2)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


@app.delete("/api/projects/{name}/plans/{pid}")
def delete_plan(name: str, pid: str):
    p = _plan_path(name, pid)
    trash = pcfg(name).ws("plans_trash")
    p.rename(trash / p.name)  # recoverable
    return {"ok": True}


@app.get("/api/projects/{name}/plans/{pid}/export")
def export_plan(name: str, pid: str, kind: str = "xml"):
    from .longform import export_xml, make_srt
    cfg = pcfg(name)
    p = _plan_path(name, pid)
    d = json.loads(p.read_text(encoding="utf-8"))
    out = cfg.ws("exports") / p.stem
    if kind == "srt":
        f = out.with_suffix(".srt")
        f.write_text(make_srt(d, Catalog(cfg.workspace / "catalog.db")), encoding="utf-8")
    else:
        f = export_xml(d, out.with_suffix(".xml"), cfg["render"]["fps"])
    return FileResponse(f, filename=f.name)


# ================================================================ outputs / files
@app.get("/api/projects/{name}/outputs")
def outputs(name: str):
    cfg = pcfg(name)
    out = []
    for mp4 in sorted(cfg.ws("outputs").rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        rel = mp4.relative_to(cfg.workspace).as_posix()
        txt = mp4.with_suffix(".txt")
        extra = [f.name for f in (mp4.with_suffix(".srt"), mp4.with_suffix(".xml")) if f.exists()]
        out.append({"file": mp4.stem, "format": mp4.parent.name, "video": f"/files/{name}/{rel}",
                    "poster": f"/files/{name}/{mp4.with_suffix('.jpg').relative_to(cfg.workspace).as_posix()}"
                    if mp4.with_suffix(".jpg").exists() else None,
                    "captions": txt.read_text(encoding="utf-8") if txt.exists() else "",
                    "extras": [f"/files/{name}/{(mp4.parent / e).relative_to(cfg.workspace).as_posix()}" for e in extra],
                    "size_mb": round(mp4.stat().st_size / 1e6, 1)})
    return out


@app.get("/files/{name}/{rel:path}")
def files(name: str, rel: str):
    return FileResponse(safe_file(name, rel))


@app.middleware("http")
async def _sysexit(request, call_next):
    """Library code signals user errors with SystemExit (it is not an Exception subclass)."""
    try:
        return await call_next(request)
    except SystemExit as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


def serve(cfg_path: str | None = None, host: str = "127.0.0.1", port: int = 8765):
    global CFG_PATH
    CFG_PATH = cfg_path
    import uvicorn
    print(f"🌐 MegaTravelOS arayüzü: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
