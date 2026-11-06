from __future__ import annotations

import json
import re
import unicodedata
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from app.action_registry import registry_for_prompt, registry_schema
from app.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS
from app.llm_router import route_with_llm

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - dependency fallback for old envs
    from difflib import SequenceMatcher

    class _FuzzFallback:
        @staticmethod
        def token_set_ratio(a: str, b: str) -> float:
            return SequenceMatcher(None, a, b).ratio() * 100

        @staticmethod
        def partial_ratio(a: str, b: str) -> float:
            return SequenceMatcher(None, a, b).ratio() * 100

    fuzz = _FuzzFallback()


SUPPORTED_CONTEXT = registry_for_prompt()

OUT_OF_SCOPE_MESSAGE = (
    "Ben masaüstü işlemlerine odaklı bir sesli asistanım. "
    "Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı ve takvim gibi "
    "bilgisayar işlemlerinde yardımcı olabilirim."
)
UNSAFE_MESSAGE = "Bu işlem güvenlik nedeniyle uygulanmadı."
UNCLEAR_MESSAGE = "Komutu net anlayamadım, tekrar söyleyebilir misiniz?"


INTERPRETER_PROMPT = f"""
Sen NOVA masaüstü asistanının komut yorumlama katmanısın.
Ham ASR metnini Türkçe doğal komut olarak yorumla ve kullanıcının muhtemel gerçek komutunu düzelt.

Kurallar:
- Yeni işlem uydurma.
- Tehlikeli komut üretme.
- Shell, CMD, PowerShell, registry, silme, formatlama, şifre toplama veya sistem ayarı komutu üretme.
- Kullanıcı niyeti belirsizse metni koru ve düşük confidence ver.
- Sadece şu güvenli bağlamda yorum yap:
{SUPPORTED_CONTEXT}

Sadece şu JSON biçiminde cevap ver:
{{
  "interpreted_text": "...",
  "confidence": 0.0,
  "note": "kısa açıklama"
}}
""".strip()


INTENT_PROMPT = f"""
Sen NOVA masaüstü asistanının merkezi intent router katmanısın.
Kullanıcının Türkçe doğal dilini desteklenen action/tool sistemine çevir.

Kurallar:
- Action uydurma, sadece action registry içinden seçim yap.
- Tehlikeli isteklerde UNSAFE_REQUEST dön.
- Masaüstü asistanlığı dışındaki sohbetlerde OUT_OF_SCOPE_CHAT dön.
- Eksik kritik bilgi varsa NEEDS_CLARIFICATION dön ve kısa soru sor.
- Shell, CMD, PowerShell, registry, silme, formatlama, şifre veya sistem ayarı komutu üretme.
- JSON dışında cevap verme.

Action registry:
{SUPPORTED_CONTEXT}

JSON formatı:
{{
  "category": "DESKTOP_ACTION | ANSWER_ONLY_IN_SCOPE | OUT_OF_SCOPE_CHAT | UNSAFE_REQUEST | NEEDS_CLARIFICATION | UNCLEAR",
  "action": "ACTION_NAME_OR_NULL",
  "args": {{}},
  "message": "",
  "spoken_message": "",
  "confidence": 0.0
}}
""".strip()


ACTION_ALIASES: dict[str, tuple[str, ...]] = {
    "DATE_TIME_ANSWER": (
        "saat kac",
        "sat kac",
        "saat kc",
        "bugunun tarihi ne",
        "bugun gunlerden ne",
        "tarih ne",
    ),
    "OPEN_WEBSITE": (
        "google ac",
        "googlea gir",
        "gogle ac",
        "youtube ac",
        "yutube ac",
        "github ac",
        "cecihome ac",
        "ceci home ac",
        "cecihome com tr ac",
        "siteyi baslat",
        "web sitesini ac",
        "selcuk universitesi sitesini ac",
    ),
    "WEB_SEARCH": (
        "internette ara",
        "google da ara",
        "webde ara",
        "arastir",
        "haberlerini ara",
        "nedir ara",
    ),
    "WEB_RESEARCH_SUMMARY": (
        "arastir ve ozetle",
        "hakkinda arastir",
        "nedir arastir",
        "kisa ozetle",
        "haberlerini ozetle",
        "son gelismeleri ozetle",
        "kaynaklardan ozetle",
    ),
    "WEB_RESEARCH_SAVE": (
        "arastir ve masaustune kaydet",
        "arastirma yap ve kaydet",
        "rapor hazirla",
        "kaynakli rapor hazirla",
        "dosyaya kaydet",
        "arastirma raporu olustur",
    ),
    "SUMMARIZE_URL": (
        "bu siteyi ozetle",
        "su siteyi ozetle",
        "bu baglantiyi oku",
        "bu linki ozetle",
        "url ozetle",
    ),
    "LATEST_NEWS_BY_TOPIC": (
        "son haberler",
        "son gelismeler",
        "gundemi ozetle",
        "teknoloji gundemi",
        "haberlerini ozetle",
        "guncel haberler",
    ),
    "OFFICIAL_INFO_SEARCH": (
        "resmi siteden arastir",
        "resmi kaynaktan bul",
        "resmi duyuruyu bul",
        "akademik takvimi resmi siteden bul",
        "universite sitesinden arastir",
    ),
    "ACADEMIC_SEARCH": (
        "akademik makale ara",
        "bilimsel kaynak bul",
        "literatur taramasi yap",
        "paper bul",
        "akademik yayinlari goster",
        "kaynaklariyla akademik ozet cikar",
    ),
    "OPEN_COMMON_APP": (
        "not defterini ac",
        "not deftrini ac",
        "hesap makinesini ac",
        "hesap maknesi ac",
        "paint ac",
        "vscode ac",
        "chrome ac",
        "word ac",
        "excel ac",
        "powerpoint ac",
        "dosya gezgini ac",
    ),
    "OPEN_SPECIAL_FOLDER": (
        "masaustunu ac",
        "belgelerimi ac",
        "belgeler klasorunu ac",
        "indirilenleri ac",
        "indirilenler klasorunu ac",
        "resimlerimi ac",
    ),
    "CREATE_FOLDER": (
        "klasor olustur",
        "yeni klasor yap",
        "proje klasoru olustur",
        "masaustunde klasor olustur",
    ),
    "OPEN_FOLDER": (
        "klasoru ac",
        "klasoru goster",
        "proje klasorunu ac",
    ),
    "CREATE_NOTE": (
        "not olustur",
        "not yaz",
        "not olarak kaydet",
        "masaustune not yaz",
        "icine metin yaz",
    ),
    "APPEND_TO_NOTE": (
        "son nota ekle",
        "notuma bunu ekle",
        "nota sunu ekle",
    ),
    "CREATE_CALENDAR_EVENT": (
        "takvime ekle",
        "randevu olustur",
        "toplanti takvime koy",
        "takvimde yarin icin sunum",
        "yarin sunum ekle",
    ),
    "CREATE_REMINDER": (
        "hatirlatici kur",
        "hatirlat",
        "bana hatirlat",
        "10 dakika sonra hatirlat",
    ),
    "LIST_REMINDERS": (
        "hatirlaticilari listele",
        "hatirlaticilarimi goster",
        "hatirlaticiyi acar misin",
        "kurdugum hatirlatmalari goster",
    ),
    "COMPLETE_REMINDER": (
        "hatirlaticiyi tamamla",
        "hatirlaticisini tamamlandi yap",
        "hatirlatmayi bitir",
    ),
    "ADD_TODO": (
        "yapilacaklara ekle",
        "todo ekle",
        "gorev listeme ekle",
    ),
    "LIST_TODOS": (
        "yapilacaklarimi goster",
        "gorevlerimi listele",
        "todo listesini ac",
    ),
    "COMPLETE_TODO": (
        "tamamlandi isaretle",
        "gorevi bitmis yap",
        "yapilacagi tamamla",
    ),
    "TAKE_SCREENSHOT": (
        "ekran goruntusu al",
        "ekran gorntusu al",
        "ekranin fotografini cek",
        "ekrani masaustune kaydet",
    ),
    "SEARCH_FILES": (
        "masaustunde dosya ara",
        "belgelerde dosya bul",
        "indirilenlerde pdf goster",
        "rapor dosyasini ara",
    ),
    "SYSTEM_INFO": (
        "pil yuzde kac",
        "diskte ne kadar bos yer var",
        "internet bagli mi",
    ),
    "VOLUME_UP": (
        "sesi artir",
        "ses yukari",
    ),
    "VOLUME_DOWN": (
        "sesi kis",
        "ses azalt",
    ),
    "MUTE_VOLUME": (
        "sesi kapat",
        "sessize al",
    ),
    "UNMUTE_VOLUME": (
        "sesi ac",
        "sessizi kapat",
    ),
    "PLAY_PAUSE_MEDIA": (
        "muzigi durdur",
        "devam ettir",
        "medyayi duraklat",
    ),
    "COPY_TEXT_TO_CLIPBOARD": (
        "panoya kopyala",
        "bu metni kopyala",
        "sunu panoya kopyala",
    ),
    "GENERAL_AI_ANSWER": (
        "nedir",
        "ne zaman",
        "nerede",
        "kim",
        "neden",
        "hangi",
        "ne amacla",
        "hangi tarihte",
        "hangi ulkede",
        "kim tarafindan",
        "ne ise yarar",
        "ne icin kullanilir",
        "ilk ne zaman",
        "ilk nerede",
        "tarihcesi",
        "gelisimi",
        "ortaya cikisi",
        "kullanim alani",
        "detayli anlat",
        "hakkinda bilgi ver",
        "nasil calisir",
        "aciklama yap",
        "merhaba nasilsin",
    ),
    "PRACTICAL_GUIDE": (
        "nasil yaparim",
        "ne kullanmaliyim",
        "hangi malzemeler",
        "nelere dikkat etmeliyim",
        "nasil sunmaliyim",
        "nasil kurarim",
    ),
    "RESEARCH_AND_EXPLAIN": (
        "kaynakli arastirma yap",
        "guncel kaynaklarla arastir",
        "internetten arastir ve anlat",
        "kaynaklariyla anlat",
    ),
    "LOCATION_INFO": (
        "konya hakkinda bilgi ver",
        "gezilecek yerler",
        "meramda ne yapilir",
        "istanbulda gezilecek",
    ),
    "ANSWER_ONLY_IN_SCOPE": (
        "ne yapabilirsin",
        "hangi islemleri yapiyorsun",
        "nasil calisiyorsun",
        "yardim",
    ),
}

