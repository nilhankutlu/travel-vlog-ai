"""Bring media into the catalog, either from the macOS Photos library
(shared albums, Live Photos, places, Apple labels) or from any plain folder."""
from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

from . import media
from .catalog import Catalog
from .config import Config


# ---------------------------------------------------------------- geo
def _geocoder():
    try:
        import reverse_geocoder as rg  # optional, offline
        return rg
    except ImportError:
        return None


def fill_places(cat: Catalog):
    """For assets with GPS but no city (folder mode), reverse-geocode offline."""
    todo = [a for a in cat.assets("lat IS NOT NULL AND city IS NULL")]
    if not todo:
        return
    rg = _geocoder()
    if rg is None:
        for a in todo:  # coarse bucket so location-based concepts still work
            cat.update(a["id"], city=f"{a['lat']:.1f},{a['lon']:.1f}")
        print("ℹ️  reverse_geocoder kurulu değil; konumlar koordinat kümesi olarak gruplanacak "
              "(uv pip install '.[geo]' ile şehir isimleri gelir).")
        return
    res = rg.search([(a["lat"], a["lon"]) for a in todo], mode=1)
    for a, r in zip(todo, res):
        cc = r.get("cc")
        # city = province/state level (Tokyo, Istanbul, Incheon); city-states collapse to the country
        city = CITY_STATES.get(cc) or r.get("admin1") or r.get("name")
        cat.update(a["id"], city=city, country=COUNTRIES.get(cc, cc), place=a.get("place") or r.get("name"))


CITY_STATES = {"HK": "Hong Kong", "SG": "Singapore", "MO": "Macau", "MC": "Monaco", "VA": "Vatican"}
COUNTRIES = {
    "HK": "Hong Kong", "KR": "South Korea", "JP": "Japan", "CN": "China", "TW": "Taiwan", "TH": "Thailand",
    "VN": "Vietnam", "SG": "Singapore", "MY": "Malaysia", "ID": "Indonesia", "PH": "Philippines",
    "TR": "Türkiye", "GR": "Greece", "IT": "Italy", "FR": "France", "ES": "Spain", "PT": "Portugal",
    "DE": "Germany", "NL": "Netherlands", "GB": "United Kingdom", "US": "United States", "AE": "UAE",
    "EG": "Egypt", "MA": "Morocco", "CH": "Switzerland", "AT": "Austria", "CZ": "Czechia", "HU": "Hungary",
    "MO": "Macau", "IN": "India", "GE": "Georgia", "MX": "Mexico", "BR": "Brazil", "AU": "Australia",
}


# ---------------------------------------------------------------- folder
def ingest_folder(cfg: Config, cat: Catalog) -> int:
    folder = cfg.path(cfg["source"]["folder"])
    if not folder or not folder.is_dir():
        raise SystemExit(f"Klasör bulunamadı: {folder}")
    groups: dict[Path, dict[str, list[Path]]] = defaultdict(lambda: {"photo": [], "video": []})
    for p in sorted(folder.rglob("*")):
        if p.name.startswith(".") or not p.is_file():
            continue
        ext = p.suffix.lower()
        key = p.with_suffix("")
        if ext in media.PHOTO_EXT:
            groups[key]["photo"].append(p)
        elif ext in media.VIDEO_EXT:
            groups[key]["video"].append(p)

    dest = cfg.ws("media") if cfg["source"].get("copy_media") else None
    n = 0
    for key, g in tqdm(groups.items(), desc="Taranıyor"):
        photo = g["photo"][0] if g["photo"] else None
        video = g["video"][0] if g["video"] else None
        try:
            vinfo = media.video_info(video) if video else {}
            pinfo = media.photo_info(photo) if photo else {}
        except Exception as e:  # unreadable / still in iCloud
            print(f"⚠️  {key.name}: okunamadı ({e.__class__.__name__}) — atlandı")
            continue
        if photo and video and vinfo.get("duration", 99) <= 4.5:
            kind = "live"
        elif video:
            kind = "video"
            if photo:  # same stem but a long video: register the photo separately
                _add(cat, f"{key.name}_still", "photo", photo, None, pinfo, {}, dest)
                n += 1
            photo = None
        else:
            kind = "photo"
        _add(cat, key.name, kind, photo, video, pinfo, vinfo, dest)
        n += 1
    fill_places(cat)
    return n


