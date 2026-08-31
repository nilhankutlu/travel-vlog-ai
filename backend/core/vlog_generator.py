import json
import os
import logging
from typing import List, Optional
from backend.models.schema import ProcessedVideoItem, MasterVlogStoryboard, VlogSegment

logger = logging.getLogger(__name__)

class VlogGenerator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def generate_ai_vlog_scripts(self, title: str, videos: List[ProcessedVideoItem], prompt_text: str) -> tuple:
        """Uses Gemini API to write both Long-form (YouTube 16:9) and Short-form (Shorts/Reels 9:16) Vlog scripts."""
        if not self.api_key:
            return (
                self.generate_fallback_long_script(title, videos),
                self.generate_fallback_short_script(title, videos)
            )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            system_instruction = """
Sen dünyaca ünlü bir YouTube & TikTok/Reels Travel Content Creator'ısın.
Sana verilen seyahat videoları verilerinden HEM LONG-FORM (Yatay 16:9) HEM DE SHORT-FORM (Dik 9:16 TikTok/Reels/Shorts) iki ayrı senaryo hazırlayacaksın.

Lütfen yanıtı şu başlıklarla ver:

# 🎬 1. LONG-FORM YATAY VLOG SENARYOSU (16:9 YouTube)
- Hikaye akışlı intro, sahne sahne detaylı seslendirme (voiceover) metinleri ve kapanış.

---

# 📱 2. SHORT-FORM DİK VLOG SENARYOSU (9:16 Instagram Reels / TikTok / Shorts)
- En yüksek estetik puana sahip sahnelerden hızlı 15-30 saniyelik tempolu metin, kanca (hook) cümlesi ve trend müzik önerisi.
"""

            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[system_instruction, f"İşlenecek Video Verileri:\n{prompt_text}"],
                config=types.GenerateContentConfig(
                    temperature=0.3
                )
            )

            if response and response.text:
                parts = response.text.split("# 📱 2. SHORT-FORM")
                long_script = parts[0]
                short_script = "# 📱 2. SHORT-FORM" + parts[1] if len(parts) > 1 else response.text
                return long_script, short_script
        except Exception as e:
            logger.error(f"Gemini Vlog Script generation error: {e}")

        return (
            self.generate_fallback_long_script(title, videos),
            self.generate_fallback_short_script(title, videos)
        )

    def generate_fallback_long_script(self, title: str, videos: List[ProcessedVideoItem]) -> str:
        script = f"""# 🎬 LONG-FORM YATAY TRAVEL VLOG SENARYOSU (16:9 YouTube)

**Vlog Başlığı**: {title}  
**Format**: Yatay (16:9) - 1920x1080  
**Müzik Önerisi**: Upbeat Cinematic Acoustic / Chill Travel Beats  

---

## 🚀 INTRO (00:00 - 00:15)
- **Dış Ses (Voiceover)**: *"Merhaba arkadaşlar! Bugün harika bir seyahate çıkıyoruz. İşte keşfettiğimiz en güzel noktalar!"*

## 📹 SAHNE AKIŞI
"""
        for idx, v in enumerate(videos, 1):
            loc_str = v.metadata.location.place_name or v.metadata.location.city or "Keşif Noktası"
            narration = v.transcript.full_text if (v.transcript.has_speech and len(v.transcript.full_text) > 10) else f"Şu an {loc_str} konumundayız. Buraları keşfetmek gerçekten büyüleyici!"
            script += f"""### Sahne {idx}: {loc_str} (`{v.metadata.file_name}`)
- **Süre**: 00:00 - {min(v.metadata.duration_seconds, 15.0)}s
- **Dış Ses Metni**: "{narration}"
---
"""
        return script

    def generate_fallback_short_script(self, title: str, videos: List[ProcessedVideoItem]) -> str:
        top_videos = sorted(videos, key=lambda x: x.vision.aesthetic_score, reverse=True)[:3]
        script = f"""# 📱 SHORT-FORM DİK REELS / TIKTOK / SHORTS SENARYOSU (9:16)

**Başlık**: {title} - Highlights  
**Format**: Dik (9:16) - 1080x1920  
**Müzik Önerisi**: Trending Viral Bass / Fast Travel Beat  
**Kanca (Hook)**: *"Ölmeden önce mutlaka görmeniz gereken 3 yer!"*

---

## ⚡ HIZLI HİGHLIGHT KESİMLERİ (15-30 Saniye)
"""
        for idx, v in enumerate(top_videos, 1):
            loc_str = v.metadata.location.place_name or "Mekan"
            script += f"""- **00:0{idx*2} - 00:0{idx*2+3}**: `{v.metadata.file_name}` | 📌 `{loc_str}` (Estetik: {v.vision.aesthetic_score}/10)
  - Ekran Metni: "📍 {loc_str}"
"""
        return script

    def generate_storyboard(self, processed_videos: List[ProcessedVideoItem], vlog_title: str = "Harika Seyahat Maceram") -> MasterVlogStoryboard:
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
        long_script, short_script = self.generate_ai_vlog_scripts(vlog_title, sorted_videos, prompt_text)

        return MasterVlogStoryboard(
            vlog_title=vlog_title,
            overall_theme=f"{loc_str} Seyahat ve Keşif Vloğu",
            recommended_music_genre="Upbeat Cinematic Travel / Ambient Chill Beats",
            total_videos_analyzed=len(sorted_videos),
            storyline=segments,
            full_vlog_script_tr=long_script,
            short_vlog_script_tr=short_script,
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

    def generate_render_scripts(self, storyboard: MasterVlogStoryboard, videos: List[ProcessedVideoItem], output_dir: str):
        """Generates both Long-Form (1920x1080 16:9 Yatay) and Short-Form (1080x1920 9:16 Dik) render scripts."""
        video_map = {item.video_id: item.metadata.file_path for item in videos}

        # 1. LONG-FORM RENDER SCRIPT (Yatay 16:9 - 1920x1080)
        long_script_path = os.path.join(output_dir, "render_long_vlog.py")
        long_output_path = os.path.join(output_dir, "final_travel_vlog_long.mp4")

        long_content = f"""#!/usr/bin/env python3
import os
import sys

print("🚀 Long-Form (Yatay 16:9 1920x1080) Travel Vlog Kurgusu Başlatılıyor...")
try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
except ImportError:
    print("❌ HATA: 'moviepy' kütüphanesi bulunamadı.")
    sys.exit(1)

clips = []
"""
        for seg in storyboard.storyline:
            fp = video_map.get(seg.video_id)
            if fp:
                long_content += f"""
if os.path.exists(r"{fp}"):
    try:
        clip = VideoFileClip(r"{fp}").subclip({seg.start_time}, {seg.end_time})
        if clip.w != 1920 or clip.h != 1080:
            clip = clip.resize(newsize=(1920, 1080))
        clips.append(clip)
    except Exception as e:
        print(f"⚠️ Uyarı: {{e}}")
"""
        long_content += f"""
if clips:
    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip.write_videofile(r"{long_output_path}", codec="libx264", audio_codec="aac", fps=24)
    print("🎉 Yatay 16:9 Long Vlog Tamamlandı: {long_output_path}")
"""
        with open(long_script_path, "w", encoding="utf-8") as f:
            f.write(long_content)
        os.chmod(long_script_path, 0o755)

        # 2. SHORT-FORM RENDER SCRIPT (Dik 9:16 - 1080x1920)
        short_script_path = os.path.join(output_dir, "render_short_vlog.py")
        short_output_path = os.path.join(output_dir, "final_travel_vlog_short.mp4")

        # Select top aesthetic videos for Short-form reels (max 3 seconds per cut)
        top_videos = sorted(videos, key=lambda x: x.vision.aesthetic_score, reverse=True)[:5]

        short_content = f"""#!/usr/bin/env python3
import os
import sys

print("📱 Short-Form (Dik 9:16 1080x1920 Reels/TikTok) Kurgusu Başlatılıyor...")
try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
    from moviepy.video.fx.all import crop
except ImportError:
    print("❌ HATA: 'moviepy' kütüphanesi bulunamadı.")
    sys.exit(1)

clips = []
"""
        for item in top_videos:
            fp = item.metadata.file_path
            short_content += f"""
if os.path.exists(r"{fp}"):
    try:
        clip = VideoFileClip(r"{fp}").subclip(0, min({item.metadata.duration_seconds}, 3.5))
        # Center-crop to 9:16 ratio (1080x1920)
        (w, h) = clip.size
        target_w = int(h * 9 / 16)
        if target_w < w:
            x_center = w / 2
            clip = crop(clip, width=target_w, height=h, x_center=x_center, y_center=h/2)
        clip = clip.resize(newsize=(1080, 1920))
        clips.append(clip)
    except Exception as e:
        print(f"⚠️ Uyarı: {{e}}")
"""
        short_content += f"""
if clips:
    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip.write_videofile(r"{short_output_path}", codec="libx264", audio_codec="aac", fps=30)
    print("🎉 Dik 9:16 Short Vlog Tamamlandı: {short_output_path}")
"""
        with open(short_script_path, "w", encoding="utf-8") as f:
            f.write(short_content)
        os.chmod(short_script_path, 0o755)

        # Legacy compatibility link
        legacy_script = os.path.join(output_dir, "render_vlog.py")
        with open(legacy_script, "w", encoding="utf-8") as f:
            f.write(long_content)
        os.chmod(legacy_script, 0o755)

        logger.info(f"Generated Long and Short render scripts in {output_dir}")