UNSAFE_ALIASES = (
    "dosyalari sil",
    "dosyalari sill",
    "tum dosyalari sil",
    "masaustundeki dosyalari sil",
    "format at",
    "bilgisayari formatla",
    "cmd calistir",
    "powershell ac",
    "registry degistir",
    "sifreleri goster",
    "sistem ayarlarini degistir",
    "javascript alert",
    "file windows",
    "data url",
)

OUT_OF_SCOPE_ALIASES = ()


def interpret_command(raw_text: str, source: str = "voice") -> dict[str, Any]:
    cleaned_raw = _clean_spaces(raw_text)
    if not cleaned_raw:
        return {
            "raw_text": raw_text,
            "interpreted_text": "",
            "confidence": 0.0,
            "used_llm": False,
            "note": "Boş metin yorumlanamadı.",
        }

    if _can_skip_llm(cleaned_raw):
        fallback_text = _basic_fallback(cleaned_raw)
        return {
            "raw_text": raw_text,
            "interpreted_text": fallback_text,
            "confidence": 0.8,
            "used_llm": False,
            "note": "Basit komut yerel olarak yorumlandı.",
        }

    if OPENAI_API_KEY:
        try:
            return _interpret_with_llm(cleaned_raw, source)
        except Exception as exc:
            print(f"LLM yorumlama timeout/hata, fallback kullanıldı: {exc}", flush=True)
            pass

    fallback_text = _basic_fallback(cleaned_raw)
    return {
        "raw_text": raw_text,
        "interpreted_text": fallback_text,
        "confidence": 0.55 if fallback_text != cleaned_raw else 0.45,
        "used_llm": False,
        "note": "LLM kullanılamadı, sınırlı fallback düzeltmesi uygulandı.",
    }


def interpret_user_intent(user_text: str, source: str = "text") -> dict[str, Any]:
    """Route natural Turkish text to NOVA's safe action/tool categories."""
    cleaned = _clean_spaces(user_text)
    if not cleaned:
        return _intent_result("UNCLEAR", message=UNCLEAR_MESSAGE, confidence=0.0)

    normalized = _normalize_turkish(cleaned)

    unsafe_score = _best_score(normalized, UNSAFE_ALIASES)
    if unsafe_score >= 82 or _contains_unsafe_words(normalized) or _has_unsafe_url(cleaned):
        return _intent_result("UNSAFE_REQUEST", message=UNSAFE_MESSAGE, confidence=max(0.9, unsafe_score / 100))

    if _is_ambiguous_short_request(normalized):
        return _intent_result("UNCLEAR", message=UNCLEAR_MESSAGE, confidence=0.35)

    fast_path = _fast_path_intent(cleaned, normalized)
    if fast_path:
        return fast_path

    llm_result = route_with_llm(cleaned, registry_schema())
    if llm_result and (
        llm_result.get("confidence", 0) >= 0.6
        or llm_result.get("category")
        in {"UNSAFE_REQUEST", "NEEDS_CLARIFICATION", "OUT_OF_SCOPE_CHAT", "ANSWER_ONLY_IN_SCOPE"}
    ):
        normalized_llm = _normalize_intent_result(llm_result)
        if normalized_llm.get("category") == "NEEDS_CLARIFICATION" and not normalized_llm.get("action"):
            local_pending = _local_intent(cleaned, normalized)
            if local_pending and local_pending.get("category") == "NEEDS_CLARIFICATION":
                local_pending["message"] = normalized_llm.get("message") or local_pending.get("message", "")
                local_pending["spoken_message"] = normalized_llm.get("spoken_message") or local_pending.get("spoken_message", "")
                local_pending["provider"] = normalized_llm.get("provider", "gemini")
                local_pending["used_llm_router"] = True
                return local_pending
        if normalized_llm.get("action") == "ACADEMIC_SEARCH" and _is_official_info_request(normalized):
            official_intent = _official_info_intent(cleaned, normalized)
            if official_intent:
                return official_intent
        if normalized_llm.get("category") in {"OUT_OF_SCOPE_CHAT", "ANSWER_ONLY_IN_SCOPE", "UNCLEAR"}:
            local_fallback = _fallback_intent(cleaned, normalized)
            if local_fallback and local_fallback.get("category") == "DESKTOP_ACTION":
                local_fallback["provider"] = "local_intent_override"
                return local_fallback
        return normalized_llm

    fallback = _fallback_intent(cleaned, normalized)
    if fallback:
        return fallback

    return _intent_result("UNCLEAR", message=UNCLEAR_MESSAGE, confidence=0.35)


