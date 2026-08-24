import os
import json
import uuid
import logging
from typing import List, Callable, Optional, Dict, Any

from backend.models.schema import ProcessedVideoItem
from backend.extractors.metadata_extractor import MetadataExtractor
from backend.extractors.audio_transcriber import AudioTranscriber
from backend.extractors.vision_analyzer import VisionAnalyzer
from backend.core.vlog_generator import VlogGenerator

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkdir", ".ins360", ".gopro"}

class VideoPipelineProcessor:
    def __init__(self, whisper_model: str = "base", gemini_api_key: Optional[str] = None):
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
        self.metadata_extractor = MetadataExtractor()
        self.audio_transcriber = AudioTranscriber(model_size=whisper_model)
        self.vision_analyzer = VisionAnalyzer(api_key=self.gemini_api_key)
        self.vlog_generator = VlogGenerator(api_key=self.gemini_api_key)
        self.processed_items: Dict[str, ProcessedVideoItem] = {}

    def is_video_file(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in SUPPORTED_EXTENSIONS

    def process_single_video(
        self,
        video_path: str,
        progress_cb: Optional[Callable[[str, float, str], None]] = None
    ) -> ProcessedVideoItem:
        """Processes one video file through metadata, audio, and vision stages."""
        file_name = os.path.basename(video_path)
        video_id = str(uuid.uuid4())[:8]

        if progress_cb:
            progress_cb(file_name, 0.1, "Metadata ve EXIF GPS okunuyor...")

        # Step 1: Metadata
        metadata = self.metadata_extractor.extract(video_path)

        if progress_cb:
            progress_cb(file_name, 0.4, "Ses konuşmaları (Whisper AI - Türkçe) çözümleniyor...")

        # Step 2: Audio Transcription
        transcript = self.audio_transcriber.transcribe(video_path)

        if progress_cb:
            progress_cb(file_name, 0.7, "Görsel sahne ve aksiyonlar (Gemini Vision) analiz ediliyor...")

        # Step 3: Vision Analysis
        location_ctx = metadata.location.place_name or ""
        vision = self.vision_analyzer.analyze(video_path, metadata.duration_seconds, location_ctx)

        if progress_cb:
            progress_cb(file_name, 1.0, "İşlem tamamlandı.")

        item = ProcessedVideoItem(
            video_id=video_id,
            metadata=metadata,
            transcript=transcript,
            vision=vision,
            status="completed"
        )

        self.processed_items[video_id] = item
        return item

    def process_directory(
        self,
        directory_path: str,
        output_dir: str,
        progress_cb: Optional[Callable[[str, int, int, float, str], None]] = None
    ) -> List[ProcessedVideoItem]:
        """Processes all videos inside a directory."""
        if not os.path.exists(directory_path):
            raise FileNotFoundError(f"Dizin bulunamadı: {directory_path}")

        os.makedirs(output_dir, exist_ok=True)

        video_files = []
        for root, _, files in os.walk(directory_path):
            for file in files:
                full_p = os.path.join(root, file)
                if self.is_video_file(full_p):
                    video_files.append(full_p)

        total_files = len(video_files)
        logger.info(f"Toplanan video sayısı: {total_files}")

        results: List[ProcessedVideoItem] = []

        for idx, v_path in enumerate(video_files, 1):
            fname = os.path.basename(v_path)
            
            def single_cb(filename, step_ratio, status_msg):
                overall_progress = ((idx - 1) + step_ratio) / max(total_files, 1)
                if progress_cb:
                    progress_cb(filename, idx, total_files, overall_progress, status_msg)

            try:
                item = self.process_single_video(v_path, single_cb)
                results.append(item)

                single_json_path = os.path.join(output_dir, f"{item.video_id}_{fname}.json")
                with open(single_json_path, "w", encoding="utf-8") as f:
                    f.write(item.model_dump_json(indent=2))

            except Exception as e:
                logger.error(f"{fname} işlenirken hata oluştu: {e}")

        # Generate Master Catalog & Full End-to-End Turkish Vlog Script
        storyboard = self.vlog_generator.generate_storyboard(results)

        master_json_path = os.path.join(output_dir, "master_catalog.json")
        with open(master_json_path, "w", encoding="utf-8") as f:
            catalog_data = {
                "total_videos": len(results),
                "videos": [item.model_dump() for item in results],
                "storyboard": storyboard.model_dump()
            }
            json.dump(catalog_data, f, ensure_ascii=False, indent=2)

        # Save Complete Turkish Vlog Script
        script_path = os.path.join(output_dir, "final_vlog_script.md")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(storyboard.full_vlog_script_tr)

        prompt_path = os.path.join(output_dir, "vlog_prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(storyboard.chat_ai_prompt)

        render_script_path = os.path.join(output_dir, "render_vlog.py")
        self.vlog_generator.generate_ffmpeg_script(storyboard, results, render_script_path)

        return results
