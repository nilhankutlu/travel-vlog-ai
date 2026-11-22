"""Config loading. Every path is resolved relative to the config file so the
whole project can be copied to another machine and run unchanged.

Projects: each project lives in <workspace>/projects/<name>/ with its own
catalog, plans and outputs, and a project.yaml that overrides config.yaml
(mode: shorts | longform, source folder / albums, render size...).
Models are shared in <workspace>/models."""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))

MODE_PRESETS = {
    "shorts": {"render": {"width": 1080, "height": 1920}},
    "longform": {
        "render": {"width": 1920, "height": 1080, "burn_subtitles": False, "music_volume": 0.15},
        "source": {"copy_media": False},
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    data: dict
    base_dir: Path
    project: str | None = None

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def path(self, p: str | None) -> Path | None:
        if p is None:
            return None
        p = Path(os.path.expanduser(str(p)))
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    @property
    def workspace(self) -> Path:
        ws = self.path(self.data["workspace"])
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    @property
    def mode(self) -> str:
        return self.data.get("mode", "shorts")

    @property
    def models_dir(self) -> Path:
        p = self.path(self.data.get("models_dir") or str(self.workspace / "models"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ws(self, *parts: str) -> Path:
        p = self.workspace.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p


def _read_base(path: str | None) -> tuple[dict, Path]:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if cfg_path.exists():
        user = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return _merge(DEFAULTS, user), cfg_path.resolve().parent
    return copy.deepcopy(DEFAULTS), ROOT


def projects_root(path: str | None = None) -> Path:
    base = load(path)
    p = base.workspace / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", name.strip().lower(), flags=re.UNICODE).strip("-")
    return s or "proje"


def load(path: str | None = None, project: str | None = None) -> Config:
    data, base = _read_base(path)
    if not project:
        return Config(data, base)
    root = Config(data, base).workspace
    pdir = root / "projects" / project
    pfile = pdir / "project.yaml"
    if not pfile.exists():
        raise SystemExit(f"Proje bulunamadı: {project}")
    pdata = yaml.safe_load(pfile.read_text(encoding="utf-8")) or {}
    mode = pdata.get("mode", "shorts")
    data = _merge(_merge(data, MODE_PRESETS.get(mode, {})), pdata)
    data["workspace"] = str(pdir)
    data["models_dir"] = str(root / "models")
    data["mode"] = mode
    # relative source paths in project.yaml are relative to the project folder
    return Config(data, pdir, project)


def save_project(cfg_path: str | None, name: str, pdata: dict) -> Path:
    pdir = projects_root(cfg_path) / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.yaml").write_text(yaml.safe_dump(pdata, allow_unicode=True, sort_keys=False),
                                       encoding="utf-8")
    return pdir
