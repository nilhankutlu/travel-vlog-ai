"""SQLite catalog: one row per asset (photo / video / live photo), plus the
analysis results and the 'moments' (time ranges worth using in an edit)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,           -- stable id (Photos uuid or file stem)
    kind TEXT NOT NULL,            -- photo | video | live
    photo_path TEXT,               -- still image (photo / live)
    video_path TEXT,               -- movie (video / live motion part)
    album TEXT,
    taken_at TEXT,                 -- ISO datetime
    lat REAL, lon REAL,
    place TEXT, city TEXT, country TEXT,
    width INTEGER, height INTEGER,
    duration REAL,
    has_audio INTEGER DEFAULT 0,
    apple_labels TEXT,             -- json list (Photos ML labels / persons)
    meta TEXT,                     -- json, anything else
    transcript TEXT,               -- json {text, language, segments:[{start,end,text,words}]}
    audio_events TEXT,             -- json [{label,start,end,score}]
    vision TEXT,                   -- json result of the vision model
    analyzed_audio INTEGER DEFAULT 0,
    analyzed_vision INTEGER DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS moments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    start REAL, end REAL,          -- seconds inside the video (0,0 for photos)
    kind TEXT,                     -- funny | speech | scenic | action | food | people | hook | photo
    score REAL,
    text TEXT,                     -- description / quote
    tags TEXT,                     -- json list
    UNIQUE(asset_id, start, end, kind)
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT DEFAULT CURRENT_TIMESTAMP,
    backend TEXT, model TEXT, purpose TEXT,
    input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL
);
"""

JSON_COLS = {"apple_labels", "meta", "transcript", "audio_events", "vision", "tags"}


class Catalog:
    def __init__(self, db_path: Path):
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------- assets
    def upsert_asset(self, a: dict):
        a = {k: (json.dumps(v, ensure_ascii=False) if k in JSON_COLS and v is not None else v)
             for k, v in a.items()}
        cols = ", ".join(a)
        ph = ", ".join("?" for _ in a)
        upd = ", ".join(f"{k}=excluded.{k}" for k in a if k != "id")
        self.db.execute(
            f"INSERT INTO assets ({cols}) VALUES ({ph}) ON CONFLICT(id) DO UPDATE SET {upd}",
            list(a.values()))
        self.db.commit()

    def update(self, asset_id: str, **fields):
        fields = {k: (json.dumps(v, ensure_ascii=False) if k in JSON_COLS and v is not None else v)
                  for k, v in fields.items()}
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE assets SET {sets} WHERE id=?", [*fields.values(), asset_id])
        self.db.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        for k in JSON_COLS & d.keys():
            if d[k]:
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        return d

    def assets(self, where: str = "1=1", args=()) -> list[dict]:
        rows = self.db.execute(f"SELECT * FROM assets WHERE {where} ORDER BY taken_at, id", args)
        return [self._row(r) for r in rows]

    def asset(self, asset_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        return self._row(r) if r else None

    # ---------- moments
    def replace_moments(self, asset_id: str, moments: list[dict]):
        self.db.execute("DELETE FROM moments WHERE asset_id=?", (asset_id,))
        for m in moments:
            self.db.execute(
                "INSERT OR IGNORE INTO moments (asset_id,start,end,kind,score,text,tags) VALUES (?,?,?,?,?,?,?)",
                (asset_id, m.get("start", 0), m.get("end", 0), m.get("kind"), m.get("score", 0),
                 m.get("text"), json.dumps(m.get("tags", []), ensure_ascii=False)))
        self.db.commit()

    def moments(self, where: str = "1=1", args=()) -> list[dict]:
        rows = self.db.execute(
            f"SELECT m.*, a.kind AS asset_kind, a.city, a.country, a.place, a.taken_at "
            f"FROM moments m JOIN assets a ON a.id=m.asset_id WHERE {where} ORDER BY m.score DESC", args)
        return [self._row(r) for r in rows]

    # ---------- usage / cost
    def log_usage(self, backend, model, purpose, inp, out, cost):
        self.db.execute(
            "INSERT INTO usage (backend,model,purpose,input_tokens,output_tokens,cost_usd) VALUES (?,?,?,?,?,?)",
            (backend, model, purpose, inp, out, cost))
        self.db.commit()

    def usage_summary(self):
        return [dict(r) for r in self.db.execute(
            "SELECT backend, model, purpose, COUNT(*) calls, SUM(input_tokens) inp, "
            "SUM(output_tokens) out, ROUND(SUM(cost_usd),4) cost FROM usage GROUP BY 1,2,3")]
