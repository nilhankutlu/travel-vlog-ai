import os
import json
import logging
from typing import List, Optional
import cv2
from PIL import Image
import io

from backend.models.schema import VisionAnalysis, VisualScene

logger = logging.getLogger(__name__)

class VisionAnalyzer:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def sample_video_frames(self, video_path: str, num_frames: int = 5) -> List[Image.Image]:
        """Extracts evenly spaced keyframes from the video file."""
        frames = []
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return frames

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return frames

        indices = [int(i * total_frames / num_frames) for i in range(num_frames)]
        
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                # Convert BGR (OpenCV) to RGB (PIL)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb_frame)
                # Resize to max 1024 width/height for fast transmission
                pil_img.thumbnail((1024, 1024))
                frames.append(pil_img)

        cap.release()
        return frames

    def analyze_with_gemini(self, video_path: str, frames: List[Image.Image], location_context: str = "") -> Optional[VisionAnalysis]:
        """Uses Google GenAI SDK to send frames to Gemini 2.0 Flash for visual scene analysis."""
        if not self.api_key:
            return None

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            prompt = f"""
Sen profesyonel bir Seyahat Vloğu (Travel Vlog) Yönetmeni ve Görsel İçerik Analistisin.
Sana bir videodan alınan sıralı kareler (keyframes) veriliyor.
Konum Bilgisi: {location_context or "Bilinmiyor"}

Lütfen bu videoda olan HER ŞEYİ detaylıca analiz et ve aşağıdaki JSON formatında Türkçe yanıt ver:

JSON Formatı:
{{
  "summary": "Videonun tek cümlelik özeti",
  "detailed_description": "Videoda olan biten her şeyin (mimari, doğa, insanlar, hareketler, detaylar) paragraf anlatımı",
  "objects_detected": ["nesne1", "nesne2", "tarihi eser", "araba"],
  "actions": ["yürüyor", "dondurma yiyor", "kamera dönüyor"],
  "scenery": "Manzara tipi (Deniz kenarı, tarihi sokak, dağ, kafe vb.)",
  "atmosphere": "Atmosfer/Ruh hali (Canlı, huzurlu, kalabalık, güneşli, romantik vb.)",
  "camera_movement": "Kamera hareketi (Sabit çekim, panning, zoom, selfie açısı)",
  "detected_text": ["Tabela metinleri", "Sokak isimleri"],
  "aesthetic_score": 8.5
}}

Lütfen SADECE geçerli JSON döndür, markdown code block işaretleri içermesin.
"""

            contents = [prompt]
            contents.extend(frames)

            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )

            if response and response.text:
                data = json.loads(response.text)
                return VisionAnalysis(
                    summary=data.get("summary", ""),
                    detailed_description=data.get("detailed_description", ""),
                    objects_detected=data.get("objects_detected", []),
                    actions=data.get("actions", []),
                    scenery=data.get("scenery", ""),
                    atmosphere=data.get("atmosphere", ""),
                    camera_movement=data.get("camera_movement", ""),
                    detected_text=data.get("detected_text", []),
                    aesthetic_score=float(data.get("aesthetic_score", 7.0)),
                    scenes=[]
                )

        except Exception as e:
            logger.error(f"Gemini Vision API analysis error: {e}")

        return None

    def fallback_analysis(self, frames: List[Image.Image], duration: float) -> VisionAnalysis:
        """Generates heuristic vision analysis if Gemini API is not available."""
        num_frames = len(frames)
        return VisionAnalysis(
            summary=f"{duration:.1f} saniyelik travel videolu çekim ({num_frames} kare örneklendi)",
            detailed_description="Çekim hareketli dış mekan veya mekan içi seyahat görselidir. (Gemini API anahtarı eklenerek detaylandırılabilir).",
            objects_detected=["seyahat görüntüsü", "dış mekan / mekan"],
            actions=["kamera kaydı"],
            scenery="Seyahat Lokasyonu",
            atmosphere="Doğal",
            camera_movement="El kamerası / Hareketli",
            detected_text=[],
            aesthetic_score=7.0
        )

    def analyze(self, video_path: str, duration: float = 0.0, location_context: str = "") -> VisionAnalysis:
        """Main entry point to perform vision analysis on a video."""
        frames = self.sample_video_frames(video_path, num_frames=5)
        if not frames:
            return VisionAnalysis(
                summary="Kareler okunamadı",
                detailed_description="Video dosyası kare ayrıştırmayı desteklemiyor veya bozuk.",
                aesthetic_score=1.0
            )

        gemini_result = self.analyze_with_gemini(video_path, frames, location_context)
        if gemini_result:
            return gemini_result

        return self.fallback_analysis(frames, duration)
