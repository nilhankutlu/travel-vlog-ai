import os
import re
import datetime
import logging
from typing import Optional, Tuple
import cv2
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

from backend.models.schema import VideoMetadata, GPSLocation

logger = logging.getLogger(__name__)

# Cache for geocoding to prevent excessive API requests
_GEO_CACHE = {}

def parse_iso6709_string(location_str: str) -> Optional[Tuple[float, float]]:
    """
    Parses ISO 6709 location string (e.g. '+41.0082+028.9784/' or '+41.0082+028.9784+0050.0/')
    into (latitude, longitude) floats.
    """
    if not location_str:
        return None
    
    # ISO 6709 regex pattern
    pattern = r'([+-]\d+\.\d+)([+-]\d+\.\d+)'
    match = re.search(pattern, location_str)
    if match:
        try:
            lat = float(match.group(1))
            lon = float(match.group(2))
            return lat, lon
        except ValueError:
            pass
    return None

class MetadataExtractor:
    def __init__(self):
        self.geocoder = Nominatim(user_agent="travel_vlog_ai_indexer/1.0")

    def reverse_geocode(self, lat: float, lon: float) -> GPSLocation:
        """Converts lat/lon coordinates to readable location structure."""
        cache_key = f"{round(lat, 4)},{round(lon, 4)}"
        if cache_key in _GEO_CACHE:
            return _GEO_CACHE[cache_key]

        loc = GPSLocation(
            latitude=lat,
            longitude=lon,
            place_name=f"{lat:.4f}, {lon:.4f}"
        )

        try:
            location_info = self.geocoder.reverse((lat, lon), language="tr", timeout=5)
            if location_info and location_info.raw:
                raw_addr = location_info.raw.get("address", {})
                
                building = raw_addr.get("tourism") or raw_addr.get("historic") or raw_addr.get("amenity") or raw_addr.get("road")
                city = raw_addr.get("city") or raw_addr.get("town") or raw_addr.get("province") or raw_addr.get("state")
                country = raw_addr.get("country")
                
                place_parts = [p for p in [building, city, country] if p]
                loc.place_name = ", ".join(place_parts) if place_parts else location_info.address
                loc.city = city
                loc.country = country
                loc.address = location_info.address

                _GEO_CACHE[cache_key] = loc
        except (GeocoderTimedOut, GeocoderServiceError, Exception) as e:
            logger.warning(f"Geocoding lookup failed for ({lat}, {lon}): {e}")

        return loc

    def extract_mp4_mov_gps(self, file_path: str) -> Optional[Tuple[float, float]]:
        """Extracts GPS coordinates from binary MP4/MOV atoms without external CLI dependencies."""
        try:
            from hachoir.parser import createParser
            from hachoir.metadata import extractMetadata

            parser = createParser(file_path)
            if parser:
                with parser:
                    metadata = extractMetadata(parser)
                    if metadata:
                        # Check for location in metadata
                        for data in metadata.exportPlainList():
                            if "location" in data.lower() or "gps" in data.lower() or "latitude" in data.lower():
                                coords = parse_iso6709_string(data)
                                if coords:
                                    return coords
        except Exception as e:
            logger.debug(f"Hachoir metadata extraction error: {e}")

        # Fallback: scan binary header for ISO 6709 location string pattern
        try:
            with open(file_path, "rb") as f:
                # Read first 1MB & last 1MB (where moov atom is usually located)
                header = f.read(1024 * 1024)
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                tail_size = min(1024 * 1024, file_size)
                f.seek(max(0, file_size - tail_size))
                tail = f.read()
                
                chunk = header + tail
                matches = re.findall(rb'([+-]\d{2,3}\.\d{4,})([+-]\d{2,3}\.\d{4,})', chunk)
                if matches:
                    lat = float(matches[0][0].decode('utf-8'))
                    lon = float(matches[0][1].decode('utf-8'))
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        return lat, lon
        except Exception as e:
            logger.debug(f"Binary GPS scan error: {e}")

        return None

    def extract(self, file_path: str) -> VideoMetadata:
        """Main entry point to extract all metadata from a video file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Video file not found: {file_path}")

        file_name = os.path.basename(file_path)
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # Basic video info via OpenCV
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {file_path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_seconds = frame_count / fps if fps > 0 else 0.0
        cap.release()

        # File creation / modification timestamp
        mtime = os.path.getmtime(file_path)
        creation_time = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Extract GPS Location
        gps_coords = self.extract_mp4_mov_gps(file_path)
        if gps_coords:
            location = self.reverse_geocode(gps_coords[0], gps_coords[1])
        else:
            location = GPSLocation(place_name="Bilinmeyen Konum (GPS Yok)")

        return VideoMetadata(
            file_name=file_name,
            file_path=os.path.abspath(file_path),
            file_size_mb=round(file_size_mb, 2),
            duration_seconds=round(duration_seconds, 2),
            fps=round(fps, 2),
            width=width,
            height=height,
            creation_time=creation_time,
            location=location
        )
