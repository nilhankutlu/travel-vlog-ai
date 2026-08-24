import unittest
import os
import tempfile
import cv2
import numpy as np

from backend.models.schema import VideoMetadata, AudioTranscript, VisionAnalysis, ProcessedVideoItem
from backend.extractors.metadata_extractor import MetadataExtractor, parse_iso6709_string
from backend.core.vlog_generator import VlogGenerator

class TestVideoPipeline(unittest.TestCase):
    def test_iso6709_parsing(self):
        coords = parse_iso6709_string("+41.0082+028.9784/")
        self.assertIsNotNone(coords)
        self.assertAlmostEqual(coords[0], 41.0082, places=4)
        self.assertAlmostEqual(coords[1], 28.9784, places=4)

    def test_synthetic_video_metadata(self):
        # Create a tiny 1-second synthetic MP4 video file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            height, width = 480, 640
            fps = 30
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(tmp_path, fourcc, fps, (width, height))

            for _ in range(30):
                frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
                out.write(frame)
            out.release()

            extractor = MetadataExtractor()
            metadata = extractor.extract(tmp_path)

            self.assertEqual(metadata.width, 640)
            self.assertEqual(metadata.height, 480)
            self.assertGreater(metadata.duration_seconds, 0)
            self.assertIsNotNone(metadata.file_name)

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_vlog_storyboard_generation(self):
        vlog_gen = VlogGenerator()
        
        sample_item = ProcessedVideoItem(
            video_id="test01",
            metadata=VideoMetadata(
                file_name="istanbul_galata.mp4",
                file_path="/videos/istanbul_galata.mp4",
                file_size_mb=12.5,
                duration_seconds=10.0,
                fps=30.0,
                width=1920,
                height=1080,
                creation_time="2026-08-24 14:00:00"
            ),
            transcript=AudioTranscript(
                full_text="Galata kulesinin yanındayız harika bir hava var.",
                language="tr",
                has_speech=True
            ),
            vision=VisionAnalysis(
                summary="Galata kulesi manzarası ve insanlar yürüyor.",
                aesthetic_score=9.0
            )
        )

        storyboard = vlog_gen.generate_storyboard([sample_item], vlog_title="Test Istanbul Tour")
        self.assertEqual(storyboard.total_videos_analyzed, 1)
        self.assertIn("Galata", storyboard.chat_ai_prompt)

if __name__ == "__main__":
    unittest.main()
