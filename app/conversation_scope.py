from __future__ import annotations

import json
import re
import unicodedata
from time import perf_counter
from typing import Any

from app.action_registry import ACTION_REGISTRY, registry_for_prompt
from app.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS


CATEGORIES = {
    "DESKTOP_ACTION",
    "ANSWER_ONLY_IN_SCOPE",
    "OUT_OF_SCOPE_CHAT",
    "UNSAFE_REQUEST",
    "UNCLEAR",
    "STOP_CONVERSATION",
}

OUT_OF_SCOPE_MESSAGE = (
    "Ben masaüstü işlemlerine odaklı bir sesli asistanım. "
    "Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı ve takvim gibi "
    "bilgisayar işlemlerinde yardımcı olabilirim."
)
UNSAFE_MESSAGE = "Bu işlem güvenlik nedeniyle uygulanmadı."
UNCLEAR_MESSAGE = "Komutu net anlayamadım, tekrar söyleyebilir misiniz?"
STOP_MESSAGE = "Konuşma modu kapatıldı."


SCOPE_PROMPT = """
Sen NOVA masaüstü asistanının aktif konuşma modu kapsam/niyet sınıflandırıcısısın.
Kullanıcıdan gelen Türkçe metni sınıflandır.

Kategori kuralları:
- DESKTOP_ACTION: Güvenli action registry içindeki masaüstü işlemleri.
- ANSWER_ONLY_IN_SCOPE: NOVA'nın ne yapabildiği, nasıl çalıştığı veya uygulama kapsamı hakkında kısa cevaplanabilir soru.
- OUT_OF_SCOPE_CHAT: Genel sohbet, kişisel tavsiye, şaka, film/yemek/kombin/aşk gibi masaüstü asistanlığı dışı konular.
- UNSAFE_REQUEST: Silme, formatlama, CMD/PowerShell, registry, şifre, hassas dosya, sistem ayarı veya rastgele exe isteği.
- UNCLEAR: Metin çok belirsiz veya işlem niyeti anlaşılamıyor.
- STOP_CONVERSATION: Kullanıcı konuşma modunu kapatmak istiyor.

Kurallar:
- Genel sohbet üretme.
- Kapsam dışı sorulara uzun cevap verme.
- Registry dışı action uydurma.
- DESKTOP_ACTION için action registry içinden bir action seç.
- Güvenlik dışı isteği her zaman UNSAFE_REQUEST yap.

Action registry:
{registry}

Sadece şu JSON formatında cevap ver:
{
  "category": "DESKTOP_ACTION | ANSWER_ONLY_IN_SCOPE | OUT_OF_SCOPE_CHAT | UNSAFE_REQUEST | UNCLEAR | STOP_CONVERSATION",
  "action": "ACTION_NAME_OR_NULL",
  "args": {},
  "message": "kullanıcıya söylenecek kısa mesaj",
  "confidence": 0.0
}
""".strip().replace("{registry}", registry_for_prompt())


def classify_conversation_input(text: str) -> dict[str, Any]:
    cleaned = _clean_spaces(text)
    if not cleaned:
        return _result("UNCLEAR", message=UNCLEAR_MESSAGE, confidence=0.0)

    fallback = _fallback_classify(cleaned)
    if fallback.get("confidence", 0.0) >= 0.75:
        return fallback

    if OPENAI_API_KEY:
        try:
            return _classify_with_llm(cleaned)
        except Exception as exc:
            print(f"LLM kapsam analizi timeout/hata, fallback kullanıldı: {exc}", flush=True)
            pass

    return _fallback_classify(cleaned)


def _classify_with_llm(text: str) -> dict[str, Any]:
    from openai import OpenAI

    start = perf_counter()
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": SCOPE_PROMPT},
            {"role": "user", "content": text},
        ],
        text={"format": {"type": "json_object"}},
    )
    raw = json.loads(response.output_text)
    print(f"[PERF] LLM kapsam analizi: {perf_counter() - start:.1f} sn", flush=True)
    return _normalize_result(raw)


