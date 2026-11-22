# 🎬 Travel Vlog AI - Video Indexer & Automated Storyboard Studio

Seyahat videolarınızı (MP4, MOV, Insta360, GoPro vb.) otomatik analiz eden, **EXIF GPS** konumlarını haritaya döküp **Whisper AI** ile Türkçe konuşmaları metne çeviren ve **Google Gemini Vision AI** ile baştan sona eksiksiz **Travel Vlog Senaryosu, Türkçe Dış Ses (Voiceover) Metinleri ve Otomatik Kurgu Betiği** üreten yapay zeka uygulaması.

---

## 🌟 Öne Çıkan Özellikler

- 📍 **Otomatik EXIF & GPS Konum Ayıklama**: Videonun çekildiği GPS koordinatlarını okuyup *"Kadıköy, İstanbul, Türkiye"* gibi adreslere çevirir.
- 🎙️ **%100 Türkçe Ses Transkripsiyonu (Whisper AI)**: Videodaki tüm Türkçe konuşmaları zaman damgalı metne döker.
- 👁️ **Görsel Sahne & Aksiyon Analizi (Gemini 2.0 Flash Vision)**: Sahne özeti, eylemler, atmosfer, kamera hareketleri ve estetik puanlama (1-10) çıkartır.
- 🎬 **Uçtan Uca Tam Vlog Senaryosu Motoru**:
  - Giriş (Intro - 15s) kurgusu ve dış ses metni.
  - Sahne sahne kesim listesi & Türkçe Voiceover okuma metinleri.
  - Fon müziği ve SFX efekt rehberi.
  - YouTube başlıkları, açıklamaları ve hashtag önerileri.
- 💻 **Modern Web Dashboard & CLI**: Sürükle-bırak yükleme, canlı süreç takibi, aranabilir katalog ve 1-Tık senaryo kopyalama.

---

## 🚀 Hızlı Başlangıç

### 1. Bağımlılıkları Yükleyin:
```bash
git clone https://github.com/nilhankutlu/travel-vlog-ai.git
cd travel-vlog-ai
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Web Arayüzünü Çalıştırın:
```bash
uvicorn backend.app:app --reload --port 8000
```
Tarayıcınızda `http://localhost:8000` adresini açın!

### 3. Komut Satırı (CLI) İle Kullanım:
```bash
python cli.py process /path/to/video_klasorunuz --output ./vlog_sonuclarim --gemini-key YOUR_GEMINI_API_KEY
```

---

## 📁 Proje Yapısı

```
travel_vlog_ai/
├── backend/
│   ├── app.py                      # FastAPI Web Sunucusu
│   ├── extractors/
│   │   ├── metadata_extractor.py   # MP4/MOV EXIF GPS & Geocoding
│   │   ├── audio_transcriber.py    # Whisper Türkçe Ses Transkripsiyonu
│   │   └── vision_analyzer.py      # Gemini Vision Görsel Analiz
│   └── core/
│       ├── processor.py            # Batch Video İşleyici
│       └── vlog_generator.py       # Tam Vlog Senaryosu Generator
├── frontend/
│   ├── index.html                  # Modern Dashboard UI
│   ├── styles.css                  # Dark mode Glassmorphism CSS
│   └── app.js                      # İnteraktif UI logic & SSE streaming
├── cli.py                          # Terminal CLI aracı
└── requirements.txt                # Python kütüphaneleri
```

---

# 🧩 MegaTravelOS (`mtos/`) — toplu Reels / Shorts / TikTok üretimi

Seyahat arşivinden (iCloud shared album'ler, Live Photos, videolar) **yüzlerce dikey video** çıkaran, **tamamen lokal** çalışan pipeline. Hiçbir ücretli API gerekmez (Ollama + faster-whisper + YAMNet + ffmpeg).

| Aşama | Ne yapar |
|---|---|
| `mtos ingest` | macOS Photos (shared album'ler, Live Photo eşleşmesi, konum, Apple etiketleri) **veya** herhangi bir klasörü kataloğa alır. GPS → şehir (offline). |
| `mtos analyze` | Whisper ile kelime zamanlı transkript, YAMNet ile kahkaha / çığlık / alkış, sahne değişimi kareleri + lokal vision modeli (mizah, hook, estetik, 9:16 kırpma noktası, ekran yazısı fikirleri) → zaman kodlu **moment** veritabanı. |
| `mtos direct` | Konsept üretici: şehir montajı, Top 5, POV, photo dump, kategori (yemek, gece…), günlük vlog, her komik an, alıntılar, split-screen, tatil özeti **ve her tek video / Live Photo'dan ayrı ürünler** (tam klip, yavaş çekim, loop, "sonunu bekle" freeze-frame, Live Photo boomerang / slow-mo / "fotoğraf sandın" reveal / sesli). Lokal LLM senaryo, hook, caption ve hashtag yazar. |
| `mtos render` | ffmpeg ile 1080×1920: Ken Burns, blur dolgu, split-screen, kelime kelime altyazı, hook/outro yazısı, müzik ducking, -14 LUFS. Her videoya Instagram / TikTok / YouTube caption `.txt`. |
| `outputs/index.html` | Filtrelenebilir inceleme galerisi. |

### Kurulum (Mac / Linux / Windows)

```bash
brew install uv ffmpeg            # Linux/Windows: uv + ffmpeg paket yöneticisinden
uv venv --python 3.12 ~/.venvs/mtos            # venv'i iCloud ile senkronize OLMAYAN bir yere koy
uv pip install --python ~/.venvs/mtos -e ".[photos,audio-events,geo]"   # photos = sadece macOS
cp config.example.yaml config.yaml              # kaynak klasör / albümler / modeller
ollama pull llava && ollama pull llama3         # önerilen: qwen2.5vl:7b + qwen2.5:7b
~/.venvs/mtos/bin/mtos all
```

> ⚠️ macOS'ta proje, venv ve `workspace` **Desktop/Documents (iCloud) dışında** olmalı; disk dolunca iCloud dosyaları buluta boşaltır ve Python gizlenen `.pth` dosyalarını atlar.
> Photos kütüphanesinden okumak için terminale **Full Disk Access** verin.
> Müzik: telifsiz parçaları `music/<upbeat|chill|cinematic|funny|emotional>/` altına koyun.

Eski v1 scriptleri `legacy/` altında.
