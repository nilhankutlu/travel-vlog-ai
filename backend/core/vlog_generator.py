import json
import os
import logging
from typing import List, Optional
from backend.models.schema import ProcessedVideoItem, MasterVlogStoryboard, VlogSegment

logger = logging.getLogger(__name__)

# Exact Persona & Rules from User's Strategy Directive
SHORT_FORM_SYSTEM_DIRECTIVE = """
ROL:
Sen TikTok ve Instagram Reels algoritmasını derinlemesine bilen, gündemi anlık takip eden bir içerik editörü/stratejistsin.

HESAP TEMASI: gezi/travel, lifestyle, vlog, comedy
HEDEF KİTLE: 20-50 yaş, Türkiye gezi içeriği takipçileri

TON KURALI:
Ne aşırı laubali/argo ol ne de kurumsal/resmi bir ton kullan. Deneyimli, esprili ama bilgisine güvenilen bir gezgin arkadaş gibi yaz. Emoji'yi ölçülü kullan, Gen Z/millennial ifadelerini serpiştir ama abartma. "Bu videoda görüldüğü üzere" tarzı anlatıcı/didaktik cümlelerden tamamen kaçın.

GENEL YASAKLAR:
- Düz kolaj/highlight reel önerme (Mod 1'de)
- Şarkı sözü veya başka içerikten alıntı kullanma
- Klişe caption ("unutulmaz anlar", "hayatın güzellikleri" vb. KESİNLİKLE YASAK)

ÇIKTI FORMATI: Numaralandır, uzun girizgah yazma, direkt kullanıma hazır madde madde yaz.
"""

