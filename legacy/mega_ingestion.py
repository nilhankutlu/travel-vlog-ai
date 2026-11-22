import os
import cv2
import json
import ollama
import argparse
from tqdm import tqdm
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

TEMP_KLASOR = "./temp_frames"
FOTO_FORMATLARI = ('.jpg', '.jpeg', '.png', '.heic', '.HEIC', '.JPG', '.PNG')
VIDEO_FORMATLARI = ('.mp4', '.mov', '.MP4', '.MOV')

if not os.path.exists(TEMP_KLASOR):
    os.makedirs(TEMP_KLASOR)

def extract_video_frames(video_path):
    """KALİTELİ: Videonun başından, ortasından ve sonundan toplam 3 kare alır."""
    frames_paths = []
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if total_frames == 0:
        return frames_paths

    # Videonun %15, %50 ve %85'inci kısımlarından kare alıyoruz
    frame_indices = [
        int(total_frames * 0.15),
        int(total_frames * 0.50),
        int(total_frames * 0.85)
    ]

    base_name = os.path.basename(video_path)
    
    for i, frame_idx in enumerate(frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            temp_path = os.path.join(TEMP_KLASOR, f"{base_name}_frame_{i}.jpg")
            cv2.imwrite(temp_path, frame)
            frames_paths.append(temp_path)
            
    cap.release()
    return frames_paths

def analyze_image_with_ai(image_path):
    """HIZLI: Görseli küçültüp Moondream modeline gönderir."""
    
    img = Image.open(image_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
        
    # AI'ın hızlı işlemesi için kaliteyi bozmadan boyutunu optimize et
    img.thumbnail((1024, 1024)) 
    
    optimized_path = os.path.join(TEMP_KLASOR, "optimized_temp.jpg")
    img.save(optimized_path, "JPEG", quality=85)

    prompt = """
    Analyze this image and return ONLY a valid JSON object. Do not write any markdown, explanations, or extra text. Just the JSON.
    The JSON must have these exact keys:
    - "scene": A short 3-4 word description of the place (e.g., "Neon lit street").
    - "objects": A list of main objects/people (e.g., ["train", "coffee", "woman"]).
    - "mood": The vibe of the image (e.g., "melancholic", "energetic", "cozy").
    - "lighting": Description of light (e.g., "dark", "golden hour", "harsh sunlight").
    - "aesthetic_score": An integer from 1 to 10 rating the visual quality and cinematic feel.
    """

    try:
        response = ollama.chat(model='moondream', messages=[
            {
                'role': 'user',
                'content': prompt,
                'images': [optimized_path]
            }
        ])
        
        raw_text = response['message']['content'].strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        return json.loads(raw_text.strip())
    except Exception as e:
        return {"error": str(e), "raw_response": raw_text if 'raw_text' in locals() else "Failed"}

def main():
    parser = argparse.ArgumentParser(description="Mega Travel Content OS - Modül 1 & 2")
    parser.add_argument("-f", "--folder", type=str, required=True, help="İşlenecek medya klasörünün tam yolu")
    parser.add_argument("-o", "--output", type=str, default="travel_metadata.json", help="Çıktı JSON dosyasının adı")
    
    args = parser.parse_args()
    klasor_yolu = args.folder
    cikti_dosyasi = args.output

    if not os.path.isdir(klasor_yolu):
        print(f"❌ Hata: '{klasor_yolu}' adında bir klasör bulunamadı!")
        return

    print(f"🚀 Mega Travel Content OS - Başlatılıyor...")
    print(f"📂 Taranan Klasör: {klasor_yolu}")
    
    all_files = [f for f in os.listdir(klasor_yolu) if not f.startswith('.')]
    database = []

    for filename in tqdm(all_files, desc="Medya İşleniyor"):
        file_path = os.path.join(klasor_yolu, filename)
        ext = os.path.splitext(filename)[1].lower()
        
        if ext in FOTO_FORMATLARI:
            ai_result = analyze_image_with_ai(file_path)
            database.append({
                "file_name": filename,
                "type": "photo",
                "path": file_path,
                "analysis": ai_result
            })
            
        elif ext in VIDEO_FORMATLARI:
            frames = extract_video_frames(file_path)
            video_analyses = []
            
            for frame in frames:
                ai_result = analyze_image_with_ai(frame)
                video_analyses.append(ai_result)
                os.remove(frame)
                
            # Videonun genel analizini ilk kare olarak alıyoruz ama tüm karelerin analizi JSON'da saklanıyor
            main_analysis = video_analyses[0] if video_analyses else {}
            
            database.append({
                "file_name": filename,
                "type": "video",
                "path": file_path,
                "analysis": main_analysis,
                "frame_analyses": video_analyses # Baş, orta ve son karelerin tüm detayları burada!
            })

    with open(cikti_dosyasi, 'w', encoding='utf-8') as f:
        json.dump(database, f, ensure_ascii=False, indent=4)
        
    print(f"\n✅ İşlem Tamamlandı! {len(database)} dosya analiz edildi.")
    print(f"💾 Sonuçlar '{cikti_dosyasi}' dosyasına kaydedildi.")

if __name__ == "__main__":
    main()