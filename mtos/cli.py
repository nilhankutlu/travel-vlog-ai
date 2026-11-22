"""mtos — MegaTravelOS command line.

  mtos serve                       # web arayüzü → http://localhost:8765
  mtos -p <proje> ingest           # Photos / klasörden kataloğa al
  mtos -p <proje> analyze          # ses + görüntü analizi, 'moment' çıkarımı
  mtos -p <proje> direct           # Shorts: yüzlerce konsept + senaryo + caption
  mtos -p <proje> longform         # Long-form: kronolojik YouTube kurgusu (bölümler, cold open)
  mtos -p <proje> render           # planları mp4'e çevir
  mtos -p <proje> export --plan X  # long-form: DaVinci/Premiere XML + SRT (render etmeden)
  mtos -p <proje> status | estimate
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
    ap.add_argument("-p", "--project", default=None, help="proje adı (workspace/projects/<ad>)")
    ap.add_argument("--backend", choices=["ollama", "anthropic"], help="analysis.backend'i ez")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest")
    an = sub.add_parser("analyze")
    an.add_argument("--limit", type=int)
    an.add_argument("--redo", action="store_true")
    an.add_argument("--only", choices=["photo", "video", "live"])
    an.add_argument("--id", action="append", help="sadece bu asset id(ler)")
    dr = sub.add_parser("direct")
    dr.add_argument("--no-llm", action="store_true")
    dr.add_argument("--max", type=int, default=None, help="en fazla kaç konsept")
    dr.add_argument("--id", action="append", help="sadece bu asset id(ler)den konsept üret")
    lf = sub.add_parser("longform")
    lf.add_argument("--no-llm", action="store_true")
    rd = sub.add_parser("render")
    rd.add_argument("--limit", type=int)
    rd.add_argument("--plan", action="append", help="sadece bu plan id(ler)")
    rd.add_argument("--force", action="store_true")
    ex = sub.add_parser("export")
    ex.add_argument("--plan", required=True)
    al = sub.add_parser("all")
    al.add_argument("--limit", type=int)
    sub.add_parser("status")
    sub.add_parser("estimate")
    sub.add_parser("gallery")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .server import serve
        serve(args.config, args.host, args.port)
        return

    cfg = config_mod.load(args.config, args.project)
    if args.backend:
        cfg.data["analysis"]["backend"] = args.backend
    cat = Catalog(cfg.workspace / "catalog.db")

    if args.cmd in ("ingest", "all"):
        from .ingest import ingest
        print(f"✅ {ingest(cfg, cat)} medya kataloğa eklendi.")
    if args.cmd in ("analyze", "all"):
        from .analyze import Analyzer
        Analyzer(cfg, cat).run(only=getattr(args, "only", None), redo=getattr(args, "redo", False),
                               limit=getattr(args, "limit", None), ids=getattr(args, "id", None))
    if args.cmd == "direct" or (args.cmd == "all" and cfg.mode == "shorts"):
        from .director import Director
        plans = Director(cfg, cat, use_llm=not getattr(args, "no_llm", False),
                         ids=getattr(args, "id", None)).run(getattr(args, "max", None))
        print(f"🎬 {len(plans)} video planı yazıldı → {cfg.ws('plans')}")
    if args.cmd == "longform" or (args.cmd == "all" and cfg.mode == "longform"):
        from .longform import run as lf_run
        lf_run(cfg, cat, use_llm=not getattr(args, "no_llm", False))
    if args.cmd in ("render", "all"):
        from .render import render_all
        render_all(cfg, cat, limit=getattr(args, "limit", None), plan_id=getattr(args, "plan", None),
                   force=getattr(args, "force", False))
    if args.cmd in ("render", "all", "gallery"):
        from .gallery import build
        print(f"🖼️  İnceleme sayfası: {build(cfg)}")
    if args.cmd == "export":
        from .longform import export_xml, make_srt
        p = next(cfg.ws("plans").glob(f"*{args.plan}*.json"))
        plan = json.loads(p.read_text(encoding="utf-8"))
        out = cfg.ws("exports") / p.stem
        export_xml(plan, out.with_suffix(".xml"), cfg["render"]["fps"])
        out.with_suffix(".srt").write_text(make_srt(plan, cat), encoding="utf-8")
        print(f"📤 {out.with_suffix('.xml')}\n📤 {out.with_suffix('.srt')}")
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
