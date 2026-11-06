from __future__ import annotations

from time import perf_counter
from typing import Any

from app.config import (
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_TIMEOUT_SECONDS,
)
from app.ollama_client import generate_with_ollama
from app.web_research import web_research_summary


MODE_TITLES = {
    "general": "Açıklama",
    "guide": "Pratik Rehber",
    "research": "Araştırma Özeti",
    "location": "Yer Bilgisi",
}

SPOKEN_MESSAGES = {
    "general": "Cevabı hazırladım. Detayları ekranda gösteriyorum.",
    "guide": "Rehberi hazırladım. Adımlar ekranda gösteriliyor.",
    "research": "Araştırma tamamlandı. Açıklama ve kaynaklar ekranda gösteriliyor.",
    "location": "Bilgiyi hazırladım. Detayları ekranda gösteriyorum.",
}

NO_LLM_MESSAGE = (
    "Yerel veya çevrim içi LLM bağlantısı kullanılamadığı için ayrıntılı cevap üretilemedi. "
    "Ollama çalışıyorsa modelin yüklü olduğunu; Gemini/OpenAI kullanıyorsanız API bağlantısını kontrol edin."
)


def generate_ai_answer(user_text: str, mode: str = "general") -> dict[str, Any]:
    """Generate a Turkish explanatory answer without executing desktop actions."""
    clean_text = " ".join(str(user_text or "").strip().split())
    selected_mode = mode if mode in MODE_TITLES else "general"
    if not clean_text:
        return _result(
            "Ne hakkında bilgi istediğinizi biraz daha açık yazar mısınız?",
            "Ne hakkında bilgi istediğinizi belirtir misiniz?",
            provider="fallback",
        )

    if selected_mode == "research":
        return _research_answer(clean_text)

    llm = _answer_with_llm(clean_text, selected_mode)
    if llm["text"]:
        return _result(
            llm["text"],
            SPOKEN_MESSAGES[selected_mode],
            provider=llm["provider"],
            error=llm["error"],
        )

    return _fallback_answer(clean_text, selected_mode, llm["error"])


def generate_general_answer(user_text: str, mode: str = "general") -> dict[str, Any]:
    """Backward-compatible name used by older tool code."""
    return generate_ai_answer(user_text, mode)


def _research_answer(user_text: str) -> dict[str, Any]:
    research = web_research_summary(user_text)
    source_text = str(research.get("screen_message", ""))
    if "ulaşılamadı" in source_text.casefold():
        return _result(
            source_text,
            "İnternet kaynağına ulaşılamadı.",
            provider="fallback",
            error=str(research.get("error", "")),
        )

    llm = _answer_with_llm(user_text, "research", context=source_text)
    if llm["text"]:
        screen = f"{llm['text']}\n\nKaynaklar:\n{_extract_sources(source_text)}".strip()
        return _result(
            screen,
            SPOKEN_MESSAGES["research"],
            provider=llm["provider"],
            error=llm["error"],
        )

    # Web kaynaklı özet, LLM kotası yokken bile boş şablondan daha değerlidir.
    return _result(
        source_text,
        SPOKEN_MESSAGES["research"],
        provider="fallback",
        error=llm["error"],
    )


def _answer_with_llm(user_text: str, mode: str, context: str = "") -> dict[str, str]:
    provider = _selected_provider()
    if not provider:
        return {"text": "", "provider": "fallback", "error": "LLM API anahtarı bulunamadı."}

    try:
        start = perf_counter()
        if provider == "ollama":
            prompt = f"{_prompt_for_mode(mode, context)}\n\nKullanıcı sorusu:\n{user_text}"
            answer = generate_with_ollama(prompt)
            print(f"[PERF] Ollama cevap üretimi ({OLLAMA_MODEL}): {perf_counter() - start:.1f} sn", flush=True)
            return {"text": answer, "provider": "ollama", "error": ""}

        from openai import OpenAI

        if provider == "gemini":
            client = OpenAI(
                api_key=GEMINI_API_KEY,
                base_url=GEMINI_BASE_URL,
                timeout=OPENAI_TIMEOUT_SECONDS,
                max_retries=0,
            )
            response = client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=[
                    {"role": "system", "content": _prompt_for_mode(mode, context)},
                    {"role": "user", "content": user_text},
                ],
            )
            print(f"[PERF] Gemini cevap üretimi: {perf_counter() - start:.1f} sn", flush=True)
            return {
                "text": (response.choices[0].message.content or "").strip(),
                "provider": "gemini",
                "error": "",
            }

        client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": _prompt_for_mode(mode, context)},
                {"role": "user", "content": user_text},
            ],
        )
        print(f"[PERF] OpenAI cevap üretimi: {perf_counter() - start:.1f} sn", flush=True)
        return {"text": response.output_text.strip(), "provider": "openai", "error": ""}
    except Exception as exc:
        error = str(exc)
        print(f"Genel cevap LLM kullanılamadı, fallback kullanıldı: {error}", flush=True)
        return {"text": "", "provider": "fallback", "error": error}


