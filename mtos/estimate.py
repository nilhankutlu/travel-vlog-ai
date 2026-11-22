"""Estimate what analysing the whole archive with the Claude API would cost,
from the catalog's actual asset mix (or from measured usage, if a pilot ran)."""
from __future__ import annotations

from collections import Counter

from .llm import PRICES


def estimate(cfg, cat, n_assets: int | None = None):
    assets = cat.assets()
    mix = Counter(a["kind"] for a in assets)
    total = n_assets or len(assets)
    px = cfg["analysis"]["max_image_px"]
    # image tokens ≈ (w*h)/750 ; a video contact sheet is ~max_px x (2/3*max_px)
    img_tok = {"photo": px * px * 0.75 / 750, "live": px * px * 0.75 / 750, "video": px * px * 0.67 / 750}
    text_in, out_tok = 900, 450  # prompt + transcript, JSON answer
    measured = [u for u in cat.usage_summary() if u["backend"] == "anthropic" and u["purpose"] == "vision"]

    print(f"Katalogdaki karışım: {dict(mix)}  →  {total} medya için tahmin\n")
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"):
        pin, pout = PRICES[model]
        cost = 0.0
        for kind, cnt in mix.items():
            share = cnt / max(1, len(assets))
            cost += total * share * ((img_tok[kind] + text_in) * pin + out_tok * pout) / 1e6
        print(f"  Görüntü analizi {model:<18} ≈ ${cost:,.2f}   (Batch API ile ≈ ${cost / 2:,.2f})")
    # director: one call per concept, ~1.5k in / 700 out
    concepts = max(50, total // 3)
    for model in ("claude-haiku-5-5", "claude-sonnet-5-5"):
        pin, pout = PRICES[model]
        print(f"  Senaryo yazımı  {model:<18} ≈ ${concepts * (1500 * pin + 700 * pout) / 1e6:,.2f}"
              f"   (~{concepts} konsept)")
    if measured:
        m = measured[0]
        print(f"\n  Ölçülen: {m['calls']} çağrı, ${m['cost']}  → medya başı ${m['cost'] / m['calls']:.4f}")
    print("\n  Ses (Whisper + YAMNet) her durumda lokal ve ücretsiz.")
