"""Config loading. Every path is resolved relative to the config file so the
whole project can be copied to another machine and run unchanged."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))


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

    def __getitem__(self, key):
        return self.data[key]

    def path(self, p: str | None) -> Path | None:
        if p is None:
            return None
        p = Path(os.path.expanduser(p))
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    @property
    def workspace(self) -> Path:
        ws = self.path(self.data["workspace"])
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def ws(self, *parts: str) -> Path:
        p = self.workspace.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p


def load(path: str | None = None) -> Config:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if cfg_path.exists():
        user = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        base = cfg_path.resolve().parent
    else:
        user, base = {}, ROOT
    return Config(_merge(DEFAULTS, user), base)