def _fallback_intent(cleaned: str, normalized: str) -> dict[str, Any] | None:
    """Limited local keyword/fuzzy fallback used only when the LLM router is unavailable."""
    web_intent = detect_web_intent(cleaned, normalized)
    if web_intent:
        return web_intent

    answer_intent = detect_answer_intent(cleaned, normalized)
    if answer_intent:
        return answer_intent

    local = _local_intent(cleaned, normalized)
    if local:
        return local
    return None


def detect_answer_intent(text: str, normalized: str | None = None) -> dict[str, Any] | None:
    normalized_text = normalized or _normalize_turkish(text)
    if _contains_general_unsafe(normalized_text):
        return _intent_result(
            "DESKTOP_ACTION",
            action="UNSAFE_OR_BLOCKED",
            args={
                "message": (
                    "Bu konuda yardımcı olamam. Sistem güvenliği ve kullanıcı verilerini korumak için "
                    "bu tür işlemler desteklenmiyor."
                )
            },
            confidence=0.96,
        )

    if _is_ambiguous_short_request(normalized_text):
        return None

    if _contains_any(normalized_text, ("guncel kaynak", "kaynakli arastirma", "kaynaklariyla", "internetten arastir", "arastirma yap")):
        return _intent_result("DESKTOP_ACTION", action="RESEARCH_AND_EXPLAIN", args={"topic": text}, confidence=0.88)

    if _contains_any(normalized_text, ("gezilecek yer", "konya", "istanbul", "meram", "selcuk universitesi")) and _contains_any(
        normalized_text,
        (
            "bilgi",
            "hakkinda",
            "gezilecek",
            "ne yapilir",
            "arastir",
            "hangi medeniyet",
            "ev sahipligi",
            "ne zaman",
            "nerede",
            "tarihcesi",
            "kim tarafindan",
        ),
    ):
        if _contains_any(normalized_text, ("guncel", "kaynak", "arastir")):
            return _intent_result("DESKTOP_ACTION", action="RESEARCH_AND_EXPLAIN", args={"topic": text}, confidence=0.86)
        return _intent_result("DESKTOP_ACTION", action="LOCATION_INFO", args={"topic": text}, confidence=0.86)

    if _contains_any(
        normalized_text,
        ("yapacagim", "yapacağım", "ne kullanmaliyim", "hangi malzemeler", "nelere dikkat", "nasil sunmaliyim", "nasil kurarim", "nasil yaparim"),
    ):
        return _intent_result("DESKTOP_ACTION", action="PRACTICAL_GUIDE", args={"question": text}, confidence=0.86)

    if _is_general_information_question(normalized_text):
        return _intent_result("DESKTOP_ACTION", action="GENERAL_AI_ANSWER", args={"question": text, "mode": "general"}, confidence=0.84)

    if _contains_any(
        normalized_text,
        ("nedir", "nasil calisir", "detayli anlat", "hakkinda bilgi", "bilgi ver", "aciklama yap", "merhaba", "nasilsin", "ne yesem", "film oner"),
    ):
        return _intent_result("DESKTOP_ACTION", action="GENERAL_AI_ANSWER", args={"question": text, "mode": "general"}, confidence=0.82)

    return None


def _is_general_information_question(normalized_text: str) -> bool:
    if _looks_like_desktop_action_request(normalized_text):
        return False

    markers = (
        "ne zaman",
        "nerede",
        "kim",
        "neden",
        "nasil",
        "ne amacla",
        "hangi",
        "ilk ne zaman",
        "ilk nerede",
        "hangi tarihte",
        "hangi ulkede",
        "ne icin kullanil",
        "ne ise yarar",
        "kim tarafindan",
        "tarihcesi",
        "gelisimi",
        "ortaya cikisi",
        "kullanim alani",
        "kullanim alanlari",
    )
    if not _contains_any(normalized_text, markers):
        return False

    words = [word for word in normalized_text.split() if len(word) > 1]
    if len(words) < 3:
        return False

    return True


def _looks_like_desktop_action_request(normalized_text: str) -> bool:
    desktop_markers = (
        "masaustunde",
        "masaustune",
        "belgelerime",
        "indirilenler",
        "resimler",
        "klasor olustur",
        "klasoru olustur",
        "klasorunu olustur",
        "klasor ac",
        "klasoru ac",
        "klasorunu ac",
        "dosya olustur",
        "not olustur",
        "not kaydet",
        "uygulama ac",
        "not defteri",
        "hesap makinesi",
        "paint",
        "chrome ac",
        "web sitesi ac",
        "siteyi ac",
        "sitesini ac",
        "takvime",
        "hatirlatici",
        "yapilacak",
        "ekran goruntusu",
        "panoya kopyala",
        "sesi artir",
        "sesi kis",
    )
    return _contains_any(normalized_text, desktop_markers)


def _is_ambiguous_short_request(normalized_text: str) -> bool:
    cleaned = normalized_text.strip(" ?!.")
    ambiguous = {
        "sey yap",
        "bir sey yap",
        "onu ac",
        "bunu ac",
        "bunu hallet",
        "oraya koy",
        "sunu yap",
        "hallet",
    }
    if cleaned in ambiguous:
        return True
    return len(cleaned.split()) <= 2 and cleaned in {"ac", "yap", "koy", "hallet"}


def _fast_path_intent(user_text: str, normalized: str) -> dict[str, Any] | None:
    """Resolve tiny, high-confidence commands without waiting for the LLM."""
    folder_intent = _direct_folder_intent(user_text, normalized)
    if folder_intent:
        return folder_intent

    if _contains_any(normalized, ("akademik", "makale", "bilimsel", "literatur", "paper", "yayin", "kaynakca")):
        return None

    if _best_score(normalized, ("saat kac", "sat kac", "saat kc", "bugunun tarihi ne", "bugun gunlerden ne")) >= 78:
        return _intent_result(
            "DESKTOP_ACTION",
            action="DATE_TIME_ANSWER",
            args=_extract_args_for_action("DATE_TIME_ANSWER", user_text, normalized),
            confidence=0.95,
        )

    if _best_score(normalized, ("google ac", "googlea gir", "gogle ac", "gogle gir")) >= 82:
        return _intent_result("DESKTOP_ACTION", action="OPEN_WEBSITE", args={"site": "google"}, confidence=0.95)

    app_fast_paths = {
        "not defteri": ("not defterini ac", "not defteri ac", "not deftrini ac"),
        "hesap makinesi": ("hesap makinesini ac", "hesap makinesi ac", "hesap maknesi ac"),
    }
    for app_name, aliases in app_fast_paths.items():
        if _best_score(normalized, aliases) >= 82:
            return _intent_result(
                "DESKTOP_ACTION",
                action="OPEN_COMMON_APP",
                args={"app_name": app_name},
                confidence=0.95,
            )

    if _best_score(normalized, ("ekran goruntusu al", "ekran gorntusu al", "ekrandaki goruntuyu kaydet")) >= 78:
        return _intent_result("DESKTOP_ACTION", action="TAKE_SCREENSHOT", args={}, confidence=0.95)

    return None