def _selected_provider() -> str:
    provider = (LLM_PROVIDER or "gemini").casefold()
    if provider == "ollama":
        return "ollama"
    if provider == "gemini" and GEMINI_API_KEY:
        return "gemini"
    if provider == "openai" and OPENAI_API_KEY:
        return "openai"
    return ""


def _prompt_for_mode(mode: str, context: str = "") -> str:
    base = """
Sen NOVA adlı Türkçe masaüstü yapay zeka asistanının bilgi üretim modusun.
Kullanıcının sorusunu doğrudan, yüksek kaliteli ve anlaşılır Türkçe ile cevapla.

Kurallar:
- Boş dolgu cümlesi yazma; "genel bir çerçeve sunabilirim" gibi kaçamak ifadeler kullanma.
- Kullanıcı detay isterse detaylı anlat; terimleri açıkla, örnek ver, gerekirse başlık kullan.
- Nasıl yapılır sorularında adım adım rehber ver.
- Pratik konularda malzemeler, yöntem, alternatifler ve dikkat noktalarını belirt.
- Tehlikeli sistem işlemi, CMD, PowerShell, registry, silme, formatlama veya zararlı işlem tarifi verme.
- Riskli istekte güvenli alternatif öner.
- "Duruma göre değişir" deyip bırakma; hangi durumlarda nasıl değiştiğini açıkla.
- Gerektiğinde şu başlıklardan uygun olanları kullan: Kısa Tanım, Detaylı Açıklama, Nasıl Çalışır, Nasıl Yapılır, Kullanım Alanları, Örnekler, Dikkat, Sonuç.
""".strip()

    if mode == "guide":
        mode_text = """
Cevap pratik rehber formatında olsun.
Gerekli malzemeler / araçlar, adım adım uygulama, alternatifler, güvenlik ve sonuç bölümlerini kullan.
""".strip()
    elif mode == "research":
        mode_text = """
Kaynak bağlamına dayanarak kapsamlı ama okunabilir bir araştırma açıklaması yaz.
Kaynakta olmayan bilgileri kesin gerçek gibi uydurma.
Kaynak linklerini metne yığma; kaynaklar ayrıca gösterilecek.
""".strip()
    elif mode == "location":
        mode_text = """
Yer, şehir, kurum veya lokasyon hakkında düzenli bilgi ver.
Öne çıkan noktalar, pratik öneriler ve kısa sonuç ekle.
Güncellik gerektiren ayrıntılarda temkinli ifade kullan.
""".strip()
    else:
        mode_text = """
Genel bilgi cevabı ver.
Kısa tanım, detaylı açıklama, örnekler, dikkat edilmesi gerekenler ve sonuç bölümlerini gerektiği kadar kullan.
""".strip()

    if context:
        return f"{base}\n\n{mode_text}\n\nKaynak bağlamı:\n{context}"
    return f"{base}\n\n{mode_text}"


def _fallback_answer(user_text: str, mode: str, error: str = "") -> dict[str, Any]:
    normalized = user_text.casefold().replace("ı", "i")

    if "merhaba" in normalized or "nasilsin" in normalized:
        return _result(
            "İyiyim, teşekkür ederim. Size güvenli masaüstü işlemleri, bilgi soruları ve pratik rehberlerde yardımcı olabilirim.",
            "İyiyim, size nasıl yardımcı olabilirim?",
            provider="fallback",
            error=error,
        )

    if mode == "guide" and "masa" in normalized:
        return _result(_fallback_table_guide(), SPOKEN_MESSAGES["guide"], provider="fallback", error=error)

    if "buyuk dil" in normalized or "büyük dil" in normalized or "llm" in normalized or "large language" in normalized:
        return _result(_fallback_llm_explanation(), SPOKEN_MESSAGES["general"], provider="fallback", error=error)

    if "pywebview" in normalized or "py webview" in normalized:
        return _result(_fallback_pywebview_explanation(), SPOKEN_MESSAGES["general"], provider="fallback", error=error)

    if mode == "location" and "konya" in normalized:
        return _result(_fallback_konya_info(), SPOKEN_MESSAGES["location"], provider="fallback", error=error)

    if mode == "guide":
        return _result(_fallback_guide_unavailable(), SPOKEN_MESSAGES["guide"], provider="fallback", error=error)

    return _result(
        NO_LLM_MESSAGE,
        "Ayrıntılı cevap üretilemedi. Lütfen API bağlantısını kontrol edin.",
        success=False,
        provider="fallback",
        error=error,
    )


