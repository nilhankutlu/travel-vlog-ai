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
