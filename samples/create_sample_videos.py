#!/usr/bin/env python3
import os
import cv2
import numpy as np

def create_sample_video(output_path, title, color, frames=60):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    height, width = 720, 1280
    fps = 30
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    for i in range(frames):
        # Create solid color frame with animated overlay text
        frame = np.full((height, width, 3), color, dtype=np.uint8)
        
        # Add text
        text = f"{title} - Frame {i+1}/{frames}"
        cv2.putText(frame, text, (50, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        out.write(frame)

    out.release()
    print(f"✅ Örnek video oluşturuldu: {output_path}")

if __name__ == "__main__":
    sample_dir = os.path.abspath("./samples/test_videos")
    create_sample_video(os.path.join(sample_dir, "01_galata_istanbul.mp4"), "Galata Kulesi Istanbul", (120, 50, 40))
    create_sample_video(os.path.join(sample_dir, "02_cappadocia_balloons.mp4"), "Kapadokya Balon Turu", (30, 100, 180))
    create_sample_video(os.path.join(sample_dir, "03_ephesus_ancient.mp4"), "Efes Antik Kenti", (40, 140, 60))
    print("\n🎉 Tüm örnek videolar hazır! Klasör:", sample_dir)