def _fallback_table_guide() -> str:
    return "\n".join(
        [
            "Masa Yapımı İçin Gerekli Malzemeler",
            "",
            "Kısa açıklama:",
            "Basit ve sağlam bir masa yapmak için önce kullanım amacını, ölçüleri ve malzeme tipini belirlemek gerekir.",
            "",
            "Gerekli malzemeler:",
            "- Masa tablası: MDF, kontrplak, masif ahşap veya hazır tezgah tablası",
            "- Ayaklar: Hazır metal ayak, ahşap ayak veya çerçeve ayak sistemi",
            "- Vida ve bağlantı aparatları",
            "- Köşe bağlantı elemanları veya L bağlantı",
            "- Zımpara, vernik ya da koruyucu boya",
            "- Matkap veya vidalama aleti",
            "",
            "Önerilen ölçüler:",
            "- Çalışma masası için 120-140 cm genişlik iyi bir başlangıçtır.",
            "- Derinlik genelde 60-75 cm aralığında seçilir.",
            "- Yükseklik çoğu kullanım için 72-75 cm civarında olur.",
            "",
            "Adım adım uygulama:",
            "1. Masanın nerede kullanılacağını ve ölçülerini belirleyin.",
            "2. Tabla malzemesini seçin. Yeni başlayanlar için MDF veya kontrplak daha pratiktir.",
            "3. Ayakların yerini işaretleyin ve simetrik olduğundan emin olun.",
            "4. Ayakları kısa vida ve bağlantı aparatlarıyla sabitleyin.",
            "5. Sallanmayı azaltmak için alt kısma destek çıtası veya çapraz bağlantı ekleyin.",
            "6. Kenarları zımparalayın ve yüzeyi vernik ya da boya ile koruyun.",
            "",
            "Dikkat:",
            "- Vida boyu tablayı delmeyecek kadar kısa olmalıdır.",
            "- Masa sallanıyorsa ayak bağlantılarını ve destek kayıtlarını güçlendirin.",
            "- Keskin kenarları mutlaka zımparalayın.",
            "",
            "Sonuç:",
            "Sunum veya öğrenci projesi için en pratik çözüm, sağlam bir MDF/kontrplak tabla ile hazır metal ayak kullanmaktır.",
        ]
    )


def _fallback_llm_explanation() -> str:
    return "\n".join(
        [
            "Büyük Dil Modelleri Nedir?",
            "",
            "Kısa Tanım",
            "Büyük dil modelleri, çok büyük metin veri kümeleri üzerinde eğitilen ve insan dilini anlama, üretme, özetleme, sınıflandırma, çeviri, kod açıklama ve soru cevaplama gibi görevleri yerine getirebilen yapay zeka modelleridir.",
            "",
            "Detaylı Açıklama",
            "Bu modeller, metindeki kelime ve parça ilişkilerini istatistiksel olarak öğrenir. Modern modeller çoğunlukla Transformer mimarisini kullanır. Transformer yapısı, bir cümledeki kelimelerin birbirleriyle olan bağını dikkate alarak bağlama uygun cevap üretmeyi sağlar.",
            "",
            "İlk Ne Zaman ve Nerede Kullanıldılar?",
            "Dil modeli fikri bilgisayar bilimi ve istatistiksel doğal dil işleme çalışmalarında 1980'ler ve 1990'larda kullanılmaya başladı. Ancak bugünkü anlamıyla büyük ölçekli yapay sinir ağı tabanlı dil modelleri 2010'ların sonunda öne çıktı. 2017'de Transformer mimarisinin tanıtılması, 2018'de GPT ve BERT gibi modellerin yaygınlaşması, 2020'de GPT-3 gibi çok büyük modellerin görünür hale gelmesi bu gelişimin önemli dönüm noktalarıdır. İlk güçlü kullanımlar daha çok ABD merkezli üniversiteler, büyük teknoloji şirketleri ve araştırma laboratuvarlarında görülmüştür.",
            "",
            "Nasıl Çalışır?",
            "1. Metin token adı verilen küçük parçalara ayrılır.",
            "2. Model, eğitim sırasında milyonlarca veya milyarlarca örnekten dil örüntülerini öğrenir.",
            "3. Kullanıcı soru sorduğunda mevcut bağlama göre en uygun devam metnini tahmin eder.",
            "4. Cevap üretirken önceki kelimeleri, kullanıcı niyetini ve verilen talimatları birlikte değerlendirir.",
            "",
            "Kullanım Alanları",
            "- Sohbet asistanları",
            "- Kod yazma ve kod açıklama",
            "- Metin özetleme",
            "- Belge analizi",
            "- Eğitim desteği",
            "- Araştırma taslağı hazırlama",
            "- Müşteri destek sistemleri",
            "",
            "Dikkat Edilmesi Gerekenler",
            "- Bazen hatalı veya uydurma bilgi verebilir.",
            "- Güncel bilgi gereken konularda kaynak kontrolü yapılmalıdır.",
            "- Hassas kişisel bilgiler modele verilmemelidir.",
            "- Cevaplar uzman doğrulamasının yerine geçmemelidir.",
            "",
            "Sonuç",
            "Büyük dil modelleri dili güçlü biçimde işleyebilen araçlardır. En iyi sonuç için net komut, yeterli bağlam ve güvenlik kontrolüyle kullanılmaları gerekir.",
        ]
    )


