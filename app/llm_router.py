from __future__ import annotations

import json
import re
import unicodedata
from time import perf_counter
from typing import Any

from app.action_registry import action_arg_keys, registry_for_prompt, registry_schema_for_prompt, safe_action_names
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


ALLOWED_ACTIONS = safe_action_names()
STEP_ACTIONS = sorted(ALLOWED_ACTIONS - {"MULTI_STEP"})
_DISABLED_PROVIDERS: set[str] = set()

ROUTER_OUT_OF_SCOPE_MESSAGE = (
    "Ben masaüstü işlemlerine odaklı bir sesli asistanım. "
    "Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı ve takvim gibi "
    "bilgisayar işlemlerinde yardımcı olabilirim."
)
ROUTER_UNSAFE_MESSAGE = "Bu işlem güvenlik nedeniyle uygulanmadı."
ROUTER_UNCLEAR_MESSAGE = "Komutu net anlayamadım, tekrar söyleyebilir misiniz?"


TOOL_ROUTER_PROMPT = """
Sen NOVA'nın LLM destekli tool router katmanısın.
Kullanıcının Türkçe doğal dil komutunu sadece aşağıdaki güvenli action registry içinden bir action'a eşleştir.

Temel kurallar:
- Action uydurma. Action listesi dışında hiçbir işlem seçme.
- CMD, PowerShell, shell, registry, silme, formatlama, şifre toplama, local file URL veya sistem ayarı değiştirme içeren isteklerde UNSAFE_REQUEST dön.
- Genel bilgi, açıklama, öneri, nasıl yapılır veya kavram anlatımı isteklerini reddetme; uygun cevap action'ını seç.
- Genel bilgi için GENERAL_AI_ANSWER, pratik nasıl yapılır rehberi için PRACTICAL_GUIDE, kaynaklı/güncel araştırma için RESEARCH_AND_EXPLAIN, şehir/yer/kurum bilgisi için LOCATION_INFO seç.
- "ne zaman", "nerede", "kim", "neden", "nasıl", "hangi", "ne amaçla", "hangi tarihte", "tarihçesi", "gelişimi", "ortaya çıkışı", "ne işe yarar", "nasıl çalışır", "kim tarafından" gibi güvenli bilgi sorularını UNCLEAR yapma; GENERAL_AI_ANSWER seç.
- Kullanıcı masaüstü işlemi istemiyor ama anlamlı bir kavram, tarih, teknoloji, kişi, kurum, şehir veya yöntem hakkında soru soruyorsa varsayılan olarak GENERAL_AI_ANSWER seç.
- Sadece anlamsız, zararlı, uygunsuz veya cevaplanmaması gereken isteklerde OUT_OF_SCOPE ya da UNSAFE_REQUEST dön.
- Desteklenen bir action için gerekli bilgi eksikse NEEDS_CLARIFICATION dön ve kısa bir Türkçe soru sor.
- Sadece izinli action parametrelerini doldur. Boş string üretme.
- Web URL parametrelerinde yalnızca public http/https alanları kabul edilir; javascript:, file:, data:, localhost gibi değerler verme.
- Kullanıcı makale, akademik makale, bilimsel kaynak, literatür, paper, yayın veya kaynakça istiyorsa OPEN_WEBSITE seçme; ACADEMIC_SEARCH seç.
- "Akademik takvim", üniversite duyurusu veya resmi kaynak araması makale değildir; OFFICIAL_INFO_SEARCH seç.
- Kullanıcı haber, son gelişme veya gündem istiyorsa LATEST_NEWS_BY_TOPIC seç.
- Kullanıcı genel araştırma/özet istiyorsa WEB_RESEARCH_SUMMARY; rapor/kaydet/dosyaya yaz istiyorsa WEB_RESEARCH_SAVE seç.
- Kullanıcı araştırma istiyor ama dosyaya kaydetme veya sadece kısa web özeti istemiyorsa RESEARCH_AND_EXPLAIN seç.
- "Merhaba nasılsın" gibi basit konuşmalarda GENERAL_AI_ANSWER seç ve kısa doğal cevap ver.
- JSON dışında hiçbir metin yazma.

Action registry:
{registry}

Çıkış JSON formatı:
{
  "category": "DESKTOP_ACTION | ANSWER_ONLY | NEEDS_CLARIFICATION | OUT_OF_SCOPE | UNSAFE_REQUEST | UNCLEAR",
  "action": "ACTION_NAME_OR_NULL",
  "args": {},
  "message": "",
  "spoken_message": "",
  "confidence": 0.0
}
""".strip().replace("{registry}", registry_schema_for_prompt())


