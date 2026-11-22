import json
import argparse
import os
import re
import ollama
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

def generate_premiere_xml(clips, output_filename, fps=30):
    """Yapay zekadan gelen klip listesini Premiere Pro uyumlu XML formatına çevirir."""
    
    xmeml = Element('xmeml', version='4')
    project = SubElement(xmeml, 'project')
    SubElement(project, 'name').text = 'AI_Generated_Reel'
    children = SubElement(project, 'children')
    sequence = SubElement(children, 'sequence', id='sequence-1')
    SubElement(sequence, 'name').text = 'AI Reel Timeline'
    SubElement(sequence, 'duration').text = '10000' 
    
    rate = SubElement(sequence, 'rate')
    SubElement(rate, 'timebase').text = str(fps)
    SubElement(rate, 'ntsc').text = 'FALSE'
    
    media = SubElement(sequence, 'media')
    video = SubElement(media, 'video')
    track = SubElement(video, 'track')
    
    current_frame = 0
    
    for i, clip in enumerate(clips):
        duration_sec = clip.get('duration_seconds', 2.0)
        clip_duration_frames = int(duration_sec * fps)
        
        clipitem = SubElement(track, 'clipitem', id=f'clipitem-{i}')
        SubElement(clipitem, 'name').text = clip.get('file_name', f'clip_{i}')
        SubElement(clipitem, 'duration').text = str(clip_duration_frames)
        
        SubElement(clipitem, 'start').text = str(current_frame)
        SubElement(clipitem, 'end').text = str(current_frame + clip_duration_frames)
        
        SubElement(clipitem, 'in').text = '0'
        SubElement(clipitem, 'out').text = str(clip_duration_frames)
        
        file_elem = SubElement(clipitem, 'file', id=f'file-{i}')
        SubElement(file_elem, 'name').text = clip.get('file_name', f'clip_{i}')
        
        abs_path = os.path.abspath(clip.get('path', ''))
        SubElement(file_elem, 'pathurl').text = f"file://localhost/{abs_path.replace(os.sep, '/')}"
        
        current_frame += clip_duration_frames

    xml_str = minidom.parseString(tostring(xmeml)).toprettyxml(indent="  ")
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(xml_str)
    
    print(f"🎬 Kurgu Timeline'ı oluşturuldu: {output_filename}")
    print("👉 Bu dosyayı Premiere Pro veya DaVinci Resolve'a sürükleyip bırakabilirsiniz!")

def safe_get(data, key, default=""):
    """Yapay zekanın bozduğu JSON formatlarını güvenli bir şekilde okur."""
    if isinstance(data, dict):
        return data.get(key, default)
    elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        return data[0].get(key, default)
    return default

def ask_ollama_for_director_cut(metadata, prompt):
    """Metadata'yı lokal Llama3'e gönderip JSON formatında kurgu planı alır."""
    
    filtered_data = []
    for item in metadata:
        if item.get("type") == "video":
            analysis = item.get("analysis", {})
            filtered_data.append({
                "file_name": item.get("file_name"),
                "path": item.get("path"),
                "scene": safe_get(analysis, "scene", "Bilinmeyen sahne"),
                "mood": safe_get(analysis, "mood", "Bilinmeyen duygu")
            })

    system_prompt = """
    You are an expert video editor. I will give you a JSON list of video files and their descriptions.
    Based on the user's request, select the best videos and create a timeline for a short video reel.
    
    CRITICAL RULES:
    1. ONLY use the 'file_name' and 'path' from the provided list.
    2. You MUST return ONLY a valid JSON object. No explanations, no markdown, no intro text.
    3. The JSON format MUST be exactly like this:
    {
        "title": "Reel Title",
        "concept": "Short concept description",
        "timeline": [
            {"file_name": "video1.mp4", "path": "./path/video1.mp4", "duration_seconds": 2.5, "reason": "Opening shot"},
            {"file_name": "video2.mp4", "path": "./path/video2.mp4", "duration_seconds": 1.5, "reason": "Fast transition"}
        ]
    }
    """

    print("🧠 Lokal AI (Llama 3) senaryoyu ve kurguyu düşünüyor... (İnternetsiz)")
    
    try:
        response = ollama.chat(model='llama3', messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Request: {prompt}\n\nVideo Database:\n{json.dumps(filtered_data)}"}
        ])
        
        result_text = response['message']['content'].strip()
        
        match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if match:
            result_text = match.group(0)
            
        return json.loads(result_text)
    except Exception as e:
        print(f"❌ JSON Çözümleme Hatası: {e}")
        print("Modelin verdiği ham cevap:", result_text if 'result_text' in locals() else "Yok")
        return None

def main():
    parser = argparse.ArgumentParser(description="Mega Travel Content OS - AI Yönetmen (Lokal)")
    parser.add_argument("-i", "--input", type=str, required=True, help="mega_ingestion.py'den çıkan JSON dosyası")
    parser.add_argument("-p", "--prompt", type=str, required=True, help="Ne tarz bir video istiyorsunuz?")
    parser.add_argument("-o", "--output", type=str, default="AI_Timeline.xml", help="Çıktı XML dosyasının adı")
    
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Hata: '{args.input}' dosyası bulunamadı!")
        return

    with open(args.input, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    director_cut = ask_ollama_for_director_cut(metadata, args.prompt)
    
    if director_cut:
        print(f"\n✅ Kurgu Planı Hazır: {director_cut.get('title', 'İsimsiz Kurgu')}")
        print(f"💡 Konsept: {director_cut.get('concept', '')}\n")
        
        for idx, clip in enumerate(director_cut.get('timeline', [])):
            print(f"{idx+1}. {clip.get('file_name')} ({clip.get('duration_seconds')} sn) -> {clip.get('reason')}")

        generate_premiere_xml(director_cut.get('timeline', []), args.output)

if __name__ == "__main__":
    main()