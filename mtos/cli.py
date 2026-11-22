"""mtos — MegaTravelOS command line.

  mtos ingest                 # Photos / klasörden kataloğa al
  mtos analyze [--limit N]    # ses + görüntü analizi, 'moment' çıkarımı
  mtos direct                 # yüzlerce video konsepti + senaryo + caption
  mtos render [--limit N]     # planları mp4'e çevir
  mtos all                    # hepsi sırayla
  mtos status                 # katalog / maliyet özeti
  mtos estimate               # Claude API ile tüm arşivi analiz etmenin tahmini maliyeti
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from . import config as config_mod
from .catalog import Catalog


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mtos", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=None, help="config.yaml yolu")
    ap.add_argument("--backend", choices=["ollama", "anthropic"], help="analysis.backend'i ez")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest")
    an = sub.add_parser("analyze")
    an.add_argument("--limit", type=int)
    an.add_argument("--redo", action="store_true")
    an.add_argument("--only", choices=["photo", "video", "live"])
    dr = sub.add_parser("direct")
    dr.add_argument("--no-llm", action="store_true")
    dr.add_argument("--max", type=int, default=None, help="en fazla kaç konsept")
    rd = sub.add_parser("render")
    rd.add_argument("--limit", type=int)
    rd.add_argument("--plan", help="sadece bu plan id")
    rd.add_argument("--force", action="store_true")
    al = sub.add_parser("all")
    al.add_argument("--limit", type=int)
    sub.add_parser("status")
    sub.add_parser("estimate")
    sub.add_parser("gallery")
    args = ap.parse_args(argv)

    cfg = config_mod.load(args.config)
    if args.backend:
        cfg.data["analysis"]["backend"] = args.backend
    cat = Catalog(cfg.workspace / "catalog.db")

    if args.cmd in ("ingest", "all"):
        from .ingest import ingest
        print(f"✅ {ingest(cfg, cat)} medya kataloğa eklendi.")
    if args.cmd in ("analyze", "all"):
        from .analyze import Analyzer
        Analyzer(cfg, cat).run(only=getattr(args, "only", None), redo=getattr(args, "redo", False),
                               limit=getattr(args, "limit", None))
    if args.cmd in ("direct", "all"):
        from .director import Director
        plans = Director(cfg, cat, use_llm=not getattr(args, "no_llm", False)).run(getattr(args, "max", None))
        print(f"🎬 {len(plans)} video planı yazıldı → {cfg.ws('plans')}")
    if args.cmd in ("render", "all"):
        from .render import render_all
        render_all(cfg, cat, limit=getattr(args, "limit", None), plan_id=getattr(args, "plan", None),
                   force=getattr(args, "force", False))
    if args.cmd in ("render", "all", "gallery"):
        from .gallery import build
        print(f"🖼️  İnceleme sayfası: {build(cfg)}")
    if args.cmd == "status":
        assets = cat.assets()
        print("Medya:", dict(Counter(a["kind"] for a in assets)))
        print("Ses analizi:", sum(a["analyzed_audio"] for a in assets), "/", len(assets),
              "| Görüntü analizi:", sum(a["analyzed_vision"] for a in assets), "/", len(assets))
        print("Şehirler:", dict(Counter(a["city"] or a["place"] or "?" for a in assets).most_common(15)))
        ms = cat.moments()
        print("Moment:", len(ms), dict(Counter(m["kind"] for m in ms)))
        errs = [a for a in assets if a["error"]]
        if errs:
            print(f"Hatalı {len(errs)}:", [(a["id"], a["error"][:80]) for a in errs[:5]])
        print(json.dumps(cat.usage_summary(), indent=1, ensure_ascii=False))
    if args.cmd == "estimate":
        from .estimate import estimate
        estimate(cfg, cat)


if __name__ == "__main__":
    main()