SYSTEM_PROMPT = """
Sen NOVA adlı güvenli bir Windows masaüstü asistanının planlayıcı katmanısın.
Kullanıcı Türkçe doğal dil komutu verir. Sen sadece JSON plan üretirsin.

Kurallar:
- Asla CMD, PowerShell, shell, registry, silme, formatlama veya sistem ayarı komutu üretme.
- Sadece aşağıdaki action registry içinde yer alan action değerlerini kullan.
- Dosya/klasör yollarını Masaüstü'ne göre göreli yaz. Örnek: "Projeler/son_yapay_zeka_haberi.txt".
- Kullanıcı "Masaüstü" derse bunu path içine yazma; yol zaten Masaüstü köküne göre yorumlanır.
- Her action yalnızca ihtiyaç duyduğu args alanlarını içersin.
- Boş string alan üretme.
- MULTI_STEP için üst seviyede args alanı kullanma; sadece action ve steps yaz.
- Birden fazla işlem gerekiyorsa action "MULTI_STEP" olsun ve steps dizisini doldur.
- Kullanıcı isteği registry dışındaysa ANSWER_ONLY ile NOVA'nın masaüstü asistanı kapsam mesajını ver.
- Çıktıya confidence, needs_clarification ve clarification_question alanlarını ekleyebilirsin; gerçek işlem için action ve args kullanılır.
- JSON formatı:
{
  "action": "ACTION_NAME",
  "args": {},
  "confidence": 0.0,
  "needs_clarification": false,
  "clarification_question": ""
}

Action registry:
{registry}

Örnek:
Kullanıcı: Masaüstünde Projeler klasörü aç ve içine son yapay zeka haberini kaydet.
Plan:
{
  "action": "MULTI_STEP",
  "steps": [
    {"action": "CREATE_FOLDER", "args": {"path": "Projeler"}},
    {"action": "SAVE_LATEST_AI_NEWS", "args": {"path": "Projeler/son_yapay_zeka_haberi.txt", "topic": "yapay zeka"}},
    {"action": "OPEN_FOLDER", "args": {"path": "Projeler"}}
  ]
}
""".strip().replace("{registry}", registry_for_prompt())


