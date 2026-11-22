import os
import argparse
from pyicloud import PyiCloudService
from tqdm import tqdm
import getpass

def main():
    parser = argparse.ArgumentParser(description="iCloud Albüm İndirici")
    parser.add_argument("-u", "--username", type=str, required=True, help="Apple ID (E-posta)")
    parser.add_argument("-a", "--album", type=str, required=True, help="İndirilecek iCloud Albüm Adı")
    parser.add_argument("-d", "--dest", type=str, default="./iCloud_Medya", help="İndirilecek hedef klasör")
    
    args = parser.parse_args()
    
    # Şifreyi terminalden gizli olarak al
    password = getpass.getpass(prompt=f"{args.username} için iCloud Şifresi: ")
    
    print("☁️ iCloud'a bağlanılıyor...")
    api = PyiCloudService(args.username, password)

    # İki Faktörlü Doğrulama (2FA) Kontrolü
    if api.requires_2fa:
        print("🔒 İki faktörlü doğrulama gerekiyor.")
        code = input("Apple cihazınıza gelen doğrulama kodunu girin: ")
        result = api.validate_2fa_code(code)
        print("Doğrulama sonucu:", result)
        if not result:
            print("❌ Doğrulama başarısız!")
            return

    if not os.path.exists(args.dest):
        os.makedirs(args.dest)

    print(f"📂 '{args.album}' albümü aranıyor...")
    albums = api.photos.albums
    
    if args.album not in albums:
        print(f"❌ Hata: '{args.album}' adında bir albüm bulunamadı.")
        print("Mevcut Albümler:", ", ".join(albums.keys()))
        return

    album_photos = albums[args.album]
    total_photos = len(album_photos)
    print(f"✅ Albüm bulundu! Toplam {total_photos} medya indirilecek.")

    for photo in tqdm(album_photos, desc="İndiriliyor"):
        download_path = os.path.join(args.dest, photo.filename)
        
        # Eğer dosya zaten varsa atla (Kaldığı yerden devam etme özelliği)
        if os.path.exists(download_path):
            continue
            
        download = photo.download()
        with open(download_path, 'wb') as opened_file:
            opened_file.write(download.raw.read())

    print(f"\n🎉 İndirme tamamlandı! Dosyalar '{args.dest}' klasöründe.")

if __name__ == "__main__":
    main()