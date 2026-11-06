from __future__ import annotations

import threading
from time import perf_counter
from typing import Any

from app.action_registry import safe_action_names
from app.llm_router import build_plan, normalize_plan
from app.tools import execute_plan


_CANCEL_EVENT = threading.Event()

DIRECT_SAFE_ACTIONS = safe_action_names()
DIRECT_STEP_ACTIONS = DIRECT_SAFE_ACTIONS - {"MULTI_STEP"}

DANGEROUS_COMMAND_WORDS = (
    "sil",
    "delete",
    "format",
    "cmd",
    "powershell",
    "terminal",
    "registry",
    "regedit",
    "javascript:",
    "file:",
    "file://",
    "data:",
    "şifre",
    "sifre",
    "parola",
    "password",
    "kişisel veri",
    "kisisel veri",
    "veri topla",
    "sistem ayarı",
    "sistem ayar",
    "ayar değiştir",
    "ayar degistir",
)


def prepare_command(user_text: str) -> dict[str, Any]:
    """Create a plan without running any desktop action."""
    start = perf_counter()
    cleaned_text = user_text.strip()
    if not cleaned_text:
        return {
            "user_text": user_text,
            "warning": None,
            "plan": {"action": "ANSWER_ONLY", "args": {"message": "Boş komut gönderildi."}},
            "success": False,
            "prepared_only": True,
            "applied": False,
        }

    plan, warning = build_plan(cleaned_text)
    print(f"[PERF] Intent/planlama: {perf_counter() - start:.1f} sn", flush=True)
    return {
        "user_text": cleaned_text,
        "warning": warning,
        "plan": plan,
        "success": True,
        "prepared_only": True,
        "applied": False,
    }


def apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Run an already prepared plan through the allowed tool layer."""
    start = perf_counter()
    safe_plan = normalize_plan(plan if isinstance(plan, dict) else {})
    results = execute_plan(safe_plan, cancel_event=_CANCEL_EVENT)
    print(f"[PERF] Action çalıştırma: {perf_counter() - start:.1f} sn", flush=True)

    return {
        "plan": safe_plan,
        "results": results,
        "success": all(result.get("success") for result in results),
        "prepared_only": False,
        "applied": True,
    }


def is_safe_plan(plan: dict[str, Any]) -> tuple[bool, str]:
    """Allow only NOVA's explicitly supported desktop actions."""
    safe_plan = normalize_plan(plan if isinstance(plan, dict) else {})
    action = safe_plan.get("action")

    if action not in DIRECT_SAFE_ACTIONS:
        return False, f"Desteklenmeyen action: {action}"

    if action != "MULTI_STEP":
        return True, "Plan güvenli."

    steps = safe_plan.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return False, "Çok adımlı plan boş."

    for index, step in enumerate(steps, start=1):
        step_action = step.get("action") if isinstance(step, dict) else None
        if step_action not in DIRECT_STEP_ACTIONS:
            return False, f"{index}. adım güvenli değil: {step_action}"

    return True, "Plan güvenli."


def run_command_direct(user_text: str) -> dict[str, Any]:
    """Interpret a command, verify its selected action, and run it when safe."""
    total_start = perf_counter()
    reset_cancel_flag()

    if _looks_dangerous(user_text):
        prepared = {
            "user_text": user_text.strip(),
            "warning": None,
            "plan": {"action": "ANSWER_ONLY", "args": {"message": "Bu işlem güvenlik nedeniyle uygulanmadı."}},
            "success": False,
        }
        print(f"[PERF] Toplam komut: {perf_counter() - total_start:.1f} sn", flush=True)
        return _blocked_direct_result(prepared, prepared["plan"], "Bu işlem güvenlik nedeniyle uygulanmadı.")

    from app.command_interpreter import interpret_user_intent

    intent = interpret_user_intent(user_text, source="text")
    result = run_intent_direct(intent, user_text)
    print(f"[PERF] Toplam komut: {perf_counter() - total_start:.1f} sn", flush=True)
    return result