def route_with_llm(
    user_text: str,
    action_registry: dict[str, Any] | None = None,
    pending_intent: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Route natural language to one registered action.

    Returns None when OpenAI is unavailable or the response cannot be trusted; callers can
    then use a limited local fallback.
    """
    global _ROUTER_TEMP_DISABLED
    provider = _selected_provider()
    if provider is None:
        return None

    registry_text = json.dumps(action_registry, ensure_ascii=False, indent=2) if action_registry else registry_schema_for_prompt()
    prompt = TOOL_ROUTER_PROMPT.replace(registry_schema_for_prompt(), registry_text)
    pending_text = ""
    if pending_intent:
        pending_text = "\nBekleyen eksik intent:\n" + json.dumps(pending_intent, ensure_ascii=False)

    try:
        start = perf_counter()
        if provider == "ollama":
            output_text = generate_with_ollama(
                f"{prompt}\n\nKomut: {user_text}{pending_text}\n\nSadece JSON döndür.",
                json_mode=True,
            )
        else:
            client = _client_for_provider(provider)
            if provider == "gemini":
                response = client.chat.completions.create(
                    model=_model_for_provider(provider),
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Komut: {user_text}{pending_text}"},
                    ],
                    response_format={"type": "json_object"},
                )
                output_text = response.choices[0].message.content or "{}"
            else:
                response = client.responses.create(
                    model=_model_for_provider(provider),
                    input=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Komut: {user_text}{pending_text}"},
                    ],
                    text={"format": {"type": "json_object"}},
                )
                output_text = response.output_text
        print(f"[PERF] {provider} tool router: {perf_counter() - start:.1f} sn", flush=True)
        result = normalize_router_result(_parse_router_json(output_text))
        result["provider"] = provider
        return result
    except Exception as exc:
        print(f"{provider} tool router kullanılamadı, fallback devreye girecek: {exc}", flush=True)
        _DISABLED_PROVIDERS.add(provider)
        return None


def _selected_provider() -> str | None:
    provider = (LLM_PROVIDER or "gemini").casefold()
    if provider not in {"gemini", "openai", "ollama"}:
        return None
    if provider in _DISABLED_PROVIDERS:
        return None
    if provider == "ollama":
        return "ollama"
    if provider == "gemini" and not GEMINI_API_KEY:
        return None
    if provider == "openai" and not OPENAI_API_KEY:
        return None
    return provider


def _client_for_provider(provider: str) -> Any:
    from openai import OpenAI

    if provider == "gemini":
        return OpenAI(
            api_key=GEMINI_API_KEY,
            base_url=GEMINI_BASE_URL,
            timeout=OPENAI_TIMEOUT_SECONDS,
            max_retries=0,
        )
    return OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)


def _model_for_provider(provider: str) -> str:
    if provider == "gemini":
        return GEMINI_MODEL
    if provider == "ollama":
        return OLLAMA_MODEL
    return OPENAI_MODEL


def _parse_router_json(output_text: str) -> dict[str, Any]:
    text = str(output_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def normalize_router_result(raw: dict[str, Any]) -> dict[str, Any]:
    category_map = {
        "ANSWER_ONLY": "ANSWER_ONLY_IN_SCOPE",
        "ANSWER_ONLY_IN_SCOPE": "ANSWER_ONLY_IN_SCOPE",
        "OUT_OF_SCOPE": "OUT_OF_SCOPE_CHAT",
        "OUT_OF_SCOPE_CHAT": "OUT_OF_SCOPE_CHAT",
        "DESKTOP_ACTION": "DESKTOP_ACTION",
        "NEEDS_CLARIFICATION": "NEEDS_CLARIFICATION",
        "UNSAFE_REQUEST": "UNSAFE_REQUEST",
        "UNCLEAR": "UNCLEAR",
    }
    category = category_map.get(str(raw.get("category", "UNCLEAR")).strip().upper(), "UNCLEAR")

    action = raw.get("action")
    action = None if action in {None, "", "null", "NULL"} else str(action).strip().upper()
    if action == "ANSWER_NOVA_CAPABILITIES":
        category = "ANSWER_ONLY_IN_SCOPE"
    elif action == "OUT_OF_SCOPE_RESPONSE":
        category = "OUT_OF_SCOPE_CHAT"
    elif action == "UNSAFE_REQUEST":
        category = "UNSAFE_REQUEST"
    elif action == "NEEDS_CLARIFICATION":
        category = "NEEDS_CLARIFICATION"
    if action and action not in ALLOWED_ACTIONS:
        category = "UNCLEAR"
        action = None

    args = raw.get("args", {}) if isinstance(raw.get("args", {}), dict) else {}
    if action:
        allowed_args = set(action_arg_keys(action))
        args = {
            key: str(value).strip()
            for key, value in args.items()
            if key in allowed_args and value is not None and str(value).strip()
        }
    else:
        args = {}

    message = _clean_spaces(str(raw.get("message", "")))
    spoken_message = _clean_spaces(str(raw.get("spoken_message", ""))) or message

    if category == "OUT_OF_SCOPE_CHAT":
        action = None
        args = {}
        message = spoken_message = message or ROUTER_OUT_OF_SCOPE_MESSAGE
    elif category == "UNSAFE_REQUEST":
        action = None
        args = {}
        message = spoken_message = ROUTER_UNSAFE_MESSAGE
    elif category == "UNCLEAR":
        action = None
        args = {}
        message = spoken_message = message or ROUTER_UNCLEAR_MESSAGE
    elif category == "NEEDS_CLARIFICATION":
        if action == "NEEDS_CLARIFICATION":
            action = None
            args = {}
        message = spoken_message = message or "Biraz daha bilgi verir misiniz?"
    elif category == "ANSWER_ONLY_IN_SCOPE":
        action = None
        args = {}
        message = spoken_message = message or ROUTER_OUT_OF_SCOPE_MESSAGE

    return {
        "category": category,
        "action": action,
        "args": args,
        "message": message,
        "spoken_message": spoken_message,
        "confidence": _clamp_confidence(raw.get("confidence", 0.6)),
        "used_llm_router": True,
    }


FOLDER_PATTERN = re.compile(
    r"""
    (?:^|\s)
    (?:
        masa[üu]st[üu]nde|
        masa[üu]st[üu]ne|
        masa[üu]st[üu]|
        desktop(?:ta|te)?
    )?
    \s*
    (?P<name>[^\\/:*?"<>|\n\r]+?)
    \s+
    klas[öo]r(?:ü|ünü|u|unu)?
    \s+
    (?P<verb>oluştur|olustur|aç|ac)
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def build_plan(user_command: str) -> tuple[dict[str, Any], str | None]:
    fast_plan = fast_local_plan(user_command)
    if fast_plan:
        return normalize_plan(fast_plan), None

    if OPENAI_API_KEY:
        try:
            return _build_plan_with_openai(user_command), None
        except Exception as exc:
            print(f"LLM timeout/hata, fallback kullanıldı: {exc}", flush=True)
            fallback = heuristic_plan(user_command)
            warning = "LLM kullanılamadı, fallback planlayıcı kullanıldı."
            return fallback, warning

    fallback = heuristic_plan(user_command)
    warning = "LLM API anahtarı bulunamadı, fallback planlayıcı kullanıldı."
    return fallback, warning


def _build_plan_with_openai(user_command: str) -> dict[str, Any]:
    from openai import OpenAI

    start = perf_counter()
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_command},
        ],
        text={"format": {"type": "json_object"}},
    )
    print(f"[PERF] LLM planlama: {perf_counter() - start:.1f} sn", flush=True)
    return normalize_plan(json.loads(response.output_text))


