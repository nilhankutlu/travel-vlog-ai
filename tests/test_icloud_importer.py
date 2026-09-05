import unittest
import os
import tempfile
import cv2
import numpy as np
from PIL import Image

from backend.extractors.icloud_importer import ICloudSharedAlbumImporter
from backend.extractors.metadata_extractor import MetadataExtractor

class TestICloudImporter(unittest.TestCase):
    def test_token_parsing(self):
        importer = ICloudSharedAlbumImporter()
        
        # Test full URL
        url = "https://www.icloud.com/sharedalbum/#B0zG65J8tG99XYZ"
        token = importer.parse_token(url)
        self.assertEqual(token, "B0zG65J8tG99XYZ")

        # Test URL with query string
        url_query = "https://www.icloud.com/sharedalbum/#B0zG65J8tG99XYZ?lang=tr"
        token_query = importer.parse_token(url_query)
        self.assertEqual(token_query, "B0zG65J8tG99XYZ")

        # Test raw token
        self.assertEqual(importer.parse_token("B0zG65J8tG99XYZ"), "B0zG65J8tG99XYZ")

    def test_photo_to_video_conversion(self):
        importer = ICloudSharedAlbumImporter()
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            img_path = os.path.join(tmp_dir, "test_photo.jpg")
            
            # Create a sample synthetic JPEG photo
            pil_img = Image.new("RGB", (800, 600), color=(73, 109, 137))
            pil_img.save(img_path)

            out_video_path = os.path.join(tmp_dir, "test_photo_converted.mp4")
            result_path = importer.convert_image_to_video_clip(img_path, out_video_path, duration_sec=1.5, fps=24)
            
            self.assertTrue(os.path.exists(result_path))
            
            # Verify converted video metadata
            extractor = MetadataExtractor()
            meta = extractor.extract(result_path)
            
            self.assertEqual(meta.width, 1920)
            self.assertEqual(meta.height, 1080)
            self.assertTrue(meta.is_photo_clip)
            self.assertEqual(meta.media_type, "photo")

    def test_folder_preparation_with_live_photo(self):
        importer = ICloudSharedAlbumImporter()
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create Live Photo pair: IMG_0001.JPG and IMG_0001.MOV
            jpg_path = os.path.join(tmp_dir, "IMG_0001.JPG")
            pil_img = Image.new("RGB", (640, 480), color=(100, 200, 100))
            pil_img.save(jpg_path)

            mov_path = os.path.join(tmp_dir, "IMG_0001.MOV")
            out = cv2.VideoWriter(mov_path, cv2.VideoWriter_fourcc(*'mp4v'), 24, (640, 480))
            for _ in range(48): # 2 seconds
                out.write(np.zeros((480, 640, 3), dtype=np.uint8))
            out.release()

            # Create standalone image without MOV pair: IMG_0002.JPG
            jpg_standalone = os.path.join(tmp_dir, "IMG_0002.JPG")
            pil_img.save(jpg_standalone)

            valid_videos = importer.prepare_album_folder(tmp_dir)
            
            # Should have IMG_0001.MOV and newly converted img_0002_converted.mp4
            self.assertGreaterEqual(len(valid_videos), 2)
            video_names = [os.path.basename(v) for v in valid_videos]
            self.assertIn("IMG_0001.MOV", video_names)
            self.assertIn("img_0002_converted.mp4", video_names)

if __name__ == "__main__":
    unittest.main()