def run_intent_direct(intent: dict[str, Any], user_text: str = "") -> dict[str, Any]:
    """Run a normalized intent router result without re-planning with the LLM."""
    reset_cancel_flag()
    category = str(intent.get("category", "UNCLEAR")).upper()
    message = str(intent.get("message") or intent.get("spoken_message") or "").strip()

    if category == "UNSAFE_REQUEST":
        prepared = _prepared_message(user_text, intent, message or "Bu işlem güvenlik nedeniyle uygulanmadı.")
        return _blocked_direct_result(prepared, prepared["plan"], message or "Bu işlem güvenlik nedeniyle uygulanmadı.")

    if category in {"OUT_OF_SCOPE_CHAT", "ANSWER_ONLY_IN_SCOPE", "NEEDS_CLARIFICATION", "UNCLEAR"}:
        return _message_direct_result(
            user_text=user_text,
            intent=intent,
            message=message or "Komutu net anlayamadım, tekrar söyleyebilir misiniz?",
            status={
                "OUT_OF_SCOPE_CHAT": "out_of_scope",
                "ANSWER_ONLY_IN_SCOPE": "answered",
                "NEEDS_CLARIFICATION": "needs_clarification",
                "UNCLEAR": "unclear",
            }.get(category, "answered"),
            success=category == "ANSWER_ONLY_IN_SCOPE",
        )

    if category != "DESKTOP_ACTION":
        return _message_direct_result(
            user_text=user_text,
            intent=intent,
            message="Komutu net anlayamadım, tekrar söyleyebilir misiniz?",
            status="unclear",
            success=False,
        )

    action = str(intent.get("action") or "ANSWER_ONLY").upper()
    args = intent.get("args", {}) if isinstance(intent.get("args", {}), dict) else {}
    plan = normalize_plan({"action": action, "args": args})

    if _looks_dangerous(user_text):
        prepared = _prepared_message(user_text, intent, "Bu işlem güvenlik nedeniyle uygulanmadı.")
        return _blocked_direct_result(prepared, plan, "Bu işlem güvenlik nedeniyle uygulanmadı.")

    is_safe, reason = is_safe_plan(plan)
    if not is_safe:
        prepared = _prepared_message(user_text, intent, "Bu işlem güvenlik nedeniyle uygulanmadı.")
        return _blocked_direct_result(prepared, plan, "Bu işlem güvenlik nedeniyle uygulanmadı.", reason)

    prepared = {
        "user_text": user_text.strip(),
        "warning": None,
        "plan": plan,
        "success": True,
    }
    applied = apply_plan(plan)
    if is_cancel_requested() or any(result.get("stopped") for result in applied["results"]):
        return _stopped_direct_result(prepared, applied["plan"], applied["results"])

    return {
        "user_text": user_text.strip(),
        "warning": None,
        "plan": applied["plan"],
        "results": applied["results"],
        "success": applied["success"],
        "prepared_only": False,
        "applied": True,
        "direct_mode": True,
        "blocked": False,
        "status": "completed" if applied["success"] else "failed",
        "reason": None,
        "safety": reason,
        "message": _first_result_message(applied["results"]),
        "spoken_message": _first_result_spoken_message(applied["results"]),
    }


def run_assistant_command(user_text: str) -> dict[str, Any]:
    """Plan and execute one NOVA command for terminal/backward compatibility."""
    prepared = prepare_command(user_text)
    applied = apply_plan(prepared["plan"])

    return {
        "user_text": prepared["user_text"],
        "warning": prepared["warning"],
        "plan": applied["plan"],
        "results": applied["results"],
        "success": prepared["success"] and applied["success"],
        "prepared_only": False,
        "applied": True,
    }


def cancel_current_task() -> dict[str, Any]:
    _CANCEL_EVENT.set()
    return {"stopped": True, "message": "İşlem durduruldu."}


def reset_cancel_flag() -> None:
    _CANCEL_EVENT.clear()


def is_cancel_requested() -> bool:
    return _CANCEL_EVENT.is_set()


def _blocked_direct_result(
    prepared: dict[str, Any],
    plan: dict[str, Any],
    message: str,
    safety_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "user_text": prepared.get("user_text", ""),
        "warning": prepared.get("warning"),
        "plan": plan,
        "results": [
            {
                "action": plan.get("action", "UNKNOWN"),
                "success": False,
                "blocked": True,
                "message": message,
            }
        ],
        "success": False,
        "prepared_only": False,
        "applied": False,
        "direct_mode": True,
        "blocked": True,
        "status": "blocked",
        "reason": safety_reason or message,
        "safety": safety_reason or message,
        "message": message,
        "spoken_message": message,
    }


def _stopped_direct_result(
    prepared: dict[str, Any],
    plan: dict[str, Any],
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "user_text": prepared.get("user_text", ""),
        "warning": prepared.get("warning"),
        "plan": plan,
        "results": results
        or [
            {
                "action": plan.get("action", "UNKNOWN"),
                "success": False,
                "stopped": True,
                "message": "İşlem durduruldu.",
            }
        ],
        "success": False,
        "prepared_only": False,
        "applied": False,
        "direct_mode": True,
        "blocked": False,
        "stopped": True,
        "status": "stopped",
        "reason": "İşlem durduruldu.",
        "safety": "Kullanıcı işlemi durdurdu.",
    }