def fast_local_plan(user_command: str) -> dict[str, Any] | None:
    """Resolve obvious safe intents locally so simple commands never wait for LLM."""
    normalized_command = _normalize_turkish(user_command)

    extractors = (
        lambda: _extract_date_time_plan(user_command, normalized_command),
        lambda: _extract_common_app_plan(normalized_command),
        lambda: _extract_special_folder_plan(normalized_command),
        lambda: _extract_website_plan(user_command, normalized_command),
        lambda: _extract_web_search_plan(user_command, normalized_command),
        lambda: _extract_note_plan(user_command, normalized_command),
        lambda: _extract_project_structure_plan(user_command, normalized_command),
        lambda: _extract_search_topic_plan(user_command, normalized_command),
        lambda: _extract_folder_plan(user_command),
    )
    for extractor in extractors:
        plan = extractor()
        if plan:
            return plan
    return None


def heuristic_plan(user_command: str) -> dict[str, Any]:
    lower_command = user_command.casefold()
    normalized_command = _normalize_turkish(lower_command)
    folder_info = _extract_folder_action(user_command)

    screenshot_plan = _extract_screenshot_plan(normalized_command)
    if screenshot_plan:
        return normalize_plan(screenshot_plan)

    date_time_plan = _extract_date_time_plan(user_command, normalized_command)
    if date_time_plan:
        return normalize_plan(date_time_plan)

    reminder_plan = _extract_reminder_plan(user_command, normalized_command)
    if reminder_plan:
        return normalize_plan(reminder_plan)

    todo_plan = _extract_todo_plan(user_command, normalized_command)
    if todo_plan:
        return normalize_plan(todo_plan)

    calendar_plan = _extract_calendar_plan(user_command, normalized_command)
    if calendar_plan:
        return normalize_plan(calendar_plan)

    web_search_plan = _extract_web_search_plan(user_command, normalized_command)
    if web_search_plan:
        return normalize_plan(web_search_plan)

    website_plan = _extract_website_plan(user_command, normalized_command)
    if website_plan:
        return normalize_plan(website_plan)

    special_folder = _extract_special_folder(normalized_command)
    if special_folder and (not folder_info or _folder_info_is_special(folder_info)):
        return normalize_plan({"action": "OPEN_SPECIAL_FOLDER", "args": {"folder": special_folder}})

    note_plan = _extract_note_plan(user_command, normalized_command)
    if note_plan:
        return normalize_plan(note_plan)

    project_plan = _extract_project_structure_plan(user_command, normalized_command)
    if project_plan:
        return normalize_plan(project_plan)

    common_app_plan = _extract_common_app_plan(normalized_command)
    if common_app_plan:
        return normalize_plan(common_app_plan)

    if "yapay zeka" in lower_command and ("haber" in lower_command or "son" in lower_command):
        folder = folder_info["name"] if folder_info else "Projeler"
        return normalize_plan(
            {
                "action": "MULTI_STEP",
                "steps": [
                    {"action": "CREATE_FOLDER", "args": {"path": folder}},
                    {
                        "action": "SAVE_LATEST_AI_NEWS",
                        "args": {
                            "path": f"{folder}/son_yapay_zeka_haberi.txt",
                            "topic": "yapay zeka",
                        },
                    },
                    {"action": "OPEN_FOLDER", "args": {"path": folder}},
                ],
            }
        )

    search_plan = _extract_search_topic_plan(user_command, normalized_command)
    if search_plan:
        return normalize_plan(search_plan)

    if folder_info:
        action = "CREATE_FOLDER" if folder_info["verb"] == "create" else "OPEN_FOLDER"
        return normalize_plan({"action": action, "args": {"path": folder_info["name"]}})

    if _looks_like_general_information_question(normalized_command):
        return normalize_plan(
            {
                "action": "GENERAL_AI_ANSWER",
                "args": {"question": user_command.strip(), "mode": "general"},
            }
        )

    return normalize_plan(
        {
            "action": "ANSWER_ONLY",
            "args": {
                "message": (
                    "Ben masaüstü işlemlerine odaklı bir sesli asistanım. "
                    "Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı ve takvim gibi "
                    "bilgisayar işlemlerinde yardımcı olabilirim."
                )
            },
        }
    )