def detect_web_intent(text: str, normalized: str | None = None) -> dict[str, Any] | None:
    normalized_text = normalized or _normalize_turkish(text)
    raw_url = _extract_raw_url(text)
    topic = extract_web_topic(text)

    if _has_unsafe_url(text):
        return _intent_result("UNSAFE_REQUEST", message=UNSAFE_MESSAGE, confidence=0.98)

    if raw_url and _contains_any(normalized_text, ("ozetle", "oku", "incele")):
        return _intent_result("DESKTOP_ACTION", action="SUMMARIZE_URL", args={"url": raw_url}, confidence=0.96)

    if raw_url and _contains_any(normalized_text, ("ac", "gir", "baslat")):
        return _intent_result("DESKTOP_ACTION", action="OPEN_WEBSITE", args={"url": raw_url}, confidence=0.94)

    official_intent = _official_info_intent(text, normalized_text)
    if official_intent:
        return official_intent

    academic_intent = detect_academic_intent(text, normalized_text)
    if academic_intent:
        return academic_intent

    if (
        _contains_any(normalized_text, ("guncel kaynak", "kaynakli", "kaynaklarla", "kaynaklariyla"))
        and _contains_any(normalized_text, ("arastir", "anlat", "acikla", "bilgi"))
        and not _contains_any(normalized_text, ("kaydet", "dosyaya", "masaustune", "rapor"))
    ):
        return _intent_result("DESKTOP_ACTION", action="RESEARCH_AND_EXPLAIN", args={"topic": text}, confidence=0.9)

    if (
        _contains_any(normalized_text, ("rapor", "kaydet", "dosyaya", "masaustune", "rapor hazirla", "rapor cikar"))
        and _contains_any(normalized_text, ("arastir", "ozetle", "haber", "gelisme", "hazirla", "cikar", "toparla"))
    ):
        return _web_topic_result("WEB_RESEARCH_SAVE", topic, confidence=0.92, save=True)

    if (
        _contains_any(normalized_text, ("son", "guncel", "haber", "gelisme", "gundem"))
        and _contains_any(normalized_text, ("ozetle", "arastir", "haber", "gelisme"))
    ):
        return _web_topic_result("LATEST_NEWS_BY_TOPIC", topic, confidence=0.9)

    if _contains_any(
        normalized_text,
        ("ozetle", "arastir", "bilgi topla", "kisa arastirma", "internetten", "toparla", "bakip"),
    ):
        return _web_topic_result("WEB_RESEARCH_SUMMARY", topic, confidence=0.88)

    if _contains_any(normalized_text, (" ara", " arat", " arama", " internette ara", "webde ara")):
        return _web_topic_result("WEB_SEARCH", topic, confidence=0.82, query=True)

    return None


def detect_academic_intent(text: str, normalized: str | None = None) -> dict[str, Any] | None:
    normalized_text = normalized or _normalize_turkish(text)
    academic_markers = (
        "akademik",
        "makale",
        "makaleler",
        "bilimsel",
        "literatur",
        "literatur taramasi",
        "paper",
        "yayin",
        "yayinlari",
        "kaynakca",
        "kaynaklariyla",
    )
    if not _contains_any(normalized_text, academic_markers):
        return None

    topic = extract_web_topic(text)
    topic = re.sub(
        r"\b(google[’'`]?\s*a|googlea|girip|bana|ile\s+ilgili|ilgili|akademik|makale(?:ler)?|bilimsel|literatür|literatur|paper|yayın(?:ları)?|yayin(?:lari)?|kaynak(?:ları|lari)?|kaynakça|kaynakca|kaynaklarıyla|kaynaklariyla|olarak|bul|bulabilir\s+misin|misin|göster|goster)\b",
        " ",
        topic,
        flags=re.IGNORECASE,
    )
    topic = _clean_spaces(topic).strip(" .:\"'")
    if not topic:
        return _intent_result(
            "NEEDS_CLARIFICATION",
            action="ACADEMIC_SEARCH",
            args={},
            message="Hangi konuda akademik kaynak aramamı istersiniz?",
            confidence=0.92,
        )

    save_to_file = _contains_any(normalized_text, ("masaustune", "kaydet", "rapor", "dosyaya", "dosyaya yaz"))
    return _intent_result(
        "DESKTOP_ACTION",
        action="ACADEMIC_SEARCH",
        args={
            "topic": topic,
            "max_results": "5",
            "save_to_file": "true" if save_to_file else "false",
            "summary_level": "medium",
        },
        confidence=0.94,
    )


def _is_official_info_request(normalized: str) -> bool:
    return (
        _contains_any(normalized, ("akademik takvim", "resmi", "universite", "universitesi"))
        and _contains_any(normalized, ("arastir", "bul", "bak", "var mi", "resmi siteden", "resmi kaynaktan", "resmi kaynak"))
    )


def _official_info_intent(text: str, normalized: str) -> dict[str, Any] | None:
    if not _is_official_info_request(normalized):
        return None
    return _web_topic_result("OFFICIAL_INFO_SEARCH", extract_web_topic(text), confidence=0.92)


def _intent_with_llm(user_text: str, source: str) -> dict[str, Any]:
    from openai import OpenAI

    start = perf_counter()
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": INTENT_PROMPT},
            {"role": "user", "content": f"Kaynak: {source}\nKomut: {user_text}"},
        ],
        text={"format": {"type": "json_object"}},
    )
    print(f"[PERF] LLM intent router: {perf_counter() - start:.1f} sn", flush=True)
    return _normalize_intent_result(json.loads(response.output_text))


def extract_web_topic(text: str) -> str:
    cleaned = re.sub(r"https?://\S+|javascript:\S+|file://\S+|data:\S+", " ", str(text or ""), flags=re.IGNORECASE)
    if ":" in cleaned:
        after_colon = _clean_spaces(cleaned.rsplit(":", 1)[-1])
        if after_colon:
            cleaned = after_colon
    stop_patterns = (
        r"\binternetten\b",
        r"\bwebden\b",
        r"\bbiraz\b",
        r"\bkonusunu\b",
        r"\bkonuyu\b",
        r"\baraştırma\s+yap\b",
        r"\baraştır\b",
        r"\barastirma\s+yap\b",
        r"\barastir\b",
        r"\baraştırıp\b",
        r"\barastirip\b",
        r"\bbakıp\b",
        r"\bbakip\b",
        r"\bbak\b",
        r"\btoparlar\s+mısın\b",
        r"\btoparlar\s+misin\b",
        r"\btoparla\b",
        r"\bözetle\b",
        r"\bozetle\b",
        r"\bözet\s+geç\b",
        r"\bozet\s+gec\b",
        r"\bhakkında\b",
        r"\bhakkinda\b",
        r"\bkısa\b",
        r"\bkisa\b",
        r"\brapor\b",
        r"\bçıkar\b",
        r"\bcikar\b",
        r"\bhazırla\b",
        r"\bhazirla\b",
        r"\bkaynaklı\b",
        r"\bkaynakli\b",
        r"\bmasaüstüne\b",
        r"\bmasaustune\b",
        r"\bkaydet\b",
        r"\bdosyaya\b",
        r"\bson\b",
        r"\bhaberlerini\b",
        r"\bhaberleri\b",
        r"\bgelişmeleri\b",
        r"\bgelismeleri\b",
        r"\bresmi\s+siteden\b",
        r"\bresmi\s+kaynaktan\b",
        r"\bresmi\s+kaynakta\b",
        r"\bresmi\s+kaynak\b",
        r"\bbul\b",
        r"\bnedir\b",
        r"\bne\s+işe\s+yarıyor\b",
        r"\bne\s+ise\s+yariyor\b",
        r"\byap\b",
        r"\bve\b",
    )
    for pattern in stop_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\btakvimini\b", "takvimi", cleaned, flags=re.IGNORECASE)
    return _clean_spaces(cleaned).strip(" .:\"'")


def _web_topic_result(
    action: str,
    topic: str,
    confidence: float,
    save: bool = False,
    query: bool = False,
) -> dict[str, Any]:
    if not topic:
        return _intent_result(
            "NEEDS_CLARIFICATION",
            action=action,
            args={},
            message="Hangi konuyu araştırmamı istersiniz?",
            confidence=0.9,
        )
    if query:
        args = {"query": topic}
    elif save:
        args = {"topic": topic, "file_name": _safe_file_name(topic + "_rapor")}
    else:
        args = {"topic": topic}
    return _intent_result("DESKTOP_ACTION", action=action, args=args, confidence=confidence)


