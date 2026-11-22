import os
import argparse
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from moviepy.editor import VideoFileClip, concatenate_videoclips

def parse_xml_timeline(xml_path):
    """XML dosyasını okuyup video yollarını ve sürelerini çıkarır."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    fps = int(root.find('.//timebase').text)
    clips_data = []
    
    for clipitem in root.findall('.//clipitem'):
        pathurl = clipitem.find('.//pathurl').text
        # file://localhost/ kısmını temizle ve Mac yoluna çevir
        filepath = unquote(pathurl.replace('file://localhost', ''))
        
        in_frame = int(clipitem.find('in').text)
        out_frame = int(clipitem.find('out').text)
        duration_sec = (out_frame - in_frame) / fps
        
        clips_data.append({
            'path': filepath,
            'duration': duration_sec
        })
        
    return clips_data

def make_vertical_reel(clip, target_w=1080, target_h=1920):
    """Videoyu Instagram Reels formatına (9:16) ortalayarak keser ve sığdırır."""
    clip_ratio = clip.w / clip.h
    target_ratio = target_w / target_h

    if clip_ratio > target_ratio:
        # Video hedeften daha geniş (Yatay çekilmiş), yüksekliğe göre boyutlandır ve yanlardan kırp
        resized_clip = clip.resize(height=target_h)
        x_center = resized_clip.w / 2
        y_center = resized_clip.h / 2
        cropped_clip = resized_clip.crop(x_center=x_center, y_center=y_center, width=target_w, height=target_h)
    else:
        # Video hedeften daha uzun, genişliğe göre boyutlandır ve alt/üstten kırp
        resized_clip = clip.resize(width=target_w)
        x_center = resized_clip.w / 2
        y_center = resized_clip.h / 2
        cropped_clip = resized_clip.crop(x_center=x_center, y_center=y_center, width=target_w, height=target_h)
        
    return cropped_clip

def main():
    parser = argparse.ArgumentParser(description="Mega Travel Content OS - Otomatik Render Motoru")
    parser.add_argument("-i", "--input", type=str, required=True, help="mega_director.py'den çıkan XML dosyası")
    parser.add_argument("-o", "--output", type=str, default="Final_Reel.mp4", help="Çıktı MP4 dosyasının adı")
    
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Hata: '{args.input}' dosyası bulunamadı!")
        return

    print(f"🎬 '{args.input}' dosyası okunuyor...")
    clips_data = parse_xml_timeline(args.input)
    
    video_clips = []
    
    print("✂️ Videolar kesiliyor ve Reels formatına (9:16) uyarlanıyor...")
    for idx, data in enumerate(clips_data):
        filepath = data['path']
        duration = data['duration']
        
        if not os.path.exists(filepath):
            print(f"⚠️ Uyarı: Dosya bulunamadı, atlanıyor -> {filepath}")
            continue
            
        print(f"   -> İşleniyor: {os.path.basename(filepath)} ({duration} sn)")
        
        try:
            # Videoyu yükle ve sadece başından istenen süre kadarını kes
            clip = VideoFileClip(filepath).subclip(0, duration)
            
            # Instagram Reels formatına çevir
            reel_clip = make_vertical_reel(clip)
            video_clips.append(reel_clip)
        except Exception as e:
            print(f"❌ Hata oluştu ({os.path.basename(filepath)}): {e}")

    if not video_clips:
        print("❌ Birleştirilecek geçerli video bulunamadı!")
        return

    print("\n🎞️ Videolar birleştiriliyor... (Bu işlem bilgisayarınızın hızına göre birkaç dakika sürebilir)")
    
    # Tüm videoları uç uca ekle
    final_video = concatenate_videoclips(video_clips, method="compose")
    
    # MP4 olarak dışa aktar
    final_video.write_videofile(
        args.output, 
        fps=30, 
        codec="libx264", 
        audio_codec="aac",
        preset="fast",
        threads=4
    )
    
    # Hafızayı temizle
    for clip in video_clips:
        clip.close()
    final_video.close()

    print(f"\n✅ BİTTİ! Kurgunuz hazır: {args.output}")
    print("📱 Artık bu videoyu direkt telefonunuza atıp Instagram'da paylaşabilirsiniz!")

if __name__ == "__main__":
    main()