def _looks_like_general_information_question(normalized_command: str) -> bool:
    if _looks_like_desktop_operation(normalized_command):
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
        "tarihcesi",
        "gelisimi",
        "ortaya cikisi",
        "kullanim alani",
        "ne ise yarar",
        "nasil calisir",
        "kim tarafindan",
        "ne icin kullanil",
    )
    if not any(marker in normalized_command for marker in markers):
        return False
    return len([word for word in normalized_command.split() if len(word) > 1]) >= 3


def _looks_like_desktop_operation(normalized_command: str) -> bool:
    markers = (
        "masaustunde",
        "masaustune",
        "klasor olustur",
        "klasoru olustur",
        "klasor ac",
        "klasoru ac",
        "dosya olustur",
        "not olustur",
        "not kaydet",
        "uygulama ac",
        "not defteri",
        "hesap makinesi",
        "web sitesi ac",
        "siteyi ac",
        "takvime",
        "hatirlatici",
        "yapilacak",
        "ekran goruntusu",
        "panoya kopyala",
    )
    return any(marker in normalized_command for marker in markers)


def _extract_special_folder_plan(normalized_command: str) -> dict[str, Any] | None:
    folder = _extract_special_folder(normalized_command)
    if folder:
        return {"action": "OPEN_SPECIAL_FOLDER", "args": {"folder": folder}}
    return None


def _extract_folder_plan(user_command: str) -> dict[str, Any] | None:
    folder_info = _extract_folder_action(user_command)
    if not folder_info:
        return None
    action = "CREATE_FOLDER" if folder_info["verb"] == "create" else "OPEN_FOLDER"
    return {"action": action, "args": {"path": folder_info["name"]}}


def normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("needs_clarification"):
        question = str(plan.get("clarification_question", "")).strip()
        return {
            "action": "ANSWER_ONLY",
            "args": {"message": question or "Bu işlem için biraz daha bilgi gerekiyor."},
        }

    action = str(plan.get("action", "ANSWER_ONLY")).strip().upper()
    if action not in ALLOWED_ACTIONS:
        action = "ANSWER_ONLY"
        return {
            "action": action,
            "args": {
                "message": (
                    "Ben masaüstü işlemlerine odaklı bir sesli asistanım. "
                    "Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı ve takvim gibi "
                    "bilgisayar işlemlerinde yardımcı olabilirim."
                )
            },
        }

    args = _normalize_args(action, plan.get("args", {}))
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        steps = []

    normalized_steps = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_action = str(step.get("action", "ANSWER_ONLY")).strip().upper()
        if step_action not in STEP_ACTIONS:
            step_action = "ANSWER_ONLY"
        normalized_step = {"action": step_action}
        step_args = _normalize_args(step_action, step.get("args", {}))
        if step_args:
            normalized_step["args"] = step_args
        normalized_steps.append(normalized_step)

    if action == "MULTI_STEP" and not normalized_steps:
        action = "ANSWER_ONLY"
        args = {"message": "Çok adımlı plan boş geldiği için işlem yapılmadı."}

    if action == "MULTI_STEP":
        return {"action": action, "steps": normalized_steps}

    normalized_plan: dict[str, Any] = {"action": action}
    if args:
        normalized_plan["args"] = args
    return normalized_plan