class VlogGenerator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def generate_ai_vlog_scripts(self, title: str, videos: List[ProcessedVideoItem], prompt_text: str, short_mode: int = 1) -> tuple:
        """Uses Gemini API with user's exact persona prompt to generate Long-Form and 4 Short-Form Viral Modes."""
        if not self.api_key:
            return (
                self.generate_fallback_long_script(title, videos),
                self.generate_fallback_short_script(title, videos, short_mode)
            )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            mode_instructions = {
                1: """MOD 1 — HAM VİDEO BANKASI:
Bu videolardan birbirinden bağımsız en az 3 farklı reels/tiktok fikri çıkar. Her fikir için:
1. HOOK — ilk 1-2 saniyelik açılış cümlesi/yazısı
2. SAHNELER — başlangıç/bitiş zaman kodları + neden seçildiği
3. EKRAN YAZILARI — hangi sahnede hangi yazı
4. SES — orijinal ses mi trend ses mi ve neden
5. CAPTION + HASHTAG (3-5 hashtag)
6. NEDEN İŞE YARAR — 1 cümle
""",
                2: """MOD 2 — MEKAN İÇERİKLERİ:
A) ESTETİK KOLAJ İÇİN TAMAMLAYICI ÖĞELER: Müzik önerisi, 2-3 overlay yazı, Caption + hashtag.
B) SESLENDİRME SCRİPTİ: Mekan hakkında 1-2 ilgi çekici doğru bilgi içeren konuşma scripti, saniye eşleştirmesi, Caption + hashtag.
""",
                3: """MOD 3 — BİR GÜNÜMÜZ (DAY-IN-THE-LIFE):
A) KOLAJ TAMAMLAYICILARI: Zaman/aktivite overlay önerileri (örn: 08:30 — kahvaltı), müzik önerisi, Caption + hashtag.
B) SESLENDİRME SCRİPTİ: Kronolojik doğal konuşma dili scripti, saniye eşleştirmeleri, samimi/mizahi dokunuşlar, Caption + hashtag.
""",
                4: """MOD 4 — TRİCK/HACK VİDEOLARI:
SADECE seslendirme scripti üret:
- HOOK — merak uyandıran "böyle yapma" tarzı açılış
- SORUN — insanların genelde yaptığı hata
- ÇÖZÜM — adım adım trick anlatımı
- SONUÇ — rakamsal kazanç/fayda kapanışı
- Saniye bazlı sahne eşleştirmesi, Caption + hashtag.
"""
            }

            selected_mode_prompt = mode_instructions.get(short_mode, mode_instructions[1])

            combined_system_prompt = f"""{SHORT_FORM_SYSTEM_DIRECTIVE}

GÖREV:
Aşağıda verilen seyahat videoları verilerini kullanarak HEM 16:9 LONG-FORM VLOG SENARYOSU HEM DE SEÇİLEN MODDA ({short_mode}) 9:16 SHORT-FORM REELS/TIKTOK SENARYOSU HAZIRLA.

SEÇİLEN SHORT-FORM MODU:
{selected_mode_prompt}

ÇIKTI BAŞLIKLARI:
# 🎬 1. LONG-FORM YATAY VLOG SENARYOSU (16:9 YouTube)
# 📱 2. SHORT-FORM REELS / TIKTOK SENARYOSU (9:16 - MOD {short_mode})
"""

            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[combined_system_prompt, f"İşlenecek Video Verileri ve Konumlar:\n{prompt_text}"],
                config=types.GenerateContentConfig(
                    temperature=0.4
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
            self.generate_fallback_short_script(title, videos, short_mode)
        )

    def generate_fallback_long_script(self, title: str, videos: List[ProcessedVideoItem]) -> str:
        script = f"""# 🎬 LONG-FORM YATAY TRAVEL VLOG SENARYOSU (16:9 YouTube)

**Vlog Başlığı**: {title}  
**Format**: Yatay (16:9) - 1920x1080  
**Müzik Önerisi**: Upbeat Cinematic Acoustic / Chill Travel Beats  

---

## 🚀 INTRO (00:00 - 00:15)
- **Dış Ses (Voiceover)**: *"Selamlar! Bugün bavulları topladık ve harika yerleri keşfetmeye gidiyoruz. İnanılmaz manzaralar ve sürprizler var, hazır mısınız?"*

## 📹 SAHNE AKIŞI
"""
        for idx, v in enumerate(videos, 1):
            loc_str = v.metadata.location.place_name or v.metadata.location.city or "Keşif Noktası"
            narration = v.transcript.full_text if (v.transcript.has_speech and len(v.transcript.full_text) > 10) else f"Şu an {loc_str} konumundayız. Buraların enerjisi ve manzarası harika!"
            script += f"""### Sahne {idx}: {loc_str} (`{v.metadata.file_name}`)
- **Süre**: 00:00 - {min(v.metadata.duration_seconds, 15.0)}s
- **Dış Ses Metni**: "{narration}"
---
"""
        return script

    def generate_fallback_short_script(self, title: str, videos: List[ProcessedVideoItem], mode: int = 1) -> str:
        top_videos = sorted(videos, key=lambda x: x.vision.aesthetic_score, reverse=True)[:3]
        
        mode_titles = {
            1: "MOD 1 — HAM VİDEO BANKASI (3 FARKLI VİRAL REELS FİKRİ)",
            2: "MOD 2 — MEKAN İÇERİKLERİ (ESTETİK KOLAJ & İLGİNÇ BİLGİLER)",
            3: "MOD 3 — BİR GÜNÜMÜZ (DAY-IN-THE-LIFE & SAAT OVERLAYLERİ)",
            4: "MOD 4 — TRİCK / HACK VİDEOLARI (PRATİK TAVSİYELER & Hileler)"
        }

        script = f"""# 📱 SHORT-FORM REELS / TIKTOK SENARYOSU (9:16)
## {mode_titles.get(mode, mode_titles[1])}

**Hedef Kitle**: 20-50 yaş Gezi Takipçileri  
**Ton**: Deneyimli, esprili gezgin arkadaş  

---
"""
        if mode == 1:
            for idx, v in enumerate(top_videos, 1):
                loc_str = v.metadata.location.place_name or "Gezilecek Yer"
                script += f"""### 🚀 VİRAL FİKİR {idx}: {loc_str}
1. **HOOK (İlk 2 Saniye)**: "Burası Türkiye'de ama kendinizi yurtdışında hissettirecek!"
2. **SAHNELER**: `{v.metadata.file_name}` (00:00 - 00:03.5s) -> Yüksek estetik açı ({v.vision.aesthetic_score}/10)
3. **EKRAN YAZISI**: "📌 {loc_str} | Kaydetmeyi unutma!"
4. **SES**: Trend Lo-Fi Travel Beats
5. **CAPTION & HASHTAGS**: Burayı görmeden rotanızı çizmeyin! #gezi #travel #turkey #reels #gezgin
6. **NEDEN İŞE YARAR**: Merak uyandıran gizli mekan formatına uyuyor.

---
"""
        elif mode == 2:
            loc_first = top_videos[0].metadata.location.place_name if top_videos else "Özel Mekan"
            script += f"""### A) ESTETİK KOLAJ ÖĞELERİ
- **Müzik**: Chill Ambient Travel Sound
- **Overlay Yazılar**: "📍 {loc_first}" | "Saklı Cennet"
- **Caption**: Bu mekana gitmeden önce bilinmesi gereken detaylar. #mekan #gezi

### B) SESLENDİRME SCRİPTİ
- **00:00 - 00:03 (Giriş)**: "{loc_first} hakkında bilmeniz gereken en ilginç detay..."
- **00:03 - 00:08 (Bilgi)**: "Burası tarihi dokusu ve manzarasıyla öne çıkıyor."
- **Caption**: #seyahat #rehber #gezi
"""
        elif mode == 3:
            script += f"""### A) SAAT & AKTİVİTE OVERLAYLERİ
- **08:30**: 🍳 Güne Başlangıç & Kahvaltı
- **12:00**: 🏛️ Tarihi Sokaklarda Keşif
- **18:30**: 🌅 Gün Batımı Manzarası

### B) SESLENDİRME SCRİPTİ
- **00:00 - 00:05**: "Bugün beraber harika bir gün geçiriyoruz! Sabah erkenden yola çıktık..."
- **Caption**: Bir günümüz böyle geçti! Siz en çok hangi anı beğendiniz? #dayinthelife #vlog #gezi
"""
        else: # Mod 4
            script += f"""### 💡 TRAVEL TRICK / HACK SCRİPTİ
- **HOOK**: "Sakın bu hatayı yapıp fazla para ödemeyin!"
- **SORUN**: "Çoğu kişi buraya gidişte pahalı bilet alıyor."
- **ÇÖZÜM**: "Bunun yerine bu gizli yöntemi uygulayın..."
- **SONUÇ**: "Yarı yarıya tasarruf edebilirsiniz!"
- **Caption**: Bu ipucunu kaydetmeyi unutmayın! #travelhack #geziipucu #tasarruf
"""
        return script

    def generate_storyboard(self, processed_videos: List[ProcessedVideoItem], vlog_title: str = "Harika Seyahat Maceram", short_mode: int = 1) -> MasterVlogStoryboard:
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
        long_script, short_script = self.generate_ai_vlog_scripts(vlog_title, sorted_videos, prompt_text, short_mode)

        return MasterVlogStoryboard(
            vlog_title=vlog_title,
            overall_theme=f"{loc_str} Seyahat ve Keşif Vloğu",
            recommended_music_genre="Upbeat Cinematic Travel / Ambient Chill Beats",
            total_videos_analyzed=len(sorted_videos),
            storyline=segments,
            full_vlog_script_tr=long_script,
            short_vlog_script_tr=short_script,
            short_mode=short_mode,
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
        video_map = {item.video_id: item.metadata.file_path for item in videos}

        # 1. LONG-FORM RENDER SCRIPT (Yatay 16:9 - 1920x1080)
        long_script_path = os.path.join(output_dir, "render_long_vlog.py")
        long_output_path = os.path.join(output_dir, "final_travel_vlog_long.mp4")

        long_segments_repr = []
        for seg in storyboard.storyline:
            fp = video_map.get(seg.video_id)
            if fp:
                long_segments_repr.append((fp, seg.start_time, seg.end_time))

        long_content = f"""#!/usr/bin/env python3
import os
import sys
import cv2

print("🚀 Long-Form (Yatay 16:9 1920x1080) Travel Vlog Kurgusu Başlatılıyor...")

segments = {repr(long_segments_repr)}
output_path = r"{long_output_path}"

rendered_moviepy = False
try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
    clips = []
    for fp, start_t, end_t in segments:
        if os.path.exists(fp):
            try:
                clip = VideoFileClip(fp).subclip(start_t, end_t)
                if clip.w != 1920 or clip.h != 1080:
                    clip = clip.resize(newsize=(1920, 1080))
                clips.append(clip)
            except Exception as e:
                print(f"⚠️ MoviePy uyarısı: {{e}}")
    if clips:
        final_clip = concatenate_videoclips(clips, method="compose")
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=24)
        print("🎉 Yatay 16:9 Long Vlog MoviePy ile Tamamlandı: " + output_path)
        rendered_moviepy = True
except Exception as e:
    print(f"MoviePy kullanılamadı veya hata verdi ({{e}}), OpenCV motoruna geçiliyor...")

if not rendered_moviepy:
    print("🎥 OpenCV Kurgu Motoru Devrede...")
    target_w, target_h = 1920, 1080
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, 24.0, (target_w, target_h))
    
    for fp, start_t, end_t in segments:
        if not os.path.exists(fp):
            continue
        cap = cv2.VideoCapture(fp)
        if not cap.isOpened():
            continue
            
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 24.0
        start_frame = int(start_t * fps)
        end_frame = int(end_t * fps) if end_t > 0 else int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        curr_frame = start_frame
        
        while cap.isOpened() and curr_frame < end_frame:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            resized = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
            writer.write(resized)
            curr_frame += 1
            
        cap.release()
    writer.release()
    print("🎉 Yatay 16:9 Long Vlog OpenCV ile Tamamlandı: " + output_path)
"""
        with open(long_script_path, "w", encoding="utf-8") as f:
            f.write(long_content)
        os.chmod(long_script_path, 0o755)

        # 2. SHORT-FORM RENDER SCRIPT (Dik 9:16 - 1080x1920)
        short_script_path = os.path.join(output_dir, "render_short_vlog.py")
        short_output_path = os.path.join(output_dir, "final_travel_vlog_short.mp4")

        top_videos = sorted(videos, key=lambda x: x.vision.aesthetic_score, reverse=True)[:5]
        short_segments_repr = []
        for item in top_videos:
            short_segments_repr.append((item.metadata.file_path, 0.0, min(item.metadata.duration_seconds, 3.5)))

        short_content = f"""#!/usr/bin/env python3
import os
import sys
import cv2

print("📱 Short-Form (Dik 9:16 1080x1920 Reels/TikTok) Kurgusu Başlatılıyor...")

segments = {repr(short_segments_repr)}
output_path = r"{short_output_path}"

rendered_moviepy = False
try:
    from moviepy.editor import VideoFileClip, concatenate_videoclips
    from moviepy.video.fx.all import crop
    clips = []
    for fp, start_t, end_t in segments:
        if os.path.exists(fp):
            try:
                clip = VideoFileClip(fp).subclip(start_t, end_t)
                (w, h) = clip.size
                target_w = int(h * 9 / 16)
                if target_w < w:
                    x_center = w / 2
                    clip = crop(clip, width=target_w, height=h, x_center=x_center, y_center=h/2)
                clip = clip.resize(newsize=(1080, 1920))
                clips.append(clip)
            except Exception as e:
                print(f"⚠️ MoviePy uyarısı: {{e}}")
    if clips:
        final_clip = concatenate_videoclips(clips, method="compose")
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=30)
        print("🎉 Dik 9:16 Short Vlog MoviePy ile Tamamlandı: " + output_path)
        rendered_moviepy = True
except Exception as e:
    print(f"MoviePy kullanılamadı veya hata verdi ({{e}}), OpenCV motoruna geçiliyor...")

if not rendered_moviepy:
    print("🎥 OpenCV Kurgu Motoru Devrede (9:16 Dik Kırpma)...")
    target_w, target_h = 1080, 1920
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, 30.0, (target_w, target_h))
    
    for fp, start_t, end_t in segments:
        if not os.path.exists(fp):
            continue
        cap = cv2.VideoCapture(fp)
        if not cap.isOpened():
            continue
            
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        start_frame = int(start_t * fps)
        end_frame = int(end_t * fps) if end_t > 0 else int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        curr_frame = start_frame
        
        while cap.isOpened() and curr_frame < end_frame:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
                
            h, w = frame.shape[:2]
            crop_w = int(h * 9 / 16)
            if crop_w < w:
                start_x = (w - crop_w) // 2
                frame = frame[:, start_x:start_x+crop_w]
                
            resized = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
            writer.write(resized)
            curr_frame += 1
            
        cap.release()
    writer.release()
    print("🎉 Dik 9:16 Short Vlog OpenCV ile Tamamlandı: " + output_path)
"""
        with open(short_script_path, "w", encoding="utf-8") as f:
            f.write(short_content)
        os.chmod(short_script_path, 0o755)

        legacy_script = os.path.join(output_dir, "render_vlog.py")
        with open(legacy_script, "w", encoding="utf-8") as f:
            f.write(long_content)
        os.chmod(legacy_script, 0o755)

        logger.info(f"Generated Long and Short render scripts with OpenCV fallback in {output_dir}")