def _local_intent(user_text: str, normalized: str) -> dict[str, Any] | None:
    out_of_scope_score = _best_score(normalized, OUT_OF_SCOPE_ALIASES)
    if out_of_scope_score >= 78:
        return _intent_result("OUT_OF_SCOPE_CHAT", message=OUT_OF_SCOPE_MESSAGE, confidence=out_of_scope_score / 100)

    marker_intent = _marker_based_intent(user_text, normalized)
    if marker_intent:
        return marker_intent

    action, score, runner_up = _best_action(normalized)
    if not action or score < 72:
        return None
    if runner_up and score - runner_up[1] < 5:
        return _intent_result("UNCLEAR", message=UNCLEAR_MESSAGE, confidence=score / 100)

    if action == "ANSWER_ONLY_IN_SCOPE":
        return _intent_result(
            "ANSWER_ONLY_IN_SCOPE",
            action=None,
            message=(
                "Klasör oluşturabilir, uygulama ve web sitesi açabilir, not, hatırlatıcı, "
                "takvim etkinliği ve yapılacak ekleyebilir, ekran görüntüsü alabilir ve saat/tarih bilgisi verebilirim."
            ),
            confidence=score / 100,
        )

    args = _extract_args_for_action(action, user_text, normalized)
    clarification = _clarification_for_action(action, args, normalized)
    if clarification:
        return _intent_result(
            "NEEDS_CLARIFICATION",
            action=action,
            args=args,
            message=clarification,
            confidence=max(0.78, score / 100),
        )

    return _intent_result("DESKTOP_ACTION", action=action, args=args, confidence=score / 100)


def _marker_based_intent(user_text: str, normalized: str) -> dict[str, Any] | None:
    folder_intent = _direct_folder_intent(user_text, normalized)
    if folder_intent:
        return folder_intent

    has_date_hint = any(
        word in normalized for word in ("bugun", "yarin", "saat", "pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar")
    )
    has_calendar_hint = any(word in normalized for word in ("takvim", "randevu", "toplanti", "sunum", "etkinlik")) and any(
        word in normalized for word in ("ekle", "koy", "olustur", "var", "icin")
    )
    if has_date_hint and has_calendar_hint:
        args = _calendar_args(user_text, normalized)
        clarification = _clarification_for_action("CREATE_CALENDAR_EVENT", args, normalized)
        if clarification:
            return _intent_result("NEEDS_CLARIFICATION", action="CREATE_CALENDAR_EVENT", args=args, message=clarification, confidence=0.9)
        return _intent_result("DESKTOP_ACTION", action="CREATE_CALENDAR_EVENT", args=args, confidence=0.9)

    if "hatirlat" in normalized:
        if "tamam" in normalized or "bitir" in normalized or "bitmis" in normalized:
            return _intent_result("DESKTOP_ACTION", action="COMPLETE_REMINDER", args=_extract_args_for_action("COMPLETE_REMINDER", user_text, normalized), confidence=0.88)
        if "liste" in normalized or "goster" in normalized or "ac" in normalized:
            return _intent_result("DESKTOP_ACTION", action="LIST_REMINDERS", args={}, confidence=0.9)
        args = _reminder_args(user_text, normalized)
        clarification = _clarification_for_action("CREATE_REMINDER", args, normalized)
        if clarification:
            return _intent_result("NEEDS_CLARIFICATION", action="CREATE_REMINDER", args=args, message=clarification, confidence=0.86)
        return _intent_result("DESKTOP_ACTION", action="CREATE_REMINDER", args=args, confidence=0.86)

    if "not" in normalized and any(word in normalized for word in ("olustur", "kaydet", "yaz")):
        args = _note_args(user_text, normalized)
        clarification = _clarification_for_action("CREATE_NOTE", args, normalized)
        if clarification:
            return _intent_result("NEEDS_CLARIFICATION", action="CREATE_NOTE", args=args, message=clarification, confidence=0.9)
        return _intent_result("DESKTOP_ACTION", action="CREATE_NOTE", args=args, confidence=0.9)

    if "not" in normalized and "ekle" in normalized:
        args = _append_note_args(user_text)
        clarification = _clarification_for_action("APPEND_TO_NOTE", args, normalized)
        if clarification:
            return _intent_result("NEEDS_CLARIFICATION", action="APPEND_TO_NOTE", args=args, message=clarification, confidence=0.86)
        return _intent_result("DESKTOP_ACTION", action="APPEND_TO_NOTE", args=args, confidence=0.86)

    if "proje" in normalized and any(word in normalized for word in ("yapi", "yapisi", "klasor", "olustur")):
        return _intent_result(
            "DESKTOP_ACTION",
            action="CREATE_PROJECT_STRUCTURE",
            args=_project_structure_args(user_text, normalized),
            confidence=0.88,
        )

    if "yapilacak" in normalized or "todo" in normalized or "gorev" in normalized:
        if "liste" in normalized or "goster" in normalized:
            return _intent_result("DESKTOP_ACTION", action="LIST_TODOS", args={}, confidence=0.88)
        if "tamam" in normalized or "bit" in normalized:
            return _intent_result("DESKTOP_ACTION", action="COMPLETE_TODO", args=_extract_args_for_action("COMPLETE_TODO", user_text, normalized), confidence=0.86)
        if "ekle" in normalized:
            return _intent_result("DESKTOP_ACTION", action="ADD_TODO", args=_extract_args_for_action("ADD_TODO", user_text, normalized), confidence=0.86)

    if "dosya" in normalized and any(word in normalized for word in ("ara", "bul", "goster")):
        args = _search_file_args(user_text, normalized)
        clarification = _clarification_for_action("SEARCH_FILES", args, normalized)
        if clarification:
            return _intent_result("NEEDS_CLARIFICATION", action="SEARCH_FILES", args=args, message=clarification, confidence=0.86)
        return _intent_result("DESKTOP_ACTION", action="SEARCH_FILES", args=args, confidence=0.86)

    if "ekran" in normalized and any(word in normalized for word in ("goruntu", "goruntusu", "fotograf", "kaydet", "cek")):
        return _intent_result("DESKTOP_ACTION", action="TAKE_SCREENSHOT", args={}, confidence=0.88)

    if any(word in normalized for word in ("pil", "disk", "internet")) and any(
        word in normalized for word in ("kac", "durum", "bagli", "bos", "alan", "var")
    ):
        return _intent_result("DESKTOP_ACTION", action="SYSTEM_INFO", args={"topic": user_text}, confidence=0.88)

    return None


def _best_action(normalized: str) -> tuple[str | None, float, tuple[str, float] | None]:
    scores: list[tuple[str, float]] = []
    for action, aliases in ACTION_ALIASES.items():
        alias_scores = [
            max(
                fuzz.token_set_ratio(normalized, alias),
                fuzz.partial_ratio(normalized, alias),
            )
            for alias in aliases
        ]
        scores.append((action, float(max(alias_scores or [0]))))
    scores.sort(key=lambda item: item[1], reverse=True)
    best = scores[0] if scores else (None, 0.0)
    runner_up = scores[1] if len(scores) > 1 else None
    return best[0], best[1], runner_up


def _best_score(normalized: str, aliases: tuple[str, ...]) -> float:
    if not aliases:
        return 0.0
    return float(max(max(fuzz.token_set_ratio(normalized, alias), fuzz.partial_ratio(normalized, alias)) for alias in aliases))