def _normalize_args(action: str, raw_args: Any) -> dict[str, str]:
    args = {}
    if isinstance(raw_args, dict):
        for key in action_arg_keys(action):
            value = raw_args.get(key, "")
            if value is None:
                continue
            text = str(value).strip()
            if text:
                args[key] = text
    return args


def _extract_folder_action(user_command: str) -> dict[str, str] | None:
    match = FOLDER_PATTERN.search(user_command.strip())
    if not match:
        return None

    folder_name = _clean_folder_name(match.group("name"))
    if not folder_name:
        return None

    verb = match.group("verb").casefold()
    return {
        "name": folder_name,
        "verb": "create" if verb in {"oluştur", "olustur"} else "open",
    }


def _clean_folder_name(folder_name: str) -> str:
    cleaned = folder_name.strip(" .\"'")
    desktop_prefixes = (
        "masaüstünde ",
        "masaustunde ",
        "masaüstüne ",
        "masaustune ",
        "masaüstü ",
        "masaustu ",
        "desktop ",
    )
    lowered = cleaned.casefold()
    for prefix in desktop_prefixes:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned.strip(" .\"'")


def _asks_for_app(lower_command: str, names: tuple[str, ...]) -> bool:
    if "aç" not in lower_command and "ac" not in lower_command:
        return False
    return any(name in lower_command for name in names)


def _normalize_turkish(value: str) -> str:
    lowered = value.casefold().replace("ı", "i")
    normalized = unicodedata.normalize("NFKD", lowered)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(ascii_text.replace("’", "'").split())


def _clean_spaces(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))


