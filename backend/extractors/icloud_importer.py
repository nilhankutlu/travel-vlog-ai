import os
import re
import json
import logging
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Tuple, Optional
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".ins360", ".gopro"}

class ICloudSharedAlbumImporter:
    def __init__(self, output_base_dir: str = "./output/icloud_albums"):
        self.output_base_dir = os.path.abspath(output_base_dir)
        os.makedirs(self.output_base_dir, exist_ok=True)

    def parse_token(self, url_or_token: str) -> str:
        """Extracts the token from an iCloud Shared Album URL or token string."""
        url_or_token = url_or_token.strip()
        if "#" in url_or_token:
            token = url_or_token.split("#")[-1].strip()
        elif "/" in url_or_token:
            token = url_or_token.rstrip("/").split("/")[-1].strip()
        else:
            token = url_or_token
        
        if "?" in token:
            token = token.split("?")[0]
        return token

    def _discover_host(self, token: str) -> str:
        """Finds the correct partition host for the iCloud shared stream."""
        candidate_hosts = [
            "p102-sharedstreams.icloud.com",
            "p01-sharedstreams.icloud.com",
            "p02-sharedstreams.icloud.com",
            "p03-sharedstreams.icloud.com",
            "p04-sharedstreams.icloud.com",
            "p05-sharedstreams.icloud.com",
            "p11-sharedstreams.icloud.com",
            "p20-sharedstreams.icloud.com",
            "p50-sharedstreams.icloud.com",
        ]
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        
        for host in candidate_hosts:
            url = f"https://{host}/{token}/sharedstreams/webstream"
            body = json.dumps({"streamCsn": "0"}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if "photos" in data:
                            logger.info(f"Discovered active iCloud host: {host}")
                            return host
            except Exception:
                continue
                
        return "p102-sharedstreams.icloud.com"

    def fetch_album_metadata(self, token: str, host: str) -> Tuple[dict, list]:
        """Fetches photos metadata and photo records."""
        url = f"https://{host}/{token}/sharedstreams/webstream"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        body = json.dumps({"streamCsn": "0"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            photos = data.get("photos", [])
            return data, photos

    def fetch_download_urls(self, token: str, host: str, photo_guids: List[str]) -> dict:
        """Fetches download URLs for derivatives via webget endpoint."""
        url = f"https://{host}/{token}/sharedstreams/webget"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        items = {}
        for i in range(0, len(photo_guids), 100):
            chunk = photo_guids[i:i+100]
            body = json.dumps({"photoGuids": chunk}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    items.update(res_data.get("items", {}))
            except Exception as e:
                logger.error(f"Error fetching webget chunk: {e}")
        return items

    def download_album_from_url(
        self,
        url_or_token: str,
        progress_cb: Optional[Any] = None
    ) -> str:
        """Downloads all videos, Live Photos video tracks, and photos from an iCloud Shared Album URL."""
        token = self.parse_token(url_or_token)
        album_dir = os.path.join(self.output_base_dir, token)
        os.makedirs(album_dir, exist_ok=True)

        if progress_cb:
            progress_cb("iCloud Albüm Sunucusu Aranıyor...", 0, 100, 0.05, "iCloud sunucusu ile bağlantı kuruluyor...")

        host = self._discover_host(token)
        metadata, photos = self.fetch_album_metadata(token, host)
        total_photos = len(photos)

        if total_photos == 0:
            raise ValueError("İlgili iCloud Paylaşılan Albümünde medya öğesi bulunamadı veya link geçersiz.")

        if progress_cb:
            progress_cb("Medya Bağlantıları Alınıyor...", 0, total_photos, 0.15, f"{total_photos} medya nesnesi tespit edildi. İndirme adresleri hazırlanıyor...")

        photo_guids = [p["photoGuid"] for p in photos if "photoGuid" in p]
        items_dict = self.fetch_download_urls(token, host, photo_guids)

        downloaded_count = 0
        for idx, photo in enumerate(photos, 1):
            guid = photo.get("photoGuid")
            derivatives = photo.get("derivatives", {})
            media_props = photo.get("mediaProperties", {})
            is_live_photo = media_props.get("livePhoto", False) or "videoDurationSeconds" in media_props

            # Find best video derivative or image derivative
            video_derivative = None
            image_derivative = None

            for key, deriv in derivatives.items():
                checksum = deriv.get("checksum")
                if not checksum or checksum not in items_dict:
                    continue
                
                # Check if it's a video file / Live Photo video track
                file_size = deriv.get("fileSize", 0)
                if "video" in key.lower() or key in ["MOV", "MP4", "1080pVideo", "720pVideo"]:
                    video_derivative = (key, deriv, items_dict[checksum])
                else:
                    # Choose largest image derivative
                    if not image_derivative or file_size > image_derivative[1].get("fileSize", 0):
                        image_derivative = (key, deriv, items_dict[checksum])

            target_derivative = video_derivative or image_derivative
            if not target_derivative:
                continue

            deriv_key, deriv_info, item_loc = target_derivative
            url_loc = item_loc.get("url_location")
            url_path = item_loc.get("url_path")
            if not url_loc or not url_path:
                continue

            download_url = f"https://{url_loc}{url_path}"

            # File naming
            ext = ".mov" if video_derivative else ".jpg"
            filename = f"media_{idx:03d}_{guid[:8]}{ext}"
            file_path = os.path.join(album_dir, filename)

            if not os.path.exists(file_path):
                try:
                    req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp, open(file_path, "wb") as f:
                        f.write(resp.read())
                    downloaded_count += 1
                except Exception as e:
                    logger.error(f"Media indirme hatası ({filename}): {e}")

            ratio = 0.15 + 0.7 * (idx / max(total_photos, 1))
            if progress_cb:
                progress_cb(filename, idx, total_photos, ratio, f"İndiriliyor: {filename} (Live Photo / Video / Görsel)")

        # Prepare static images into motion video clips so all photos are usable
        self.prepare_album_folder(album_dir)

        if progress_cb:
            progress_cb("iCloud Albüm İndirme Tamamlandı", total_photos, total_photos, 1.0, "Tüm videolar ve Live Fotolar başarıyla indirildi ve hazırlandı!")

        return album_dir

    def prepare_album_folder(self, folder_path: str) -> List[str]:
        """
        Scans folder for:
        1. Regular videos (.mp4, .mov) and Live Photo .mov clips.
        2. Static photos without a paired .mov -> convert static photo to a 3-second motion video clip!
        Returns all valid video file paths in folder.
        """
        if not os.path.exists(folder_path):
            return []

        all_files = os.listdir(folder_path)
        base_names_with_video = set()

        for f in all_files:
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_VIDEO_EXTS:
                base_names_with_video.add(os.path.splitext(f)[0].lower())

        valid_videos = []
        for f in all_files:
            ext = os.path.splitext(f)[1].lower()
            full_p = os.path.join(folder_path, f)

            if ext in SUPPORTED_VIDEO_EXTS:
                valid_videos.append(full_p)
            elif ext in SUPPORTED_IMAGE_EXTS:
                base_name = os.path.splitext(f)[0].lower()
                # If there's no matching .mov/.mp4 Live Photo video track, create a 3s motion video clip!
                if base_name not in base_names_with_video and not f.endswith("_converted.mp4"):
                    converted_video_path = os.path.join(folder_path, f"{base_name}_converted.mp4")
                    if not os.path.exists(converted_video_path):
                        self.convert_image_to_video_clip(full_p, converted_video_path, duration_sec=3.0)
                    if os.path.exists(converted_video_path):
                        valid_videos.append(converted_video_path)

        return valid_videos

    @staticmethod
    def convert_image_to_video_clip(
        image_path: str,
        output_video_path: str,
        duration_sec: float = 3.0,
        fps: int = 24
    ) -> str:
        """Converts a static image file into a smooth 3-second motion MP4 video clip using OpenCV."""
        try:
            pil_img = Image.open(image_path).convert("RGB")
            img_np = np.array(pil_img)
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            h, w = img_bgr.shape[:2]
            target_w, target_h = 1920, 1080

            # Scale and center on 1920x1080 canvas
            scale = min(target_w / w, target_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

            canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
            y_offset = (target_h - new_h) // 2
            x_offset = (target_w - new_w) // 2
            canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized

            total_frames = int(duration_sec * fps)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(output_video_path, fourcc, fps, (target_w, target_h))

            # Apply subtle Ken Burns zoom effect (1.00 -> 1.05)
            for frame_idx in range(total_frames):
                zoom_factor = 1.0 + 0.05 * (frame_idx / max(total_frames, 1))
                zh, zw = int(target_h / zoom_factor), int(target_w / zoom_factor)
                zy = (target_h - zh) // 2
                zx = (target_w - zw) // 2
                cropped = canvas[zy:zy+zh, zx:zx+zw]
                zoomed_frame = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
                writer.write(zoomed_frame)

            writer.release()
            logger.info(f"Görsel videoya dönüştürüldü: {output_video_path}")
            return output_video_path
        except Exception as e:
            logger.error(f"Görsel dönüştürme hatası ({image_path}): {e}")
            return ""
