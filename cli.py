#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from backend.core.processor import VideoPipelineProcessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description="Travel Vlog AI Video Maker & Indexer - Automatic EXIF GPS, Whisper Transcript & Gemini Vision Processing"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Process command
    process_parser = subparsers.add_parser("process", help="Process a directory of video files")
    process_parser.add_argument("folder", type=str, help="Path to folder containing raw videos")
    process_parser.add_argument("--output", "-o", type=str, default="./vlog_output", help="Output directory for JSON, Markdown prompt & FFmpeg script")
    process_parser.add_argument("--gemini-key", type=str, default=None, help="Google Gemini API Key for vision analysis")
    process_parser.add_argument("--whisper-model", type=str, default="base", choices=["tiny", "base", "small", "medium", "large-v3"], help="Whisper speech recognition model size")

    args = parser.parse_args()

    if args.command == "process":
        folder_path = os.path.abspath(args.folder)
        output_dir = os.path.abspath(args.output)
        
        if not os.path.exists(folder_path):
            print(f"❌ HATA: '{folder_path}' klasörü bulunamadı!")
            sys.exit(1)

        print("===========================================================")
        print("🚀 TRAVEL VLOG AI INDEXER & AUTOMATED MAKER")
        print("===========================================================")
        print(f"📁 Kaynak Klasör: {folder_path}")
        print(f"📦 Çıktı Dizini: {output_dir}")
        print(f"🎙️ Whisper Modeli: {args.whisper_model}")
        print(f"👁️ Gemini Vision: {'Aktif (API Key verildi)' if args.gemini_key or os.environ.get('GEMINI_API_KEY') else 'Pasif (Heuristic analiz)'}")
        print("-----------------------------------------------------------")

        processor = VideoPipelineProcessor(
            whisper_model=args.whisper_model,
            gemini_api_key=args.gemini_key
        )

        def cli_progress(filename, current, total, ratio, status):
            percent = int(ratio * 100)
            bar = "█" * (percent // 5) + "-" * (20 - (percent // 5))
            print(f"\r[{bar}] %{percent:3d} | [{current}/{total}] {filename[:25]:<25} -> {status:<40}", end="", flush=True)

        results = processor.process_directory(
            directory_path=folder_path,
            output_dir=output_dir,
            progress_cb=cli_progress
        )

        print("\n-----------------------------------------------------------")
        print(f"🎉 İŞLEM TAMAMLANDI! Toplam {len(results)} video başarıyla işlendi.")
        print(f"📄 Oluşturulan Dosyalar:")
        print(f"  1. Master Catalog JSON: {os.path.join(output_dir, 'master_catalog.json')}")
        print(f"  2. AI Vlog Promptu:     {os.path.join(output_dir, 'vlog_prompt.md')}")
        print(f"  3. Otomatik Kurgu Betiği: {os.path.join(output_dir, 'render_vlog.py')}")
        print("===========================================================")

if __name__ == "__main__":
    main()
