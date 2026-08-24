import json
import os
import logging
from typing import List, Optional
from backend.models.schema import ProcessedVideoItem, MasterVlogStoryboard, VlogSegment

logger = logging.getLogger(__name__)

class VlogGenerator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def generate_ai_vlog_script(self, title: str, videos: List[ProcessedVideoItem], prompt_text: str) -> str:
        """Uses Gemini API to write the complete end-to-end Travel Vlog Script in Turkish."""
        if not self.api_key:
            return self.generate_fallback_vlog_script(title, videos)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            system_instruction = """
Sen dünyaca ünlü bir YouTube Travel Vlogger'ı ve Profesyonel Video Kurgu Yönetmenisin.
Sana verilen seyahat videolarının (EXIF konumları, zamanları, ses konuşmaları ve görsel analizleri) verilerini kullanarak:

BAŞINDAN SONUNA TAM BİR TRAVEL VLOG SENARYOSU YAZACAKSIN.

Senaryoda tam olarak şunlar yer almalıdır:
1. 🎬 **VLOG BAŞLIĞI VE ÖZETİ**: 3 Farklı YouTube Başlık Önerisi, Sosyal Media Hashtagleri.
2. 🎵 **MÜZİK & ATMOFER**: Giriş, gelişme ve sonuç için fon müziği ve ses efekti (SFX) rehberi.
3. 🚀 **INTRO (GİRİŞ - 00:00 - 00:15)**: Dikkat çekici ilk 15 saniye kurgu ve seslendirme metni.
4. 📹 **SAHNE SAHNE KURGU VE DİŞ SES METNİ (VOICEOVER)**:
   - Hangi videodan hangi saniyeler alınacak?
   - Dış ses olarak ne söylenecek? (Tam okunacak Türkçe dış ses metni)
   - Ekran alt yazısı (Subtitle) ve Konum etiketi.
5. 🏁 **OUTRO (KAPANIŞ)**: Abone ol & beğeni çağrısı dış ses metni.

Lütfen yanıtı son derece detaylı, hazır okunabilir akıcı Türkçe ile ver.
"""

            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[system_instruction, f"İşlenecek Video Verileri ve Konumlar:\n{prompt_text}"],
                config=types.GenerateContentConfig(
                    temperature=0.3
                )
            )

            if response and response.text:
                return response.text
        except Exception as e:
            logger.error(f"Gemini Vlog Script generation error: {e}")

        return self.generate_fallback_vlog_script(title, videos)

    def generate_fallback_vlog_script(self, title: str, videos: List[ProcessedVideoItem]) -> str:
        """Fallback script generator if Gemini API key is not provided."""
        script = f"""# 🎬 TAM TRAVEL VLOG SENARYOSU VE KURGU PLANI

**Vlog Başlığı**: {title}  
**İşlenen Video Sayısı**: {len(videos)}  
**Müzik Önerisi**: Upbeat Cinematic Acoustic / Chill Lo-Fi Travel Beats  

---

## 🚀 INTRO (GİRİŞ - 00:00 - 00:12)
- **Görsel**: En yüksek estetik puana sahip videoların hızlı kurgusu (0.5 sn geçişler).
- **Dış Ses (Voiceover)**: *"Merhaba arkadaşlar! Bugün harika bir yolculuğa çıkıyoruz. Çantamızı hazırladık ve efsane mekanları keşfetmeye hazırız!"*
- **Fon Müziği**: Hareketli, tempolu açılış müziği.

---

## 📹 SAHNE SAHNE AKIŞ VE DIŞ SES METİNLERİ

"""
        for idx, v in enumerate(videos, 1):
            loc_str = v.metadata.location.place_name or v.metadata.location.city or "Keşif Noktası"
            narration = v.transcript.full_text if (v.transcript.has_speech and len(v.transcript.full_text) > 10) else f"Şu an {loc_str} konumundayız. Etraftaki atmosfer harika, buranın manzarası büyüleyici!"

            script += f"""### SAHNE {idx}: {loc_str} (`{v.metadata.file_name}`)
- **Kutlama / Süre**: 00:00 - {min(v.metadata.duration_seconds, 12.0)}s
- **Ekran Konum Yazısı**: `📌 {loc_str}`
- **Görsel**: {v.vision.summary} ({v.vision.camera_movement})
- **Dış Ses (Okunacak Metin)**:
> "{narration}"
- **SFX Efekti**: {v.vision.atmosphere} ses efekti & yumuşak geçiş.

---
"""

        script += """
## 🏁 OUTRO (KAPANIŞ - SON 15 SANİYE)
- **Dış Ses (Voiceover)**: *"Bu harika gezinin sonuna geldik! Eğer videoyu beğendiyseniz kanala abone olmayı ve yorum bırakmayı unutmayın. Bir sonraki macerada görüşmek üzere!"*
- **Ekran**: Son kareler & Abone Ol butonu animasyonu.
"""
        return script

    def generate_storyboard(self, processed_videos: List[ProcessedVideoItem], vlog_title: str = "Unforgettable Travel Journey") -> MasterVlogStoryboard:
        """Constructs a chronological travel vlog storyboard from analyzed video items."""
        sorted_videos = sorted(
            processed_videos,
            key=lambda x: x.metadata.creation_time or ""
        )

        segments: List[VlogSegment] = []
        locations_visited = set()

        for idx, item in enumerate(sorted_videos, 1):
            loc_name = item.metadata.location.place_name or item.metadata.location.city or "Bilinmeyen Mekan"
            locations_visited.add(loc_name)

            if item.transcript.has_speech and item.transcript.full_text:
                narration = f'Ortam/Spiker: "{item.transcript.full_text[:120]}"'
            else:
                narration = f'Dış Ses (Voiceover): "{item.vision.summary}"'

            segment = VlogSegment(
                segment_id=idx,
                video_id=item.video_id,
                file_name=item.metadata.file_name,
                start_time=0.0,
                end_time=min(item.metadata.duration_seconds, 15.0),
                suggested_title=f"Sahne {idx}: {loc_name}",
                narration_voiceover=narration,
                editing_notes=f"Kamera: {item.vision.camera_movement}. Atmosfer: {item.vision.atmosphere}.",
                location_name=loc_name
            )
            segments.append(segment)

        loc_str = ", ".join(list(locations_visited)[:5])
        prompt_text = self.build_ai_vlog_prompt(vlog_title, sorted_videos, segments)

        # Generate End-to-End Turkish Vlog Script
        full_script = self.generate_ai_vlog_script(vlog_title, sorted_videos, prompt_text)

        return MasterVlogStoryboard(
            vlog_title=vlog_title,
            overall_theme=f"{loc_str} Seyahat ve Keşif Vloğu",
            recommended_music_genre="Upbeat Cinematic Travel / Ambient Chill Beats",
            total_videos_analyzed=len(sorted_videos),
            storyline=segments,
            full_vlog_script_tr=full_script,
            chat_ai_prompt=prompt_text
        )

    def build_ai_vlog_prompt(self, title: str, videos: List[ProcessedVideoItem], segments: List[VlogSegment]) -> str:
        prompt = f"""# 🎬 AI TRAVEL VLOG KURGU & SENARYO İSTEMİ

**Vlog Başlığı**: {title}
**İşlenen Toplam Video Sayısı**: {len(videos)}

---

## 📹 VİDEO DİZİNİ VE DETAYLI ANALİZ RAPORU

"""
        for idx, item in enumerate(videos, 1):
            loc = item.metadata.location
            prompt += f"""### Video {idx}: `{item.metadata.file_name}`
- **Tarih & Saat**: {item.metadata.creation_time}
- **Konum**: {loc.place_name} ({loc.latitude or 'N/A'}, {loc.longitude or 'N/A'})
- **Süre**: {item.metadata.duration_seconds} saniye | **Çözünürlük**: {item.metadata.width}x{item.metadata.height}
- **Görsel Sahne Özeti**: {item.vision.summary}
- **Detaylı Görsel Açıklama**: {item.vision.detailed_description}
- **Tespit Edilen Nesneler & Eylemler**: {", ".join(item.vision.objects_detected)} | {", ".join(item.vision.actions)}
- **Atmosfer & Kamera Hareketi**: {item.vision.atmosphere} | {item.vision.camera_movement}
- **Estetik Kurgu Puanı**: {item.vision.aesthetic_score}/10
- **Ses / Konuşma Transcripti (Türkçe)**:
> "{item.transcript.full_text}"

---
"""
        return prompt

    def generate_ffmpeg_script(self, storyboard: MasterVlogStoryboard, videos: List[ProcessedVideoItem], output_script_path: str):
        video_map = {item.video_id: item.metadata.file_path for item in videos}

        script_content = f"""#!/usr/bin/env python3
# Otomatik Oluşturulan Travel Vlog FFmpeg / MoviePy Render Betiği
import os
import sys

print("🚀 Travel Vlog Otomatik Kurgusu Başlatılıyor...")
print("Başlık: {storyboard.vlog_title}")

try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
except ImportError:
    print("❌ HATA: 'moviepy' kütüphanesi yüklü değil. 'pip install moviepy' çalıştırın.")
    sys.exit(1)

clips = []
"""
        for seg in storyboard.storyline:
            fp = video_map.get(seg.video_id)
            if fp:
                script_content += f"""
if os.path.exists(r"{fp}"):
    print("🎬 İşleniyor: {os.path.basename(fp)} ({seg.start_time}s - {seg.end_time}s)...")
    try:
        clip = VideoFileClip(r"{fp}").subclip({seg.start_time}, {seg.end_time})
        clips.append(clip)
    except Exception as e:
        print(f"⚠️ Klip yüklenirken uyarı: {{e}}")
"""

        script_content += """
if not clips:
    print("❌ İşlenecek geçerli klip bulunamadı.")
    sys.exit(1)

print(f"✨ Toplam {len(clips)} klip birleştiriliyor...")
final_clip = concatenate_videoclips(clips, method="compose")
output_filename = "final_travel_vlog.mp4"
final_clip.write_videofile(output_filename, codec="libx264", audio_codec="aac")
print(f"🎉 VLOG KURGUSU TAMAMLANDI! Çıktı dosyası: {output_filename}")
"""
        with open(output_script_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        os.chmod(output_script_path, 0o755)
        logger.info(f"FFmpeg render script created at {output_script_path}")