def _add(cat, aid, kind, photo, video, pinfo, vinfo, dest):
    if dest:
        photo = Path(shutil.copy2(photo, dest)) if photo else None
        video = Path(shutil.copy2(video, dest)) if video else None
    info = {**pinfo, **{k: v for k, v in vinfo.items() if v not in (None, 0)}}
    existing = cat.asset(aid) or {}
    cat.upsert_asset({
        "id": aid, "kind": kind,
        "photo_path": str(photo) if photo else None,
        "video_path": str(video) if video else None,
        "taken_at": info.get("taken_at") or existing.get("taken_at"),
        "lat": info.get("lat"), "lon": info.get("lon"),
        "width": info.get("width"), "height": info.get("height"),
        "duration": vinfo.get("duration") or 0,
        "has_audio": int(bool(vinfo.get("has_audio"))),
        "meta": {"content_id": info.get("content_id")},
    })


# ---------------------------------------------------------------- Photos.app
def ingest_photos(cfg: Config, cat: Catalog) -> int:
    try:
        import osxphotos
        from osxphotos.photoexporter import ExportOptions, PhotoExporter
    except ImportError:
        raise SystemExit("osxphotos yok: uv pip install '.[photos]'  (sadece macOS)")

    pcfg = cfg["source"]["photos"]
    db = osxphotos.PhotosDB(dbfile=pcfg.get("library")) if pcfg.get("library") else osxphotos.PhotosDB()

    wanted_shared = set(pcfg.get("shared_albums") or [])
    wanted_albums = set(pcfg.get("albums") or [])
    selected: dict[str, tuple] = {}

    shared = db.album_info_shared
    print(f"📚 Shared album'ler: {', '.join(a.title for a in shared) or '(yok)'}")
    for alb in shared:
        if not wanted_shared or alb.title in wanted_shared:
            for ph in alb.photos:
                selected[ph.uuid] = (ph, alb.title)
    if wanted_albums:
        for alb in db.album_info:
            if alb.title in wanted_albums:
                for ph in alb.photos:
                    selected.setdefault(ph.uuid, (ph, alb.title))
    if pcfg.get("include_own_library"):
        for ph in db.photos():
            selected.setdefault(ph.uuid, (ph, None))

    out_dir = cfg.ws("media")
    n = 0
    for uuid, (ph, album) in tqdm(selected.items(), desc="Photos'tan alınıyor"):
        photo_path = video_path = None
        if ph.ismovie:
            video_path = ph.path
        else:
            photo_path = ph.path
            if ph.live_photo:
                video_path = ph.path_live_photo
        if (ph.ismovie and not video_path) or (not ph.ismovie and not photo_path) or \
           (ph.live_photo and not video_path):
            # Not on disk (iCloud optimized storage / shared stream not cached): export via Photos
            try:
                res = PhotoExporter(ph).export(
                    str(out_dir), options=ExportOptions(download_missing=True, live_photo=True, overwrite=False))
                files = [Path(f) for f in res.exported + getattr(res, "skipped", [])]
                for f in files:
                    if f.suffix.lower() in media.VIDEO_EXT:
                        video_path = video_path or str(f)
                    elif f.suffix.lower() in media.PHOTO_EXT:
                        photo_path = photo_path or str(f)
            except Exception as e:
                print(f"⚠️  {ph.original_filename}: indirilemedi ({e})")
                continue
        kind = "video" if ph.ismovie else "live" if (ph.live_photo and video_path) else "photo"
        vinfo = {}
        if video_path:
            try:
                vinfo = media.video_info(Path(video_path))
            except Exception:
                pass
        addr = ph.place.address if ph.place else None
        loc = ph.location or (None, None)
        labels = list(ph.labels or []) + [f"person:{p}" for p in (ph.persons or []) if p != "_UNKNOWN_"]
        cat.upsert_asset({
            "id": uuid, "kind": kind,
            "photo_path": photo_path, "video_path": video_path,
            "album": album,
            "taken_at": ph.date.isoformat() if ph.date else None,
            "lat": loc[0], "lon": loc[1],
            "place": ph.place.name if ph.place else None,
            "city": getattr(addr, "city", None) if addr else None,
            "country": getattr(addr, "country", None) if addr else None,
            "width": ph.width, "height": ph.height,
            "duration": vinfo.get("duration", 0),
            "has_audio": int(bool(vinfo.get("has_audio"))),
            "apple_labels": labels,
            "meta": {"filename": ph.original_filename, "favorite": ph.favorite,
                     "title": ph.title, "description": ph.description,
                     "comments": [c.text for c in (getattr(ph, "comments", None) or [])]},
        })
        n += 1
    fill_places(cat)
    return n


def ingest(cfg: Config, cat: Catalog) -> int:
    return ingest_photos(cfg, cat) if cfg["source"]["type"] == "photos" else ingest_folder(cfg, cat)
