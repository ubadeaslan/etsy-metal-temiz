# Etsy Metal Paneli

CNC kesim metal duvar süsü, saat, isim tabelası ve özel portre için **tasarım → kesilebilirlik kontrolü →
mockup → listing metni → yükleme kiti** paneli. Kendi bilgisayarında, tarayıcıdan kullanılır. Windows ve Mac'te
çalışır.

- **Her şey kendi bilgisayarında durur.** Program boş gelir; tasarımların, odaların, ayarların ve API
  anahtarların yalnız senin klasöründedir, kimseye gönderilmez. Tek istisna: AI adımlarında tarifin ve
  tasarım görselin, kendi anahtarınla seçtiğin sağlayıcıya (OpenAI ya da Gemini) gider.
- **AI isteğe bağlı.** Anahtar eklemeden kendi tasarımını yükleyip kontrol, mockup ve kit adımlarını
  kullanabilirsin.

## Kurulum

Önce [Python](https://www.python.org/downloads/) kur (3.11 ya da daha yenisi; önerilen 3.13).

Sonra bu sayfada yeşil **Code → Download ZIP** ile indir ve ZIP'i aç (ya da `git clone`).

### Mac

1. Klasörü kullanıcı klasörüne taşı (İndirilenler'de bırakma).
2. **Terminal**'i aç, `bash ` yaz (sonunda boşluk var), `baslat.command` dosyasını Terminal penceresine
   sürükle ve Enter'a bas.
3. İlk seferde paketler kurulur (birkaç dakika), sonra tarayıcıda panel açılır.

Sonraki açılışlarda aynı şeyi yapabilir ya da çift tıklayabilirsin. İndirilen dosyaya çift tıklayınca Mac
"açılamıyor" derse: **Sistem Ayarları → Gizlilik ve Güvenlik → Yine de Aç**.

### Windows

1. Python kurarken **Add python.exe to PATH** kutusunu işaretle.
2. `baslat.bat` dosyasına çift tıkla. İlk seferde paketler kurulur, sonra tarayıcıda panel açılır.

Kapatmak için Terminal / siyah pencereyi kapat. Panelin adresi: http://127.0.0.1:8765

### Ekran görüntüsünden boy okuma (isteğe bağlı)

- Mac: `brew install tesseract`
- Windows: `winget install --id UB-Mannheim.TesseractOCR`

## İlk ayar

1. **Ayarlar → API anahtarları:** OpenAI ve/veya Gemini anahtarını yapıştır, "modelleri getir" ile dene.
   Aylık tavanı ayarla. Sağlayıcının kendi sitesinde de harcama limiti koy; paneldeki tutar tahmindir.
2. **Ayarlar → Ürün gerçekleri:** malzeme, kalınlık, kaplama, gönderim yeri, mağaza adı… Boş bıraktığın alan
   listing'de hiç geçmez; AI ürün bilgisi uydurmaz.
3. **Ayarlar → Kesim eşikleri:** en ince köprü, en küçük delik, en dar boşluk. Kesimi yapan atölyeye sor.
4. **Ayarlar → SKU:** kendi ön ekin ve ilk numaran.
5. **Odalar:** boş duvarlı oda fotoğrafları yükle ya da ürettir. ChatGPT için hazır liste:
   [docs/oda-promptu.md](docs/oda-promptu.md)
6. **Ayarlar → Hazır kartlarım (isteğe bağlı):** her listing'e eklenecek kendi görsellerin (montaj, kargo, gümrük).

## Akış

1. **Yeni tasarım:** ürün tipi + tarif ("soyut, dalgalı çizgilerden modern saat") → 1-4 aday. Ya da kendi
   PNG/JPG'ni yükle. Satış boyları genişlik olarak girilir (inç ya da cm; yükseklik tasarımın oranından
   hesaplanır).
2. **Kontrol:** en küçük satış boyunda kopan parça, ince köprü, küçük delik, dar boşluk + ağırlık ve kesim
   boyu tahmini. Saatlerde göbek ve mekanizma deliği otomatik eklenir. Her işaretli nokta için ön izlemeli
   düzeltmeler ve elle düzenleyici (taşı, kement, fırça, silgi, köprü; geri al).
3. **Görseller (kare, 3000 px):** renge tıkla, o renk için oda seç: siyah 2, altın 2, gümüş, bronz, beyaz 1'er
   → 7 renk görseli. Ardından Available Finishes, Size Guide, yakın plan, bilgi kartı ve kendi kartların.
4. **Listing:** AI tasarımı görerek İngilizce başlık, 13 tag ve açıklama yazar; preflight Etsy kurallarına göre
   kontrol eder; elle düzenleyebilirsin.
5. **Kit:** `calisma/tasarimlar/<id>/kit/` → `gorseller/` (sıralı) + `listing.txt` + `atolye/` (SVG, PNG, ölçü
   notu, her satış boyu için gerçek mm ölçülü DXF). Etsy'ye sen yükler ve yayınlarsın.

## Verilerin nerede

| Ne | Nerede |
|----|--------|
| Tasarımlar, görseller, kitler | `calisma/tasarimlar/` |
| Odalar · hazır kartlar | `calisma/arka-planlar/` · `calisma/kartlar/` |
| Ayarlar · harcama defteri | `calisma/ayarlar.json` · `calisma/harcama.jsonl` |
| API anahtarları | `.env` |

`calisma/` ve `.env` git'e girmez. **Yedek** için bu ikisini kopyala. **Klasörü birine verirken ikisini de
çıkar**; en iyisi bu sayfanın bağlantısını vermektir.

**Güncelleme:** `git pull` yeter. ZIP kullanıyorsan yeni ZIP'i ayrı klasöre aç, eski klasördeki `calisma`
klasörünü ve `.env` dosyasını yenisine taşı (Mac'te `.env` gizlidir: Finder'da ⌘⇧. ile görünür).

## Sorun çıkarsa

- **"Python bulunamadı":** Python'u kur, dosyayı yeniden aç.
- **Paketler kurulamadı:** interneti kontrol et; sürerse `.venv` klasörünü silip yeniden aç.
- **Portre fotoğrafı açılmıyor:** iPhone'un HEIC fotoğrafını JPG'ye çevir (Mac: Önizleme → Dışa Aktar → JPEG).
- **Gemini 429 "free_tier":** Gemini görsel modelleri ücretsiz katmanda çalışmaz; faturalandırmayı aç ya da
  görselde OpenAI'yi seç.

## Geliştirme

```
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m uvicorn metal.web.app:app --reload --port 8765
```

Font lisansları: [LISANSLAR.md](LISANSLAR.md)