def _extract_args_for_action(action: str, user_text: str, normalized: str) -> dict[str, str]:
    if action == "DATE_TIME_ANSWER":
        if "sat" in normalized or "saat" in normalized or "kac" in normalized:
            return {"question": "saat kaç"}
        if "gunlerden" in normalized:
            return {"question": "bugün günlerden ne"}
        return {"question": user_text}
    if action == "OPEN_WEBSITE":
        return _website_args(user_text, normalized)
    if action == "WEB_SEARCH":
        return {"query": _strip_intent_words(user_text) or user_text}
    if action == "ACADEMIC_SEARCH":
        detected = detect_academic_intent(user_text, normalized)
        return detected.get("args", {}) if detected else {"topic": _strip_intent_words(user_text) or user_text}
    if action == "GENERAL_AI_ANSWER":
        return {"question": user_text, "mode": "general"}
    if action == "RESEARCH_AND_EXPLAIN":
        return {"topic": user_text}
    if action == "PRACTICAL_GUIDE":
        return {"question": user_text}
    if action == "LOCATION_INFO":
        return {"topic": user_text}
    if action == "OPEN_COMMON_APP":
        return {"app_name": _app_name(normalized)}
    if action == "OPEN_SPECIAL_FOLDER":
        return {"folder": _special_folder(normalized)}
    if action == "CREATE_FOLDER":
        return {"path": _folder_name(user_text) or "YeniKlasor"}
    if action == "OPEN_FOLDER":
        return {"path": _folder_name(user_text) or "Projeler"}
    if action == "CREATE_NOTE":
        return _note_args(user_text, normalized)
    if action == "APPEND_TO_NOTE":
        return _append_note_args(user_text)
    if action == "CREATE_CALENDAR_EVENT":
        return _calendar_args(user_text, normalized)
    if action == "CREATE_REMINDER":
        return _reminder_args(user_text, normalized)
    if action == "CREATE_PROJECT_STRUCTURE":
        return _project_structure_args(user_text, normalized)
    if action in {"LIST_REMINDERS", "LIST_TODOS", "TAKE_SCREENSHOT", "VOLUME_UP", "VOLUME_DOWN", "MUTE_VOLUME", "UNMUTE_VOLUME", "PLAY_PAUSE_MEDIA"}:
        return {}
    if action == "COMPLETE_REMINDER":
        return {"title": _clean_completion_title(user_text)}
    if action == "ADD_TODO":
        title = re.sub(r"\b(yapılacaklara|yapilacaklara|yapılacaklarıma|yapilacaklarima|todo|görev|gorev|listeme|ekle)\b", "", user_text, flags=re.IGNORECASE)
        return {"title": _clean_spaces(title) or "Yeni görev"}
    if action == "COMPLETE_TODO":
        return {"title": _clean_completion_title(user_text)}
    if action == "SEARCH_FILES":
        return _search_file_args(user_text, normalized)
    if action == "SYSTEM_INFO":
        return {"topic": user_text}
    if action == "COPY_TEXT_TO_CLIPBOARD":
        return {"text": _clipboard_text(user_text)}
    return {}


def _clarification_for_action(action: str, args: dict[str, str], normalized: str) -> str | None:
    if action == "CREATE_CALENDAR_EVENT":
        if not args.get("when"):
            return "Tarih bilgisini belirtir misiniz?"
        if not _has_time(normalized):
            return "Saat bilgisini belirtir misiniz?"
    if action == "CREATE_REMINDER" and not _has_time_or_relative(normalized):
        return "Ne zaman hatırlatmamı istersiniz?"
    if action == "CREATE_NOTE" and not args.get("content"):
        return "Nota ne yazmamı istersiniz?"
    if action == "APPEND_TO_NOTE" and not args.get("content"):
        return "Nota hangi metni eklememi istersiniz?"
    if action == "SEARCH_FILES" and not args.get("query"):
        return "Hangi dosyayı aramamı istersiniz?"
    if action == "ACADEMIC_SEARCH" and not args.get("topic"):
        return "Hangi konuda akademik kaynak aramamı istersiniz?"
    if action == "COPY_TEXT_TO_CLIPBOARD" and not args.get("text"):
        return "Panoya hangi metni kopyalamamı istersiniz?"
    return None


def _normalize_intent_result(raw: dict[str, Any]) -> dict[str, Any]:
    category = str(raw.get("category", "UNCLEAR")).strip().upper()
    if category not in {
        "DESKTOP_ACTION",
        "ANSWER_ONLY_IN_SCOPE",
        "OUT_OF_SCOPE_CHAT",
        "UNSAFE_REQUEST",
        "NEEDS_CLARIFICATION",
        "UNCLEAR",
    }:
        category = "UNCLEAR"

    action = raw.get("action")
    action = None if action in {None, "", "null", "NULL"} else str(action).strip().upper()
    args = raw.get("args", {}) if isinstance(raw.get("args", {}), dict) else {}
    message = _clean_spaces(raw.get("message", ""))
    spoken_message = _clean_spaces(raw.get("spoken_message", "")) or message

    if category == "OUT_OF_SCOPE_CHAT":
        message = spoken_message = OUT_OF_SCOPE_MESSAGE
    elif category == "UNSAFE_REQUEST":
        message = spoken_message = UNSAFE_MESSAGE
    elif category == "UNCLEAR":
        message = spoken_message = message or UNCLEAR_MESSAGE
    elif category == "NEEDS_CLARIFICATION":
        message = spoken_message = message or "Biraz daha bilgi verir misiniz?"

    result = _intent_result(
        category=category,
        action=action,
        args={key: str(value).strip() for key, value in args.items() if str(value).strip()},
        message=message,
        spoken_message=spoken_message,
        confidence=_clamp_confidence(raw.get("confidence", 0.6)),
    )
    if raw.get("provider"):
        result["provider"] = str(raw.get("provider"))
    if raw.get("used_llm_router"):
        result["used_llm_router"] = True
    return result


def _interpret_with_llm(raw_text: str, source: str) -> dict[str, Any]:
    from openai import OpenAI

    start = perf_counter()
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": INTERPRETER_PROMPT},
            {"role": "user", "content": f"Kaynak: {source}\nHam metin: {raw_text}"},
        ],
        text={"format": {"type": "json_object"}},
    )
    data = json.loads(response.output_text)
    print(f"[PERF] LLM komut yorumlama: {perf_counter() - start:.1f} sn", flush=True)
    interpreted_text = _clean_spaces(str(data.get("interpreted_text", raw_text)))
    confidence = _clamp_confidence(data.get("confidence", 0.7))
    note = _clean_spaces(str(data.get("note", "LLM ile yorumlandı.")))

    if not interpreted_text:
        interpreted_text = raw_text
        confidence = 0.2
        note = "LLM boş yorum döndürdüğü için ham metin korundu."

    return {
        "raw_text": raw_text,
        "interpreted_text": interpreted_text,
        "confidence": confidence,
        "used_llm": True,
        "note": note,
    }


def _can_skip_llm(text: str) -> bool:
    normalized = _normalize_turkish(text)
    fast_signals = (
        "saat kac",
        "bugunun tarihi",
        "bugun gunlerden",
        "google",
        "youtube",
        "github",
        "not defteri",
        "hesap makinesi",
        "masaustunu ac",
        "belgeler",
        "indirilenler",
        "merhaba",
        "nasilsin",
        "sil",
        "format",
        "cmd",
        "powershell",
    )
    return any(signal in normalized for signal in fast_signals)