def _looks_dangerous(user_text: str) -> bool:
    lowered = str(user_text or "").casefold()
    return any(word in lowered for word in DANGEROUS_COMMAND_WORDS)


def _prepared_message(user_text: str, intent: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "user_text": user_text.strip(),
        "warning": None,
        "plan": {"action": "ANSWER_ONLY", "args": {"message": message}},
        "success": False,
        "intent": intent,
    }


def _message_direct_result(
    user_text: str,
    intent: dict[str, Any],
    message: str,
    status: str,
    success: bool,
) -> dict[str, Any]:
    return {
        "user_text": user_text.strip(),
        "warning": None,
        "plan": {"action": "ANSWER_ONLY", "args": {"message": message}},
        "results": [{"action": "ANSWER_ONLY", "success": True, "message": message, "value": ""}],
        "success": success,
        "prepared_only": False,
        "applied": False,
        "direct_mode": True,
        "blocked": False,
        "status": status,
        "reason": message,
        "safety": "İşlem gerektirmeyen yanıt.",
        "message": message,
        "spoken_message": intent.get("spoken_message") or message,
        "needs_clarification": status == "needs_clarification",
        "out_of_scope": status == "out_of_scope",
        "unclear": status == "unclear",
        "intent": intent,
    }


def _first_result_message(results: list[dict[str, Any]]) -> str:
    if not results:
        return "İşlem tamamlandı."
    first = results[0]
    if not first.get("success", False):
        return str(first.get("message") or "İşlem sırasında hata oluştu.")
    action = first.get("action")
    if action in {
        "ANSWER_ONLY",
        "DATE_TIME_ANSWER",
        "LIST_REMINDERS",
        "LIST_TODOS",
        "SEARCH_FILES",
        "SYSTEM_INFO",
        "WEB_RESEARCH_SUMMARY",
        "ACADEMIC_SEARCH",
        "SUMMARIZE_URL",
        "LATEST_NEWS_BY_TOPIC",
        "OFFICIAL_INFO_SEARCH",
        "ANSWER_NOVA_CAPABILITIES",
        "OUT_OF_SCOPE_RESPONSE",
        "UNSAFE_REQUEST",
        "NEEDS_CLARIFICATION",
        "GENERAL_AI_ANSWER",
        "RESEARCH_AND_EXPLAIN",
        "PRACTICAL_GUIDE",
        "LOCATION_INFO",
        "UNSAFE_OR_BLOCKED",
    }:
        return str(first.get("message") or "İşlem tamamlandı.")
    action_messages = {
        "CREATE_CALENDAR_EVENT": "Takvim etkinliği oluşturuldu.",
        "CREATE_REMINDER": "Hatırlatıcı oluşturuldu.",
        "COMPLETE_REMINDER": "Hatırlatıcı tamamlandı.",
        "ADD_TODO": "Yapılacaklara eklendi.",
        "COMPLETE_TODO": "Yapılacak tamamlandı.",
        "APPEND_TO_NOTE": "Nota metin eklendi.",
        "CREATE_PROJECT_STRUCTURE": "Proje yapısı oluşturuldu.",
        "TAKE_SCREENSHOT": "Ekran görüntüsü kaydedildi.",
        "WEB_RESEARCH_SAVE": "Araştırma raporu kaydedildi.",
        "ACADEMIC_SEARCH": str(first.get("message") or "Akademik kaynaklar bulundu."),
        "COPY_TEXT_TO_CLIPBOARD": "Metin panoya kopyalandı.",
        "VOLUME_UP": "Ses artırıldı.",
        "VOLUME_DOWN": "Ses kısıldı.",
        "MUTE_VOLUME": "Ses kapatıldı.",
        "UNMUTE_VOLUME": "Ses açıldı.",
        "VOLUME_CONTROL": str(first.get("message") or "Ses ayarı değiştirildi."),
        "PLAY_PAUSE_MEDIA": "Medya oynatma durumu değiştirildi.",
    }
    return action_messages.get(str(action), "İşlem tamamlandı.")


def _first_result_spoken_message(results: list[dict[str, Any]]) -> str:
    if not results:
        return "İşlem tamamlandı."
    first = results[0]
    return str(first.get("spoken_message") or _first_result_message(results))
