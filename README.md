# NOVA — Türkçe Sesli Masaüstü Asistanı

NOVA, Python ile geliştirilmiş bir Windows masaüstü asistanı prototipidir. Türkçe yazılı veya sesli komutları masaüstü işlemlerine dönüştürür; sonuçları ekranda gösterir ve sesli yanıt verebilir.

## Bileşenler

- **Arayüz:** pywebview, HTML, CSS ve JavaScript.
- **Konuşma tanıma:** faster-whisper / Whisper.
- **Sesli yanıt:** pyttsx3 ve edge-tts.
- **Komut yürütme:** Python fonksiyonları ve izinli işlem listesi.
- **İsteğe bağlı LLM bağlantısı:** Ollama, Gemini veya OpenAI.

## Proje kapsamı

Kodda saat ve sistem bilgisi, izinli uygulama ve web sitesi açma, dosya/klasör ve not işlemleri, hatırlatıcılar, yapılacaklar, takvim çıktıları, ekran görüntüsü ve araştırma işlevleri bulunur. İşlevlerin kullanılabilirliği yerel kurulum ve yapılandırılan servislerle ilişkilidir.

LLM çıktısı doğrudan terminal komutu olarak çalıştırılmaz; uygulamanın tanımlı işlem katmanından geçirilir.

## Kurulum — Windows CMD

Python 3.14.5 ve Windows x64 üzerinde aşağıdaki temel kontroller elle doğrulandı. Proje klasörünü açıp Dosya Gezgini'nin adres çubuğuna `cmd` yazarak bu klasörde bir komut penceresi açabilirsiniz.

```bat
py -3.14 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
python nova_app.py
```

İlk açılışta konuşma tanıma modeli indirilebilir. Uygulama çalışırken CMD penceresini açık tutun.

### LLM ayarları

`.env.example`, varsayılan olarak yerel Ollama bağlantısını kullanır. LLM özellikleri için Ollama'nın çalışması ve `OLLAMA_MODEL` değerindeki modelin bilgisayarınızda bulunması gerekir. Varsayılan model adı `qwen2.5:7b`'dir. Kurulu modele göre `.env` dosyanızı düzenleyin.

Gemini veya OpenAI kullanmak için `.env` içindeki sağlayıcı ve ilgili API anahtarı alanlarını kendi hesabınıza göre yapılandırın. Gerçek API anahtarlarını kaynak depoya eklemeyin.

### Ses çözümleme uyumluluğu

Bu paket, `faster-whisper==1.2.1` ile `av==18.1.0` sürümlerini birlikte kullanır. PyAV 19 ile görülen `metadata_errors` parametre hatasını önlemek için bu iki sürüm kurulum dosyasında sabitlenmiştir.

## Elle doğrulanan temel senaryolar

| Girdi | Doğrulanan sonuç |
| --- | --- |
| Yazılı: `Saat kaç?` | Saat bilgisi ekranda gösterildi. |
| Mikrofon: `Saat kaç?` | Ses algılandı; yanıt yazılı ve sesli verildi. |
| `Not Defteri'ni aç` | Not Defteri açıldı. |

Bu liste bütün özelliklerin veya farklı donanımların test edildiği anlamına gelmez. LLM sağlayıcı bağlantısı ve arka planda uyandırma akışı ayrıca doğrulanmalıdır.

## Çalıştırma dosyaları

- `nova_app.py`: masaüstü arayüzü.
- `main.py`: terminal girişi.
- `nova_watcher.py`: arka planda uyandırma akışı.
- `mikrofon_test.py`: mikrofon denemesi.
- `NOVA_Aktif_Dinleme.bat`, `NOVA_ArkaPlanda_Baslat.bat` ve `NOVA_Debug_Dinleme.bat`: ilgili başlatma kısayolları.

Batch dosyaları kendi bulundukları klasörü kullanır; belirli bir Windows kullanıcı adına veya masaüstü yoluna bağlı değildir.

## Yerel çalışma dosyaları

Paylaşım paketinde API anahtarı içeren `.env`, sanal ortam, ses kayıtları, eski takvim/hatırlatıcı verileri ve sunum günlükleri bulunmaz. Çalışma verileri kullanım sırasında `data/` ve `recordings/` altında oluşabilir. Bu dizinler `.gitignore` ile kaynak takibinin dışında tutulur.