def _extract_website_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    if not _has_open_intent(normalized_command):
        return None

    known_sites = {
        "google": {"site": "google"},
        "youtube": {"site": "youtube"},
        "github": {"site": "github"},
        "selcuk universitesi": {"site": "selçuk üniversitesi"},
    }
    for name, args in known_sites.items():
        if name in normalized_command:
            return {"action": "OPEN_WEBSITE", "args": args}

    domain_match = re.search(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", normalized_command)
    if domain_match:
        return {"action": "OPEN_WEBSITE", "args": {"url": domain_match.group(1)}}

    return None


def _extract_web_search_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    if not _has_search_intent(normalized_command):
        return None
    if any(word in normalized_command for word in ("kaydet", "dosyaya", "masaustune", "hazirla")):
        return None

    query = re.sub(r"\b(ara|arat|arama yap|internette ara|google'da ara|googleda ara)\b", "", user_command, flags=re.IGNORECASE)
    query = query.strip(" .\"'")
    if not query:
        query = user_command.strip()
    return {"action": "WEB_SEARCH", "args": {"query": query}}


def _extract_common_app_plan(normalized_command: str) -> dict[str, Any] | None:
    if not _has_open_intent(normalized_command):
        return None
    app_names = {
        "not defteri": "not defteri",
        "notepad": "not defteri",
        "hesap makinesi": "hesap makinesi",
        "calculator": "hesap makinesi",
        "paint": "paint",
        "wordpad": "wordpad",
        "vs code": "vs code",
        "vscode": "vs code",
        "visual studio code": "vs code",
        "chrome": "chrome",
        "google chrome": "chrome",
    }
    for key, app_name in app_names.items():
        if key in normalized_command:
            return {"action": "OPEN_COMMON_APP", "args": {"app_name": app_name}}
    return None


def _extract_date_time_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    date_words = ("saat kac", "tarih", "bugun gunlerden", "hangi gun", "bugun ne")
    if any(word in normalized_command for word in date_words):
        return {"action": "DATE_TIME_ANSWER", "args": {"question": user_command.strip()}}
    return None


def _extract_screenshot_plan(normalized_command: str) -> dict[str, Any] | None:
    if "ekran goruntusu" in normalized_command or "screenshot" in normalized_command:
        return {"action": "TAKE_SCREENSHOT"}
    return None


def _extract_reminder_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    if "hatirlaticilar" in normalized_command and "listele" in normalized_command:
        return {"action": "LIST_REMINDERS"}
    if "hatirlat" not in normalized_command:
        return None
    title = user_command
    title = re.sub(r"^\s*bana\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\bhat[ıi]rlat\b", "", title, flags=re.IGNORECASE)
    title = _strip_datetime_words(title)
    title = re.sub(r"\b(?:meyi|mayı|mayi|meyi)\b", "", title, flags=re.IGNORECASE)
    title = title.strip(" .\"'") or "NOVA hatırlatıcısı"
    return {"action": "CREATE_REMINDER", "args": {"title": title, "when": user_command.strip()}}


def _extract_todo_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    if "yapilacaklar" not in normalized_command and "yapilacaklara" not in normalized_command:
        if "tamamlandi" not in normalized_command and "tamamlandı" not in user_command.casefold():
            return None

    if "listele" in normalized_command:
        return {"action": "LIST_TODOS"}

    if "tamamlandi" in normalized_command or "tamamlandı" in user_command.casefold():
        title = re.sub(r"\b(?:tamamlandı|tamamlandi|işaretle|isaretle)\b", "", user_command, flags=re.IGNORECASE)
        title = title.strip(" .\"'") or user_command.strip()
        return {"action": "COMPLETE_TODO", "args": {"title": title}}

    if "ekle" in normalized_command:
        title = re.sub(r"^\s*yap[ıi]lacaklara\s+", "", user_command, flags=re.IGNORECASE)
        title = re.sub(r"\bekle\b", "", title, flags=re.IGNORECASE).strip(" .\"'")
        return {"action": "ADD_TODO", "args": {"title": title or "Yeni yapılacak"}}
    return None


def _extract_calendar_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    calendar_markers = ("ekle", "randevu", "randevusu", "toplanti", "etkinlik", "takvim", "kaydet", "koy", "var")
    time_markers = (
        "bugun",
        "yarin",
        "saat",
        "pazartesi",
        "sali",
        "carsamba",
        "persembe",
        "cuma",
        "cumartesi",
        "pazar",
        "ikiye",
    )
    if not any(marker in normalized_command for marker in calendar_markers):
        return None
    if not any(marker in normalized_command for marker in time_markers) and not re.search(r"\b\d{1,2}[./]\d{1,2}", normalized_command):
        return None
    title = _strip_datetime_words(user_command)
    title = re.sub(
        r"\b(?:ekle|oluştur|olustur|randevusu|randevu|kaydet|koy|takvime|takvim|var)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = title.strip(" .\"'") or "NOVA Etkinliği"
    return {"action": "CREATE_CALENDAR_EVENT", "args": {"title": title, "when": user_command.strip()}}


def _extract_special_folder(normalized_command: str) -> str | None:
    if not _has_open_intent(normalized_command):
        return None
    if "belgeler" in normalized_command or "documents" in normalized_command:
        return "documents"
    if "indirilenler" in normalized_command or "downloads" in normalized_command:
        return "downloads"
    if "resimler" in normalized_command or "pictures" in normalized_command:
        return "pictures"
    if "masaustu" in normalized_command or "desktop" in normalized_command:
        return "desktop"
    return None


def _folder_info_is_special(folder_info: dict[str, str]) -> bool:
    normalized_name = _normalize_turkish(folder_info.get("name", ""))
    return normalized_name in {"belgeler", "documents", "indirilenler", "downloads", "resimler", "pictures"}


def _has_open_intent(normalized_command: str) -> bool:
    return any(
        signal in normalized_command
        for signal in ("ac", "gir", "baslat", "goster", "sayfasini", "sitesini", "siteye")
    )


def _has_search_intent(normalized_command: str) -> bool:
    return any(
        signal in normalized_command
        for signal in (" ara", " arat", " arama", " arastir", " araştır")
    )


def _extract_note_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    if not any(word in normalized_command for word in ("not", "liste", "listesi")):
        return None
    if not any(word in normalized_command for word in ("olustur", "kaydet", "yaz")):
        return None

    folder = "documents" if "belgeler" in normalized_command or "belgelerime" in normalized_command else "desktop"
    file_name = "nova_notu.txt"
    content = "NOVA tarafından oluşturulan not."

    content_match = re.search(r"\bi[cç]ine\s+(.+?)(?:\s+yaz|\s+kaydet)?$", user_command, re.IGNORECASE)
    if content_match:
        content = content_match.group(1).strip(" .\"'")

    name_match = re.search(r"([A-Za-zÇĞİÖŞÜçğıöşü0-9 _-]+?)\s+notu\s+(?:kaydet|oluştur|olustur)", user_command, re.IGNORECASE)
    if name_match:
        file_name = _safe_file_stem(_clean_note_title(name_match.group(1))) + ".txt"

    list_match = re.search(
        r"([A-Za-zÇĞİÖŞÜçğıöşü0-9 _-]+?)\s+listesi\s+(?:kaydet|oluştur|olustur)",
        user_command,
        re.IGNORECASE,
    )
    if list_match:
        list_name = (_clean_note_title(list_match.group(1)) + " listesi").strip()
        file_name = _safe_file_stem(list_name) + ".txt"
        if content == "NOVA tarafından oluşturulan not.":
            content = list_name

    return {"action": "CREATE_NOTE", "args": {"folder": folder, "file_name": file_name, "content": content}}


def _extract_project_structure_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    if "proje" not in normalized_command or not any(word in normalized_command for word in ("yapi", "yapisi", "klasoru olustur")):
        return None

    folder_info = _extract_folder_action(user_command)
    main_folder = folder_info["name"] if folder_info else "Proje"
    name_match = re.search(
        r"(?:masa[üu]st[üu]nde\s+)?([A-Za-zÇĞİÖŞÜçğıöşü0-9_-]+)\s+proje\s+yap[ıi]s[ıi]",
        user_command,
        re.IGNORECASE,
    )
    if name_match:
        main_folder = name_match.group(1).strip(" .\"'")

    custom_folders = []
    custom_match = re.search(
        r"i[cç]ine\s+(.+?)\s+klas[öo]r(?:lerini|leri|ler)?",
        user_command,
        re.IGNORECASE,
    )
    if custom_match:
        custom_folders = [
            part.strip(" .,\"'")
            for part in re.split(r"\s*,\s*|\s+ve\s+|\s+", custom_match.group(1))
            if part.strip(" .,\"'")
        ]

    args = {"path": main_folder}
    if custom_folders:
        args["folders"] = ", ".join(custom_folders)
    return {"action": "CREATE_PROJECT_STRUCTURE", "args": args}


def _extract_search_topic_plan(user_command: str, normalized_command: str) -> dict[str, Any] | None:
    if not any(word in normalized_command for word in ("arastirma", "ozet", "haber")):
        return None
    if not any(word in normalized_command for word in ("kaydet", "hazirla", "yap")):
        return None

    topic = user_command.strip()
    topic_match = re.search(r"(.+?)\s+hakkında", user_command, re.IGNORECASE)
    if topic_match:
        topic = topic_match.group(1).strip(" .\"'")
    elif "teknoloji" in normalized_command and "haber" in normalized_command:
        topic = "teknoloji"
    elif "yapay zeka" in user_command.casefold():
        topic = "yapay zeka"

    file_name = _safe_file_stem(topic) + "_ozet.txt"
    return {
        "action": "SEARCH_TOPIC_AND_SAVE",
        "args": {"topic": topic, "path": file_name, "file_name": file_name},
    }


def _strip_datetime_words(value: str) -> str:
    cleaned = str(value or "")
    cleaned = re.sub(r"\b(?:bugün|bugun|yarın|yarin)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:pazartesi|salı|sali|çarşamba|carsamba|perşembe|persembe|cuma|cumartesi|pazar)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{4})?\b", "", cleaned)
    cleaned = re.sub(r"\b\d{1,2}\s+(?:ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)(?:\s+\d{4})?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bsaat\s*\d{1,2}(?:[:.]\d{2})?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}[:.]\d{2}\b", "", cleaned)
    cleaned = re.sub(r"\b\d+\s*(?:dakika|saat)\s+sonra\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:bire|ikiye|üçe|uce|dörde|dorde|beşe|bese|altıya|altiya|yediye|sekize|dokuza|ona|on bire|on ikiye)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[’'` ]*(?:e|a|de|da|ye|ya)\s+", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.strip(" .\"'").split())


def _safe_file_stem(value: str) -> str:
    normalized = _normalize_turkish(value)
    cleaned = re.sub(r"[^a-z0-9_-]+", "_", normalized).strip("_")
    return cleaned or "nova_notu"


def _clean_note_title(value: str) -> str:
    cleaned = value.strip(" .\"'")
    cleaned = re.sub(
        r"^(?:masa[üu]st[üu]ne|masa[üu]st[üu]nde|masa[üu]st[üu]|belgelerime|belgelerimde|belgeler|documents)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .\"'") or "nova_notu"
