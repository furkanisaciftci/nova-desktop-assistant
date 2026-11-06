from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from time import perf_counter
from typing import Any

from app.assistant_core import apply_plan, cancel_current_task, prepare_command, run_intent_direct
from app.audio_utils import normalize_turkish_for_wake
from app.command_interpreter import interpret_command, interpret_user_intent
from app.conversation_scope import (
    OUT_OF_SCOPE_MESSAGE,
    UNCLEAR_MESSAGE,
    UNSAFE_MESSAGE,
    classify_conversation_input,
)
from app.tts import play_welcome_sound, speak, stop_speech
from app.tools import get_due_reminders
from app.voice_input import transcribe_microphone_command, warm_up_voice_model


BASE_DIR = Path(__file__).resolve().parent
UI_FILE = BASE_DIR / "ui" / "index.html"
WAKE_GREETING = "Buyurun, sizi dinliyorum."
DATA_DIR = BASE_DIR / "data"
WAKE_EVENT_PATH = DATA_DIR / "wake_event.json"


class Api:
    def __init__(self) -> None:
        self.pending_intent: dict[str, Any] | None = None

    def prepare_command(self, text: str) -> dict[str, Any]:
        try:
            return {"ok": True, "data": prepare_command(text)}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Plan oluşturulurken hata oluştu: {exc}",
            }

    def apply_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"ok": True, "data": apply_plan(plan)}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Plan uygulanırken hata oluştu: {exc}",
            }

    def run_command_direct(self, text: str) -> dict[str, Any]:
        try:
            return {"ok": True, "data": self._handle_user_text(text, source="text")}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Komut çalıştırılırken hata oluştu: {exc}",
            }

    def transcribe_voice(self) -> dict[str, Any]:
        try:
            total_start = perf_counter()
            voice_result = transcribe_microphone_command()
            raw_text = voice_result["text"]
            interpret_start = perf_counter()
            interpretation = interpret_command(raw_text, source="voice")
            print(f"[PERF] Intent yorumlama: {perf_counter() - interpret_start:.1f} sn", flush=True)
            print(f"[PERF] Sesli komut toplam: {perf_counter() - total_start:.1f} sn", flush=True)
            return {
                "ok": True,
                "data": {
                    "raw_text": raw_text,
                    "interpreted_text": interpretation["interpreted_text"],
                    "interpretation": interpretation,
                    "audio_path": voice_result["audio_path"],
                    "duration_seconds": voice_result["duration_seconds"],
                },
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Sesli komut alınamadı: {exc}",
            }

    def voice_command_direct(self) -> dict[str, Any]:
        try:
            total_start = perf_counter()
            voice_result = transcribe_microphone_command()
            raw_text = voice_result["text"]
            if not raw_text.strip():
                return {"ok": True, "data": _simple_voice_result(False, "Ses algılanamadı, tekrar deneyebilirsiniz.")}

            direct_result = self._handle_user_text(raw_text, source="voice")
            print(f"[PERF] Sesli komut toplam: {perf_counter() - total_start:.1f} sn", flush=True)
            return {
                "ok": True,
                "data": direct_result,
            }
        except Exception as exc:
            message = "Ses algılanamadı, tekrar deneyebilirsiniz." if "Ses algılanamadı" in str(exc) else f"Sesli komut alınamadı: {exc}"
            return {"ok": False, "error": message}

    def speak_text(self, text: str) -> dict[str, Any]:
        _speak_in_background(text)
        return {"ok": True, "data": {"queued": True}}

    def speak_text_sync(self, text: str) -> dict[str, Any]:
        try:
            return {"ok": True, "data": speak(text)}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Sesli cevap verilirken hata oluştu: {exc}",
            }

    def stop_current_task(self) -> dict[str, Any]:
        try:
            task_result = cancel_current_task()
            speech_result = stop_speech()
            return {"ok": True, "data": {"task": task_result, "speech": speech_result}}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"İşlem durdurulurken hata oluştu: {exc}",
            }

    def check_due_reminders(self) -> dict[str, Any]:
        try:
            return {"ok": True, "data": {"reminders": get_due_reminders(mark_announced=True)}}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Hatırlatıcılar kontrol edilirken hata oluştu: {exc}",
            }

    def consume_wake_event(self) -> dict[str, Any]:
        try:
            if not WAKE_EVENT_PATH.exists():
                return {"ok": True, "data": {"event": None}}
            raw = WAKE_EVENT_PATH.read_text(encoding="utf-8")
            try:
                WAKE_EVENT_PATH.unlink()
            except OSError:
                pass
            event = json.loads(raw)
            if time.time() - float(event.get("created_at", 0)) > 45:
                return {"ok": True, "data": {"event": None}}
            return {"ok": True, "data": {"event": event}}
        except Exception as exc:
            return {"ok": False, "error": f"Uyandırma olayı okunamadı: {exc}"}

    def classify_conversation_text(self, text: str) -> dict[str, Any]:
        try:
            return {"ok": True, "data": classify_conversation_input(text)}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Konuşma kapsamı analiz edilirken hata oluştu: {exc}",
            }

    def _handle_user_text(self, text: str, source: str) -> dict[str, Any]:
        command_text = _strip_wake_prefix(str(text or "").strip())
        if not command_text:
            return _simple_voice_result(False, UNCLEAR_MESSAGE)

        pending = self._try_complete_pending(command_text)
        if pending:
            intent = pending
        else:
            if self.pending_intent and not _looks_like_short_answer(command_text):
                self.pending_intent = None
            start = perf_counter()
            intent = interpret_user_intent(command_text, source=source)
            print(f"[PERF] Intent router: {perf_counter() - start:.1f} sn", flush=True)

        if intent.get("category") == "NEEDS_CLARIFICATION":
            self.pending_intent = {
                "action": intent.get("action"),
                "args": dict(intent.get("args", {})),
                "missing": _missing_fields_for_intent(intent),
            }
            result = run_intent_direct(intent, command_text)
            return _decorate_message_result(result)

        self.pending_intent = None
        result = run_intent_direct(intent, command_text)
        return _decorate_message_result(result)

    def _try_complete_pending(self, text: str) -> dict[str, Any] | None:
        if not self.pending_intent:
            return None

        action = self.pending_intent.get("action")
        args = dict(self.pending_intent.get("args", {}))
        missing = set(self.pending_intent.get("missing", []))

        if action == "CREATE_CALENDAR_EVENT" and "time" in missing and _looks_like_time_answer(text):
            args["when"] = f"{args.get('when', '')} saat {text}".strip()
            return {
                "category": "DESKTOP_ACTION",
                "action": "CREATE_CALENDAR_EVENT",
                "args": args,
                "message": "",
                "spoken_message": "",
                "confidence": 0.95,
            }

        if action == "CREATE_REMINDER" and "when" in missing and _looks_like_time_answer(text):
            args["when"] = f"{args.get('when', '')} {text}".strip()
            return {
                "category": "DESKTOP_ACTION",
                "action": "CREATE_REMINDER",
                "args": args,
                "message": "",
                "spoken_message": "",
                "confidence": 0.92,
            }

        if action == "CREATE_NOTE" and "content" in missing and text.strip():
            args["content"] = text.strip()
            return {
                "category": "DESKTOP_ACTION",
                "action": "CREATE_NOTE",
                "args": args,
                "message": "",
                "spoken_message": "",
                "confidence": 0.92,
            }

        if action == "APPEND_TO_NOTE" and "content" in missing and text.strip():
            args["content"] = text.strip()
            return {
                "category": "DESKTOP_ACTION",
                "action": "APPEND_TO_NOTE",
                "args": args,
                "message": "",
                "spoken_message": "",
                "confidence": 0.92,
            }

        if action == "SEARCH_FILES" and "query" in missing and text.strip():
            args["query"] = text.strip()
            return {
                "category": "DESKTOP_ACTION",
                "action": "SEARCH_FILES",
                "args": args,
                "message": "",
                "spoken_message": "",
                "confidence": 0.92,
            }

        if action == "COPY_TEXT_TO_CLIPBOARD" and "text" in missing and text.strip():
            args["text"] = text.strip()
            return {
                "category": "DESKTOP_ACTION",
                "action": "COPY_TEXT_TO_CLIPBOARD",
                "args": args,
                "message": "",
                "spoken_message": "",
                "confidence": 0.92,
            }

        return None



