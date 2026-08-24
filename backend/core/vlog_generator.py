import json
import os
import logging
from typing import List
from backend.models.schema import ProcessedVideoItem, MasterVlogStoryboard, VlogSegment

logger = logging.getLogger(__name__)

class VlogGenerator:
    def __init__(self):
        pass

    def generate_storyboard(self, processed_videos: List[ProcessedVideoItem], vlog_title: str = "Unforgettable Travel Journey") -> MasterVlogStoryboard:
        """Constructs a chronological travel vlog storyboard from analyzed video items."""
        # Sort videos by creation time
        sorted_videos = sorted(
            processed_videos,
            key=lambda x: x.metadata.creation_time or ""
        )

        segments: List[VlogSegment] = []
        locations_visited = set()

        for idx, item in enumerate(sorted_videos, 1):
            loc_name = item.metadata.location.place_name or item.metadata.location.city or "Bilinmeyen Mekan"
            locations_visited.add(loc_name)

            # Choose narration based on audio transcript or visual summary
            if item.transcript.has_speech and item.transcript.full_text:
                narration = f'Spiker/Ortam Konuşması: "{item.transcript.full_text[:120]}..."'
            else:
                narration = f'Dış Ses / Narration: "{item.vision.summary}"'

            segment = VlogSegment(
                segment_id=idx,
                video_id=item.video_id,
                file_name=item.metadata.file_name,
                start_time=0.0,
                end_time=min(item.metadata.duration_seconds, 15.0),  # Limit best scenes to ~15s max per shot
                suggested_title=f"Sahne {idx}: {loc_name}",
                narration_voiceover=narration,
                editing_notes=f"Kamera: {item.vision.camera_movement}. Atmosfer: {item.vision.atmosphere}. Estetik Puanı: {item.vision.aesthetic_score}/10.",
                location_name=loc_name
            )
            segments.append(segment)

        loc_str = ", ".join(list(locations_visited)[:5])
        
        # Build mega AI Prompt for ChatGPT / Gemini / Claude
        prompt_text = self.build_ai_vlog_prompt(vlog_title, sorted_videos, segments)

        return MasterVlogStoryboard(
            vlog_title=vlog_title,
            overall_theme=f"{loc_str} Seyahat ve Keşif Vloğu",
            recommended_music_genre="Lo-Fi Cinematic / Upbeat Acoustic Travel Music",
            total_videos_analyzed=len(sorted_videos),
            storyline=segments,
            chat_ai_prompt=prompt_text
        )

    def build_ai_vlog_prompt(self, title: str, videos: List[ProcessedVideoItem], segments: List[VlogSegment]) -> str:
        """Builds a formatted Markdown prompt that can be pasted directly into any AI LLM."""
        prompt = f"""# 🎬 AI TRAVEL VLOG KURGU & SENARYO İSTEMİ (PROMPT)

Sana seyahatim sırasında çektiğim **{len(videos)} adet video klibin** tüm EXIF (konum/zaman), ses transkripsiyonu ve Görsel Yapay Zeka analiz verilerini sunuyorum.

Lütfen bu verileri kullanarak YouTube / Instagram / TikTok için profesyonel, akıcı ve ilgi çekici bir **Travel Vlog Senaryosu ve Kurgu Planı** hazırla.

---

## 📌 VLOG GENEL BİLGİLERİ
- **Vlog Başlığı**: {title}
- **İşlenen Toplam Video Sayısı**: {len(videos)}
- **Tavsiye Edilen Müzik Teması**: Upbeat Cinematic Travel / Ambient Chill

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
- **Ses / Konuşma Transcripti**:
> "{item.transcript.full_text}"

---
"""

        prompt += """
## 🎯 YAPMANI İSTEDİĞİM GÖREVLER:

1. **Giriş (Intro - 0:00 - 0:15)**: En yüksek estetik puana sahip videoları seçerek hızlı, tempolu bir intro kurgusu oluştur.
2. **Ana Hikaye Akışı**: Videoları kronolojik ve coğrafi sıraya göre mantıklı bölümlere (Bölüm 1: Varış & İlk İzlenimler, Bölüm 2: Keşif & Yemekler vb.) ayır.
3. **Dış Ses (Voiceover) Metni**: Her sahne geçişi için akıcı, samimi bir anlatıcı dış ses metni yaz.
4. **Müzik ve Ses Efekti (SFX) Önerileri**: Sahnelere uygun arka plan müziği ve atmosferik ses efektleri (rüzgar, deniz, sokak sesleri) belirt.
5. **Kurgu Kesim Listesi (Timestamps)**: Hangi videodan tam olarak kaçıncı saniyelerin alınacağını belirt (örneğin: `video01.mp4 00:02 - 00:07`).
6. **YouTube Başlık & SEO Açıklaması**: Videoya tıklandıran 3 farklı YouTube başlığı ve hashtag'li açıklama metni öner.
"""
        return prompt

    def generate_ffmpeg_script(self, storyboard: MasterVlogStoryboard, videos: List[ProcessedVideoItem], output_script_path: str):
        """Generates an executable Python script using MoviePy/FFmpeg to render the vlog automatically."""
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