def _fallback_pywebview_explanation() -> str:
    return "\n".join(
        [
            "PyWebView Nedir?",
            "",
            "Kısa Tanım",
            "PyWebView, Python ile masaüstü pencere açıp bu pencerenin içinde HTML, CSS ve JavaScript arayüzü çalıştırmayı sağlayan hafif bir kütüphanedir.",
            "",
            "Nasıl Çalışır?",
            "Python tarafı masaüstü pencereyi oluşturur. Arayüz tarafı HTML/CSS/JS ile hazırlanır. JavaScript, pywebview API üzerinden Python fonksiyonlarını çağırabilir. Böylece web teknolojileriyle görünen ama Python ile çalışan masaüstü uygulamalar geliştirilebilir.",
            "",
            "NOVA'da Kullanım Mantığı",
            "- `nova_app.py` pencereyi açar.",
            "- `ui/index.html`, `ui/style.css` ve `ui/app.js` arayüzü oluşturur.",
            "- JavaScript, Python'daki API sınıfını çağırır.",
            "- Python tarafı komutu yorumlar, güvenli plan üretir ve izinli araçlarla çalıştırır.",
            "",
            "Avantajları",
            "- Arayüz geliştirmek HTML/CSS ile kolaydır.",
            "- Python ekosistemiyle doğrudan çalışır.",
            "- Öğrenci projeleri ve prototipler için hızlıdır.",
            "",
            "Dikkat",
            "PyWebView doğrudan güvenlik sağlamaz. Güvenlik, Python tarafındaki whitelist action/tool yapısıyla kurulmalıdır.",
        ]
    )


def _fallback_konya_info() -> str:
    return "\n".join(
        [
            "Konya Hakkında Kısa Bilgi",
            "",
            "Kısa Tanım",
            "Konya, Türkiye'nin yüzölçümü bakımından en büyük illerinden biridir. Selçuklu mirası, Mevlana kültürü ve geniş bozkır coğrafyasıyla öne çıkar.",
            "",
            "Öne Çıkan Yerler",
            "1. Mevlana Müzesi",
            "2. Alaeddin Tepesi ve Alaeddin Camii",
            "3. Karatay Medresesi",
            "4. Sille",
            "5. Meram Bağları",
            "6. Tropikal Kelebek Bahçesi",
            "",
            "Pratik Öneriler",
            "- Tarihi merkez için yürüyüş rotası yapılabilir.",
            "- Sille ve Meram için ayrı zaman ayırmak iyi olur.",
            "- Güncel ziyaret saatleri için resmi kaynaklar kontrol edilmelidir.",
            "",
            "Sonuç",
            "Konya; tarih, kültür ve sakin şehir deneyimini birlikte sunan güçlü bir gezi rotasıdır.",
        ]
    )


def _fallback_guide_unavailable() -> str:
    return "\n".join(
        [
            "Ayrıntılı Rehber Üretilemedi",
            "",
            "Gemini bağlantısı kullanılamadığı için bu konuda yeterince ayrıntılı ve güvenilir bir rehber hazırlayamadım.",
            "",
            "Ne yapabilirsiniz?",
            "1. İnternet bağlantısını kontrol edin.",
            "2. GEMINI_API_KEY değerinin .env dosyasında doğru olduğundan emin olun.",
            "3. Biraz daha kısa ve net bir komutla tekrar deneyin.",
        ]
    )


def _extract_sources(source_text: str) -> str:
    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    capture = False
    sources = []
    for line in lines:
        if line.casefold().startswith("kaynak"):
            capture = True
            continue
        if capture:
            sources.append(line)
    return "\n".join(sources[:6]) or "Kaynak bilgisi ekranda gösteriliyor."


def _result(
    screen_message: str,
    spoken_message: str,
    *,
    success: bool = True,
    provider: str = "fallback",
    error: str = "",
) -> dict[str, Any]:
    return {
        "success": success,
        "screen_message": screen_message.strip(),
        "spoken_message": spoken_message.strip(),
        "provider": provider,
        "error": error,
    }