def _strip_wake_prefix(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""

    normalized = normalize_turkish_for_wake(value)
    for phrase in ("hey nova", "merhaba nova", "nova asistan", "nova"):
        match = re.search(rf"^\s*{re.escape(phrase)}\b", normalized, flags=re.IGNORECASE)
        if match:
            cleaned = normalized[match.end():].strip(" ,.;:-")
            cleaned = re.sub(
                r"^(de|da|şimdi|simdi|lütfen|lutfen|bana|benim için|benim icin|acaba)\b",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned
    return value

def _speak_wake_greeting() -> None:
    _welcome_in_background()


def _speak_in_background(text: str) -> None:
    thread = threading.Thread(target=speak, args=(text,), daemon=True)
    thread.start()


def _welcome_in_background() -> None:
    thread = threading.Thread(target=play_welcome_sound, daemon=True)
    thread.start()


def _simple_voice_result(
    success: bool,
    message: str,
    blocked: bool = False,
    out_of_scope: bool = False,
) -> dict[str, Any]:
    return {
        "success": success,
        "blocked": blocked,
        "out_of_scope": out_of_scope,
        "message": message,
        "spoken_message": message,
    }


def _decorate_message_result(result: dict[str, Any]) -> dict[str, Any]:
    message = str(result.get("message") or result.get("spoken_message") or "").strip()
    if not message:
        message = _message_from_direct_result(result)
    result["message"] = message
    result["spoken_message"] = str(result.get("spoken_message") or message)

    if result.get("needs_clarification") or result.get("status") == "needs_clarification":
        result["success"] = False
        result["needs_clarification"] = True
    if result.get("out_of_scope") or result.get("status") == "out_of_scope":
        result["success"] = False
        result["out_of_scope"] = True
    if result.get("unclear") or result.get("status") == "unclear":
        result["success"] = False
        result["unclear"] = True
    return result


def _message_from_direct_result(result: dict[str, Any]) -> str:
    if result.get("blocked") or result.get("status") == "blocked":
        return UNSAFE_MESSAGE
    if result.get("stopped") or result.get("status") == "stopped":
        return "İşlem durduruldu."
    if result.get("success"):
        first_result = result.get("results", [{}])[0] if result.get("results") else {}
        if not first_result.get("success", False):
            return str(first_result.get("message") or "İşlem sırasında hata oluştu.")
        if first_result.get("action") in {
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
            "GENERAL_AI_ANSWER",
            "RESEARCH_AND_EXPLAIN",
            "PRACTICAL_GUIDE",
            "LOCATION_INFO",
            "UNSAFE_OR_BLOCKED",
        }:
            return str(first_result.get("message") or "İşlem tamamlandı.")
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
            "COPY_TEXT_TO_CLIPBOARD": "Metin panoya kopyalandı.",
            "VOLUME_UP": "Ses artırıldı.",
            "VOLUME_DOWN": "Ses kısıldı.",
            "MUTE_VOLUME": "Ses kapatıldı.",
            "UNMUTE_VOLUME": "Ses açıldı.",
            "PLAY_PAUSE_MEDIA": "Medya oynatma durumu değiştirildi.",
        }
        return action_messages.get(str(first_result.get("action")), "İşlem tamamlandı.")
    first_result = result.get("results", [{}])[0] if result.get("results") else {}
    return str(first_result.get("message") or "İşlem sırasında hata oluştu.")


def _missing_fields_for_intent(intent: dict[str, Any]) -> list[str]:
    action = intent.get("action")
    message = str(intent.get("message") or "")
    if action == "CREATE_CALENDAR_EVENT" and "Saat" in message:
        return ["time"]
    if action == "CREATE_CALENDAR_EVENT":
        return ["date"]
    if action == "CREATE_REMINDER":
        return ["when"]
    if action == "CREATE_NOTE":
        return ["content"]
    if action == "APPEND_TO_NOTE":
        return ["content"]
    if action == "SEARCH_FILES":
        return ["query"]
    if action == "COPY_TEXT_TO_CLIPBOARD":
        return ["text"]
    return []


def _looks_like_time_answer(text: str) -> bool:
    value = str(text or "").strip().casefold()
    return bool(
        re.search(r"\b\d{1,2}[:.]\d{2}\b", value)
        or re.search(r"\b\d{1,2}\b", value)
        or re.search(r"\b\d+\s*(dakika|saat)\s+sonra\b", value)
        or any(word in value for word in ("sabah", "öğlen", "oglen", "akşam", "aksam"))
    )


def _looks_like_short_answer(text: str) -> bool:
    value = str(text or "").strip()
    return len(value.split()) <= 4 or _looks_like_time_answer(value)


def _on_wake_start(window: object) -> None:
    try:
        window.evaluate_js(
            "window.localStorage.setItem('nova_opened_by_wake', '1');"
            "window.dispatchEvent(new Event('nova-wake-opened'));"
        )
    except Exception:
        pass


def main() -> None:
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("pywebview bulunamadı. Kurulum için: pip install -r requirements.txt") from exc

    if not UI_FILE.exists():
        raise SystemExit(f"Arayüz dosyası bulunamadı: {UI_FILE}")

    opened_by_wake_word = "--wake" in sys.argv
    url = UI_FILE.resolve().as_uri()

    window = webview.create_window(
        "NOVA Asistan",
        url,
        js_api=Api(),
        width=980,
        height=720,
        min_size=(760, 560),
    )

    threading.Thread(target=warm_up_voice_model, daemon=True).start()
    if opened_by_wake_word:
        webview.start(_on_wake_start, window)
    else:
        webview.start()


if __name__ == "__main__":
    main()