def _basic_fallback(text: str) -> str:
    fixed = _clean_spaces(text)
    replacements = (
        (r"\bmasaya\s+üstünde\b", "Masaüstünde"),
        (r"\bmasaya\s+ustunde\b", "Masaüstünde"),
        (r"\bmasa\s+üstünde\b", "Masaüstünde"),
        (r"\bmasa\s+ustunde\b", "Masaüstünde"),
    )
    for pattern, replacement in replacements:
        fixed = re.sub(pattern, replacement, fixed, flags=re.IGNORECASE)
    return _clean_spaces(fixed)


def _intent_result(
    category: str,
    action: str | None = None,
    args: dict[str, str] | None = None,
    message: str = "",
    spoken_message: str = "",
    confidence: float = 0.5,
) -> dict[str, Any]:
    if category == "OUT_OF_SCOPE_CHAT":
        message = spoken_message = OUT_OF_SCOPE_MESSAGE
    elif category == "UNSAFE_REQUEST":
        message = spoken_message = UNSAFE_MESSAGE
    elif category == "UNCLEAR":
        message = spoken_message = message or UNCLEAR_MESSAGE
    elif category == "NEEDS_CLARIFICATION":
        spoken_message = spoken_message or message
    return {
        "category": category,
        "action": action,
        "args": args or {},
        "message": message,
        "spoken_message": spoken_message or message,
        "confidence": _clamp_confidence(confidence),
    }


def _contains_unsafe_words(normalized: str) -> bool:
    destructive = ("sil", "sill", "format", "cmd", "powershell", "registry", "regedit", "sifre", "parola", "javascript", "file", "data", "zararli yazilim", "gizlice veri", "izinsiz sisteme")
    return any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in destructive)


def _contains_general_unsafe(normalized: str) -> bool:
    return _contains_any(
        normalized,
        (
            "zararli yazilim",
            "malware",
            "sifre cal",
            "sifreleri goster",
            "izinsiz gir",
            "gizlice veri",
            "antivirusu kapat",
            "kayit defterini degistir",
            "registry degistir",
        ),
    )


def _has_unsafe_url(text: str) -> bool:
    lowered = str(text or "").casefold()
    if any(token in lowered for token in ("javascript:", "file:", "data:", "localhost", "127.0.0.1")):
        return True
    match = _extract_raw_url(text)
    if not match:
        return False
    parsed = urlparse(match if "://" in match else "https://" + match)
    host = (parsed.hostname or "").casefold()
    return host in {"localhost", "127.0.0.1", "::1"}


def _extract_raw_url(text: str) -> str:
    match = re.search(r"\b(?:https?://|javascript:|file://|data:)\S+", str(text or ""), re.IGNORECASE)
    if match:
        return match.group(0).strip(" .,;\"'")
    domain = re.search(r"\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+\b", str(text or ""))
    return domain.group(0).strip(" .,;\"'") if domain else ""


def _contains_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(signal in text for signal in signals)