def _fallback_classify(text: str) -> dict[str, Any]:
    normalized = _normalize_turkish(text)

    if _contains_any(normalized, ("konusmayi durdur", "nova dur", "gorusuruz", "yeterli")):
        return _result("STOP_CONVERSATION", message=STOP_MESSAGE, confidence=0.9)
    if normalized.strip() in {"dur", "kapat", "cik", "cikis", "gorusuruz", "yeterli"}:
        return _result("STOP_CONVERSATION", message=STOP_MESSAGE, confidence=0.9)

    if _contains_any(
        normalized,
        (
            "tum dosyalar",
            "dosyalari sil",
            "klasoru sil",
            "format",
            "cmd",
            "powershell",
            "registry",
            "regedit",
            "sifre",
            "parola",
            "hassas dosya",
            "sistem ayari",
            "sistemi degistir",
            "rastgele exe",
        ),
    ):
        return _result("UNSAFE_REQUEST", message=UNSAFE_MESSAGE, confidence=0.95)

    if _contains_any(
        normalized,
        (
            "nasilsin",
            "kombin",
            "ask",
            "yemek",
            "film",
            "saka",
            "sohbet",
            "tavsiye",
            "spor onerisi",
            "kisisel yorum",
            "ne yesem",
        ),
    ):
        return _result("OUT_OF_SCOPE_CHAT", message=OUT_OF_SCOPE_MESSAGE, confidence=0.85)

    if _contains_any(
        normalized,
        (
            "nova ne yapabilir",
            "ne yapabilirsin",
            "hangi komut",
            "bu uygulama nasil calisiyor",
            "nasil calisiyorsun",
            "yardim",
        ),
    ):
        return _result(
            "ANSWER_ONLY_IN_SCOPE",
            message=(
                "Klasör oluşturabilir, uygulama ve web sitesi açabilir, not ve yapılacak ekleyebilir, "
                "hatırlatıcı veya takvim etkinliği oluşturabilir, ekran görüntüsü alabilir ve saat/tarih bilgisi verebilirim."
            ),
            confidence=0.85,
        )

    desktop_signals = (
        "ac",
        "gir",
        "baslat",
        "olustur",
        "kaydet",
        "ara",
        "not",
        "klasor",
        "dosya",
        "ekran goruntusu",
        "takvim",
        "randevu",
        "toplanti",
        "hatirlat",
        "yapilacak",
        "saat",
        "tarih",
        "bugun gunlerden",
        "web",
        "site",
    )
    if _contains_any(normalized, desktop_signals):
        return _result("DESKTOP_ACTION", action=None, message="", confidence=0.75)

    return _result("UNCLEAR", message=UNCLEAR_MESSAGE, confidence=0.35)


def _normalize_result(raw: dict[str, Any]) -> dict[str, Any]:
    category = str(raw.get("category", "UNCLEAR")).strip().upper()
    if category not in CATEGORIES:
        category = "UNCLEAR"

    action = raw.get("action")
    if action is not None:
        action = str(action).strip().upper()
    if not action or action == "NULL":
        action = None
    if action is not None and action not in ACTION_REGISTRY:
        category = "UNCLEAR"
        action = None

    message = _clean_spaces(raw.get("message", ""))
    if category == "OUT_OF_SCOPE_CHAT":
        message = OUT_OF_SCOPE_MESSAGE
    elif category == "UNSAFE_REQUEST":
        message = UNSAFE_MESSAGE
    elif category == "STOP_CONVERSATION":
        message = STOP_MESSAGE
    elif category == "UNCLEAR":
        message = message or UNCLEAR_MESSAGE
    elif category == "ANSWER_ONLY_IN_SCOPE":
        message = message or "Bu konuda masaüstü asistanlığı kapsamında yardımcı olabilirim."

    return _result(
        category=category,
        action=action,
        args=raw.get("args", {}) if isinstance(raw.get("args", {}), dict) else {},
        message=message,
        confidence=_clamp_confidence(raw.get("confidence", 0.6)),
    )


def _result(
    category: str,
    action: str | None = None,
    args: dict[str, Any] | None = None,
    message: str = "",
    confidence: float = 0.5,
) -> dict[str, Any]:
    return {
        "category": category,
        "action": action,
        "args": args or {},
        "message": message,
        "confidence": confidence,
    }


def _contains_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(signal in text for signal in signals)


def _normalize_turkish(value: str) -> str:
    lowered = str(value or "").casefold().replace("ı", "i")
    normalized = unicodedata.normalize("NFKD", lowered)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^\w\s]", " ", ascii_text)
    return _clean_spaces(ascii_text)


def _clean_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))
