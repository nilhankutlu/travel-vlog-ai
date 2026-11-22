"""Pluggable model backends: local Ollama (free) or the Claude API.
Both return parsed JSON that matches a JSON schema, and log token usage."""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

from .catalog import Catalog
from .config import Config

# $ per 1M tokens (input, output) - Claude API first-party list prices
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def _strict(schema: dict) -> dict:
    """Make every object closed + fully required (needed by Claude structured outputs)."""
    s = json.loads(json.dumps(schema))

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "object" and "properties" in n:
                n.setdefault("additionalProperties", False)
                n["required"] = list(n["properties"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(s)
    return s


def _parse_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


class Backend:
    def __init__(self, cfg: Config, cat: Catalog):
        self.cfg, self.cat = cfg, cat
        self.kind = cfg["analysis"]["backend"]
        if self.kind == "ollama":
            import ollama
            o = cfg["analysis"]["ollama"]
            self.client = ollama.Client(host=o["host"])
            self.vision_model, self.text_model = o["vision_model"], o["text_model"]
        elif self.kind == "anthropic":
            import anthropic
            a = cfg["analysis"]["anthropic"]
            self.client = anthropic.Anthropic()
            self.vision_model, self.text_model = a["vision_model"], a["text_model"]
        else:
            raise ValueError(f"unknown backend {self.kind}")

    # ------------------------------------------------------------------
    def vision_json(self, images: list[Path], prompt: str, schema: dict, purpose="vision") -> dict:
        return self._call(self.vision_model, prompt, schema, images, purpose, max_tokens=2000)

    def text_json(self, prompt: str, schema: dict, system: str | None = None, purpose="text",
                  max_tokens: int = 8000) -> dict:
        return self._call(self.text_model, prompt, schema, [], purpose, system=system, max_tokens=max_tokens)

    # ------------------------------------------------------------------
    def _call(self, model, prompt, schema, images, purpose, system=None, max_tokens=4000):
        if self.kind == "ollama":
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msg = {"role": "user", "content": prompt}
            if images:
                msg["images"] = [str(p) for p in images]
            msgs.append(msg)
            r = self.client.chat(model=model, messages=msgs, format=schema,
                                 options={"temperature": 0.4, "num_ctx": 8192})
            self.cat.log_usage("ollama", model, purpose, r.get("prompt_eval_count") or 0,
                               r.get("eval_count") or 0, 0.0)
            return _parse_json(r["message"]["content"])

        # Claude API
        content = []
        for p in images:
            from PIL import Image
            buf = io.BytesIO()
            Image.open(p).convert("RGB").save(buf, "JPEG", quality=85)
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(buf.getvalue()).decode()}})
        content.append({"type": "text", "text": prompt})
        kwargs = dict(model=model, max_tokens=max_tokens,
                      messages=[{"role": "user", "content": content}],
                      output_config={"format": {"type": "json_schema", "schema": _strict(schema)},
                                     "effort": "low"})
        if system:
            kwargs["system"] = system
        r = self.client.messages.create(**kwargs)
        pin, pout = PRICES.get(model, (0, 0))
        u = r.usage
        self.cat.log_usage("anthropic", model, purpose, u.input_tokens, u.output_tokens,
                           (u.input_tokens * pin + u.output_tokens * pout) / 1e6)
        if r.stop_reason == "refusal":
            raise RuntimeError("model refused")
        text = next(b.text for b in r.content if b.type == "text")
        return _parse_json(text)
