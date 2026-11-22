"""Speech transcription (faster-whisper, word timestamps) and audio-event
detection (YAMNet: laughter, screaming, applause, music...)."""
from __future__ import annotations

import urllib.request
import wave
import zipfile
from pathlib import Path

import numpy as np

YAMNET_URL = ("https://storage.googleapis.com/mediapipe-models/audio_classifier/"
              "yamnet/float32/latest/yamnet.tflite")

# AudioSet labels we care about -> our event name
EVENT_MAP = {
    "Laughter": "laughter", "Giggle": "laughter", "Belly laugh": "laughter",
    "Chuckle, chortle": "laughter", "Snicker": "laughter", "Baby laughter": "laughter",
    "Screaming": "scream", "Shout": "shout", "Yell": "shout", "Children shouting": "shout",
    "Applause": "applause", "Cheering": "cheering", "Crowd": "crowd",
    "Music": "music", "Singing": "singing",
    "Gasp": "gasp", "Whoop": "cheering", "Clapping": "applause",
    "Vehicle horn, car horn, honking": "horn", "Train": "train", "Fireworks": "fireworks",
    "Ocean": "waves", "Waves, surf": "waves", "Bird": "birds", "Dog": "animal", "Cat": "animal",
    "Speech": "speech",
}


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


# ---------------------------------------------------------------- whisper
# Phrases Whisper invents on music / noise / foreign speech (YouTube outro training data)
HALLUCINATIONS = [
    "izlediğiniz için teşekkür", "abone olmayı unutmayın", "altyazı m.k.", "thanks for watching",
    "thank you for watching", "subscribe to my channel", "please subscribe", "like and subscribe",
    "sous-titres réalisés", "untertitel im auftrag", "字幕", "請不吝點贊", "訂閱", "ご視聴ありがとう",
]


def _is_hallucination(text: str) -> bool:
    t = text.lower().strip()
    return not t or any(h in t for h in HALLUCINATIONS)


class Transcriber:
    def __init__(self, model: str, compute: str = "int8", language: str | None = None,
                 cache_dir: Path | None = None):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model, device="auto", compute_type=compute,
                                  download_root=str(cache_dir) if cache_dir else None)
        self.language = language

    def __call__(self, wav: Path) -> dict:
        # pass decoded samples (avoids faster-whisper's PyAV path and its version quirks)
        segs, info = self.model.transcribe(
            read_wav(wav), language=self.language, word_timestamps=True, vad_filter=True,
            beam_size=5, condition_on_previous_text=False)
        out = []
        for s in segs:
            if s.no_speech_prob > 0.7 and s.avg_logprob < -1.0:
                continue
            if _is_hallucination(s.text):
                continue
            out.append({
                "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                "words": [{"w": w.word, "s": round(w.start, 2), "e": round(w.end, 2)}
                          for w in (s.words or [])],
            })
        text = " ".join(s["text"] for s in out).strip()
        return {"language": info.language, "lang_prob": round(info.language_probability, 2),
                "text": text, "segments": out}


# ---------------------------------------------------------------- YAMNet
class EventDetector:
    def __init__(self, model_dir: Path):
        from ai_edge_litert.interpreter import Interpreter
        path = model_dir / "yamnet.tflite"
        if not path.exists():
            print("⬇️  YAMNet modeli indiriliyor (~4 MB)...")
            urllib.request.urlretrieve(YAMNET_URL, path)
        with zipfile.ZipFile(path) as z:  # labels are packed in the tflite metadata
            name = next(n for n in z.namelist() if n.endswith(".txt"))
            self.labels = z.read(name).decode().strip().splitlines()
        self.it = Interpreter(model_path=str(path))
        self.inp = self.it.get_input_details()[0]
        self.out = self.it.get_output_details()[0]
        self.win = int(np.prod(self.inp["shape"])) or 15600
        if list(self.inp["shape"]) != [self.win] and len(self.inp["shape"]) == 1:
            self.it.resize_tensor_input(self.inp["index"], [self.win])
        self.it.allocate_tensors()
        self.idx = {i: EVENT_MAP[l] for i, l in enumerate(self.labels) if l in EVENT_MAP}

    def __call__(self, wav: Path, hop: float = 0.48, thresh: float = 0.25) -> list[dict]:
        x = read_wav(wav)
        if len(x) < self.win:
            x = np.pad(x, (0, self.win - len(x)))
        step = int(16000 * hop)
        hits: list[dict] = []
        for start in range(0, len(x) - self.win + 1, step):
            chunk = x[start:start + self.win].reshape(self.inp["shape"]).astype(np.float32)
            self.it.set_tensor(self.inp["index"], chunk)
            self.it.invoke()
            scores = self.it.get_tensor(self.out["index"]).reshape(-1)
            t0 = start / 16000
            best: dict[str, float] = {}
            for i, ev in self.idx.items():
                if scores[i] >= thresh:
                    best[ev] = max(best.get(ev, 0), float(scores[i]))
            for ev, sc in best.items():
                hits.append({"label": ev, "start": round(t0, 2), "end": round(t0 + 0.975, 2), "score": round(sc, 2)})
        return _merge(hits)


def _merge(hits: list[dict], gap: float = 0.6) -> list[dict]:
    out: list[dict] = []
    for h in sorted(hits, key=lambda h: (h["label"], h["start"])):
        if out and out[-1]["label"] == h["label"] and h["start"] - out[-1]["end"] <= gap:
            out[-1]["end"] = max(out[-1]["end"], h["end"])
            out[-1]["score"] = max(out[-1]["score"], h["score"])
        else:
            out.append(dict(h))
    return sorted(out, key=lambda h: h["start"])


def loudness_peaks(wav: Path, top: int = 3) -> list[dict]:
    """Sudden loud moments (reactions, shouts) — cheap extra signal."""
    x = read_wav(wav)
    if len(x) < 16000:
        return []
    win = 8000
    rms = np.sqrt(np.convolve(x ** 2, np.ones(win) / win, mode="valid"))[::win // 2]
    if rms.max() < 0.05:
        return []
    base = np.median(rms) + 1e-4
    idx = np.argsort(rms)[::-1]
    peaks = []
    for i in idx:
        if rms[i] / base < 3 or len(peaks) >= top:
            break
        t = i * (win // 2) / 16000
        if all(abs(t - p["start"]) > 2 for p in peaks):
            peaks.append({"label": "loud", "start": round(max(t - 0.5, 0), 2), "end": round(t + 1.0, 2),
                          "score": round(float(min(rms[i] / base / 10, 1)), 2)})
    return peaks