def _website_args(user_text: str, normalized: str) -> dict[str, str]:
    known = {
        "google": "google",
        "gogle": "google",
        "youtube": "youtube",
        "yutube": "youtube",
        "github": "github",
        "selcuk universitesi": "selçuk üniversitesi",
        "cecihome": "cecihome",
        "ceci home": "cecihome",
        "cecihome com tr": "cecihome.com.tr",
    }
    for key, site in known.items():
        if key in normalized or fuzz.partial_ratio(normalized, key) >= 86:
            return {"site": site}
    domain_match = re.search(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", normalized)
    if domain_match:
        return {"url": domain_match.group(1)}
    words = _strip_intent_words(user_text)
    return {"site": words or user_text}


def _app_name(normalized: str) -> str:
    candidates = {
        "not defteri": ("not defteri", "not deftrini", "notepad"),
        "hesap makinesi": ("hesap makinesi", "hesap maknesi", "calculator"),
        "paint": ("paint",),
        "vs code": ("vscode", "vs code", "visual studio code"),
        "chrome": ("chrome", "google chrome"),
        "word": ("word", "microsoft word"),
        "excel": ("excel", "microsoft excel"),
        "powerpoint": ("powerpoint", "power point", "microsoft powerpoint"),
        "dosya gezgini": ("dosya gezgini", "file explorer", "explorer"),
    }
    best_name = "not defteri"
    best_score = 0.0
    for app_name, aliases in candidates.items():
        score = _best_score(normalized, aliases)
        if score > best_score:
            best_name = app_name
            best_score = score
    return best_name


def _special_folder(normalized: str) -> str:
    folders = {
        "desktop": ("masaustu", "masaustunu", "desktop"),
        "documents": ("belgeler", "belgelerimi", "documents"),
        "downloads": ("indirilenler", "downloads"),
        "pictures": ("resimler", "pictures"),
    }
    best_folder = "desktop"
    best_score = 0.0
    for folder, aliases in folders.items():
        score = _best_score(normalized, aliases)
        if score > best_score:
            best_folder = folder
            best_score = score
    return best_folder


def _direct_folder_intent(user_text: str, normalized: str) -> dict[str, Any] | None:
    if "klasor" not in normalized and "klasör" not in user_text.casefold():
        return None

    create_words = ("olustur", "oluştur", "yeni", "kur", "yap")
    open_words = ("goster", "göster", "ac", "aç")

    wants_create = _contains_any(normalized, create_words)
    wants_open = _contains_any(normalized, open_words)

    # Türkçede "klasör aç" çoğu zaman "yeni klasör oluştur" anlamında kullanılır.
    # Bu yüzden masaüstünde/masaüstüne + klasör aç ifadesini, açıkça gösterme yoksa oluşturma sayıyoruz.
    if not wants_create and wants_open and _contains_any(normalized, ("masaustunde", "masaustune", "desktop")) and not _contains_any(normalized, ("goster", "göster", "var olan")):
        wants_create = True

    if not wants_create and not wants_open:
        return None

    folder_name = _folder_name(user_text)
    if not folder_name:
        folder_name = "NOVA Sunum" if "sunum" in normalized else "Yeni Klasor"

    action = "CREATE_FOLDER" if wants_create else "OPEN_FOLDER"
    return _intent_result("DESKTOP_ACTION", action=action, args={"path": folder_name}, confidence=0.98)


def _folder_name(user_text: str) -> str:
    text = _clean_spaces(user_text).strip(" .\"'")

    # Ses tanımada sık gelen birleşmeler: "masaüstünesunum" -> "masaüstüne sunum"
    text = re.sub(r"(masa[üu]st[üu]ne)(?=\S)", r"\1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"(masa[üu]st[üu]nde)(?!ki)(?=\S)", r"\1 ", text, flags=re.IGNORECASE)
    text = re.sub(r"(masaustu(?:ne|nde))(?!ki)(?=\S)", r"\1 ", text, flags=re.IGNORECASE)

    # Örn: Masaüstünde NOVA Sunum adında yeni bir klasör oluştur
    match = re.search(
        r"(?:masa[üu]st[üu]ndeki|masa[üu]st[üu]nde|masa[üu]st[üu]ne|desktop(?:ta|te)?|desktop['’]?a)?\s*"
        r"(?P<name>.+?)\s+"
        r"(?:ad[ıi]nda\s+|isimli\s+)?(?:yeni\s+bir\s+|yeni\s+)?"
        r"klas[öo]r(?:ü|ünü|u|unu)?\s*"
        r"(?:oluştur|olustur|aç|ac|göster|goster|yap|kur)?\s*$",
        text,
        re.IGNORECASE,
    )
    if match:
        name = match.group("name")
        name = re.sub(r"\b(ad[ıi]nda|isimli|yeni|bir)\b", " ", name, flags=re.IGNORECASE)
        return _clean_spaces(name).strip(" .\"'")

    # Örn: NOVA Sunum klasörünü göster / NOVA Sunum klasörünü aç
    match = re.search(
        r"(?:masa[üu]st[üu]ndeki|masa[üu]st[üu]nde|masa[üu]st[üu]ne|desktop(?:ta|te)?|desktop['’]?a)?\s*"
        r"(?P<name>.+?)\s+klas[öo]r(?:ü|ünü|u|unu)?",
        text,
        re.IGNORECASE,
    )
    if match:
        return _clean_spaces(match.group("name")).strip(" .\"'")

    cleaned = re.sub(
        r"\b(klasör|klasor|oluştur|olustur|aç|ac|göster|goster|yap|kur|yeni|bir|adında|adinda|isimli|masaüstünde|masaustunde|masaüstüne|masaustune|masaüstündeki|masaustundeki|desktopta|desktopa|desktop)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_spaces(cleaned).strip(" .\"'")


def _note_args(user_text: str, normalized: str) -> dict[str, str]:
    folder = "documents" if "belgeler" in normalized else "desktop"
    content = ""
    content_match = re.search(r"\bi[cç]ine\s+(.+?)(?:\s+yaz|\s+kaydet)?$", user_text, re.IGNORECASE)
    if content_match:
        content = _clean_spaces(content_match.group(1).strip(" .\"'"))
    file_name = "nova_notu.txt"
    title_match = re.search(r"([A-Za-zÇĞİÖŞÜçğıöşü0-9 _-]+?)\s+(?:notu|not)\s+(?:oluştur|olustur|kaydet|yaz)", user_text, re.IGNORECASE)
    if title_match:
        file_name = _safe_file_name(title_match.group(1))
    args = {"folder": folder, "file_name": file_name}
    if content:
        args["content"] = content
    return args


def _calendar_args(user_text: str, normalized: str) -> dict[str, str]:
    title = _strip_datetime_words(user_text)
    title = re.sub(r"\b(takvimde|takvime|takvim|için|icin|ekle|koy|randevu|toplantı|toplanti|var)\b", "", title, flags=re.IGNORECASE)
    title = _clean_spaces(title).strip(" .\"'") or "NOVA etkinliği"
    return {"title": title, "when": user_text}


def _reminder_args(user_text: str, normalized: str) -> dict[str, str]:
    title = re.sub(r"\b(bana|beni|hatırlat|hatirlat|hatırlatıcı|hatirlatici|kur|oluştur|olustur)\b", "", user_text, flags=re.IGNORECASE)
    title = _strip_datetime_words(title)
    return {"title": _clean_spaces(title).strip(" .\"'") or "NOVA hatırlatıcısı", "when": user_text}


def _append_note_args(user_text: str) -> dict[str, str]:
    content = ""
    match = re.search(r"(?:şunu|sunu|bunu|metni)?\s*ekle[:\s]+(.+)$", user_text, re.IGNORECASE)
    if match:
        content = _clean_spaces(match.group(1).strip(" .\"'"))
    return {"content": content} if content else {}


def _search_file_args(user_text: str, normalized: str) -> dict[str, str]:
    folder = ""
    if "belgeler" in normalized:
        folder = "documents"
    elif "indirilen" in normalized:
        folder = "downloads"
    elif "resim" in normalized:
        folder = "pictures"
    elif "masaustu" in normalized:
        folder = "desktop"

    query = user_text
    query = re.sub(r"\b(masaüstünde|masaustunde|belgelerde|indirilenlerde|resimlerde|dosyasını|dosyasini|dosya|ara|bul|göster|goster|pdf)\b", "", query, flags=re.IGNORECASE)
    query = _clean_spaces(query).strip(" .\"'")
    args = {"query": query}
    if folder:
        args["folder"] = folder
    return args


def _project_structure_args(user_text: str, normalized: str) -> dict[str, str]:
    match = re.search(r"(?:masa[üu]st[üu]nde\s+)?([A-Za-zÇĞİÖŞÜçğıöşü0-9_-]+)\s+proje", user_text, re.IGNORECASE)
    path = match.group(1).strip(" .\"'") if match else (_folder_name(user_text) or "Proje")
    if _normalize_turkish(path) in {"masaustu", "masaustune", "masaustunde", "desktop"}:
        path = "Proje"
    args = {"path": path}
    folders_match = re.search(r"i[cç]ine\s+(.+?)\s+(?:ekle|klas[öo]r)", user_text, re.IGNORECASE)
    if folders_match:
        folders = _clean_spaces(folders_match.group(1).replace(" ve ", " "))
        if folders:
            args["folders"] = folders
    return args


def _clean_completion_title(user_text: str) -> str:
    cleaned = re.sub(
        r"\b(bu|hatırlatıcıyı|hatirlaticiyi|hatırlatıcısını|hatirlaticisini|hatırlatmayı|hatirlatmayi|tamamla|tamamlandı|tamamlandi|yap|işaretle|isaretle|görevi|gorevi|bitmiş|bitmis|bitir|todo|yapılacak|yapilacak)\b",
        "",
        user_text,
        flags=re.IGNORECASE,
    )
    return _clean_spaces(cleaned).strip(" .\"'")


def _clipboard_text(user_text: str) -> str:
    cleaned = re.sub(
        r"\b(şunu|sunu|bunu|bu metni|metni|panoya|kopyala|kopyalayabilir misin)\b",
        "",
        user_text,
        flags=re.IGNORECASE,
    )
    return _clean_spaces(cleaned).strip(" .\"'")


def _strip_intent_words(text: str) -> str:
    cleaned = re.sub(
        r"\b(aç|ac|gir|başlat|baslat|site|sitesi|sitesini|ara|arat|araştır|arastir|google|internette|webde|nedir)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_spaces(cleaned).strip(" .\"'")


def _strip_datetime_words(value: str) -> str:
    cleaned = str(value or "")
    cleaned = re.sub(r"\b(?:bugün|bugun|yarın|yarin)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:pazartesi|salı|sali|çarşamba|carsamba|perşembe|persembe|cuma|cumartesi|pazar)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\bsaat\s*\d{1,2}(?:[:.]\d{2})?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}[:.]\d{2}\b", "", cleaned)
    cleaned = re.sub(r"\b\d+\s*(?:dakika|saat)\s+sonra\b", "", cleaned, flags=re.IGNORECASE)
    return _clean_spaces(cleaned)


def _has_time(normalized: str) -> bool:
    return bool(
        re.search(r"\b(saat\s*)?\d{1,2}[:.]\d{2}\b", normalized)
        or re.search(r"\bsaat\s*\d{1,2}(?:\s+\d{2})?\b", normalized)
        or re.search(r"\b\d{1,2}\s+\d{2}\b", normalized)
    )


def _has_time_or_relative(normalized: str) -> bool:
    return _has_time(normalized) or bool(re.search(r"\b\d+\s*(dakika|saat)\s+sonra\b", normalized)) or any(
        word in normalized for word in ("bugun", "yarin", "pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar")
    )


def _safe_file_name(title: str) -> str:
    stem = _normalize_turkish(title)
    stem = re.sub(r"[^a-z0-9_-]+", "_", stem).strip("_") or "nova_notu"
    return stem + ".txt"


def _clean_spaces(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _normalize_turkish(value: str) -> str:
    lowered = str(value or "").casefold().replace("ı", "i")
    normalized = unicodedata.normalize("NFKD", lowered)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^\w\s]", " ", ascii_text)
    return _clean_spaces(ascii_text)


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))
