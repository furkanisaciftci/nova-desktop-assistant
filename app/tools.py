from __future__ import annotations

import ctypes
import os
import json
import re
import shutil
import socket
import struct
import subprocess
import unicodedata
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

from app.answer_engine import generate_ai_answer
from app.config import (
    ALLOWED_APPS,
    ALLOWED_ROOTS,
    DEFAULT_NEWS_FILE_NAME,
    DEFAULT_NEWS_TOPIC,
    DESKTOP_DIR,
    DOCUMENTS_DIR,
    SPECIAL_FOLDERS,
)
from app.news import build_news_document, fetch_latest_ai_news, summarize_news
from app.web_research import (
    academic_search,
    latest_news_by_topic,
    official_info_search,
    summarize_url,
    validate_public_url,
    web_research_save,
    web_research_summary,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CALENDAR_DIR = DATA_DIR / "calendar"
REMINDERS_PATH = DATA_DIR / "reminders.json"
TODOS_PATH = DATA_DIR / "todos.json"
NOTES_INDEX_PATH = DATA_DIR / "notes.json"
SCREENSHOTS_DIR_NAME = "NOVA_Screenshots"


def execute_plan(plan: dict[str, Any], cancel_event: Any = None) -> list[dict[str, Any]]:
    if _is_cancelled(cancel_event):
        return [_cancelled_result()]

    if plan.get("action") == "MULTI_STEP":
        results = []
        for index, step in enumerate(plan.get("steps", []), start=1):
            if _is_cancelled(cancel_event):
                result = _cancelled_result()
                result["step"] = index
                results.append(result)
                break
            result = _execute_single(step.get("action", ""), step.get("args", {}))
            result["step"] = index
            results.append(result)
        return results

    if _is_cancelled(cancel_event):
        return [_cancelled_result()]
    return [_execute_single(plan.get("action", ""), plan.get("args", {}))]


def _execute_single(action: str, args: dict[str, str]) -> dict[str, Any]:
    try:
        if action == "CREATE_FOLDER":
            path = create_folder(args.get("path", ""))
            return _ok(action, f"Klasör oluşturuldu veya zaten vardı: {path}", path)

        if action == "WRITE_TEXT_FILE":
            path = write_text_file(args.get("path", ""), args.get("content", ""))
            return _ok(action, f"Metin dosyası yazıldı: {path}", path)

        if action == "OPEN_FOLDER":
            path = open_folder(args.get("path", ""))
            return _ok(action, f"Klasör açıldı: {path}", path)

        if action == "OPEN_APP":
            app_name = open_app(args.get("app_name", ""))
            return _ok(action, f"Uygulama açıldı: {app_name}", app_name)

        if action == "SAVE_LATEST_AI_NEWS":
            path = save_latest_ai_news(
                args.get("path", ""),
                topic=args.get("topic", "") or DEFAULT_NEWS_TOPIC,
                file_name=args.get("file_name", "") or DEFAULT_NEWS_FILE_NAME,
            )
            return _ok(action, f"Son yapay zeka haberi kaydedildi: {path}", path)

        if action == "OPEN_WEBSITE":
            url = open_website(args.get("url", "") or args.get("site", ""))
            return _ok(action, f"Web sitesi açıldı: {url}", url)

        if action == "CREATE_NOTE":
            path = create_note(
                folder=args.get("folder", ""),
                file_name=args.get("file_name", ""),
                content=args.get("content", ""),
            )
            return _ok(action, f"Not dosyası oluşturuldu: {path}", path)

        if action == "APPEND_TO_NOTE":
            path = append_to_note(args.get("content", ""), args.get("file_name", ""))
            return _ok(action, f"Nota metin eklendi: {path}", path)

        if action == "CREATE_PROJECT_STRUCTURE":
            path = create_project_structure(args.get("path", ""), args.get("folders", ""))
            return _ok(action, f"Proje yapısı oluşturuldu: {path}", path)

        if action == "SEARCH_TOPIC_AND_SAVE":
            path = search_topic_and_save(
                topic=args.get("topic", ""),
                path_text=args.get("path", ""),
                file_name=args.get("file_name", ""),
            )
            return _ok(action, f"Kısa araştırma dosyaya kaydedildi: {path}", path)

        if action == "OPEN_SPECIAL_FOLDER":
            path = open_special_folder(args.get("folder", ""))
            return _ok(action, f"Klasör açıldı: {path}", path)

        if action == "WEB_SEARCH":
            url = web_search(args.get("query", ""))
            return _ok(action, f"Web araması açıldı: {url}", url)

        if action == "WEB_RESEARCH_SUMMARY":
            return _ok(action, web_research_summary(args.get("topic", "")), "")

        if action == "WEB_RESEARCH_SAVE":
            return _ok(action, web_research_save(args.get("topic", ""), args.get("file_name", "")), "")

        if action == "SUMMARIZE_URL":
            return _ok(action, summarize_url(args.get("url", "")), "")

        if action == "LATEST_NEWS_BY_TOPIC":
            return _ok(action, latest_news_by_topic(args.get("topic", "")), "")

        if action == "OFFICIAL_INFO_SEARCH":
            return _ok(action, official_info_search(args.get("topic", "")), "")

        if action == "ACADEMIC_SEARCH":
            max_results = args.get("max_results", "5")
            try:
                max_results_int = int(max_results or "5")
            except ValueError:
                max_results_int = 5
            result = academic_search(
                args.get("topic", ""),
                max_results=max_results_int,
                save_to_file=_as_bool(args.get("save_to_file", "")),
                summary_level=args.get("summary_level", "medium"),
            )
            return _ok(action, result, result.get("path", ""))

        if action == "GENERAL_AI_ANSWER":
            return _ok(action, generate_ai_answer(args.get("question", ""), args.get("mode", "general")), "")

        if action == "RESEARCH_AND_EXPLAIN":
            return _ok(action, generate_ai_answer(args.get("topic", ""), "research"), "")

        if action == "PRACTICAL_GUIDE":
            return _ok(action, generate_ai_answer(args.get("question", ""), "guide"), "")

        if action == "LOCATION_INFO":
            return _ok(action, generate_ai_answer(args.get("topic", ""), "location"), "")

        if action == "UNSAFE_OR_BLOCKED":
            return _ok(
                action,
                args.get(
                    "message",
                    "Bu konuda yardımcı olamam. Sistem güvenliği ve kullanıcı verilerini korumak için bu tür işlemler desteklenmiyor.",
                ),
                "",
            )

        if action == "OPEN_COMMON_APP":
            app_name = open_common_app(args.get("app_name", ""))
            return _ok(action, f"Uygulama açıldı: {app_name}", app_name)

        if action == "DATE_TIME_ANSWER":
            message = date_time_answer(args.get("question", ""))
            return _ok(action, message, "")

        if action == "CREATE_CALENDAR_EVENT":
            when_text = args.get("when", "") or " ".join(
                part for part in (args.get("date", ""), args.get("time", "")) if part
            )
            path = create_calendar_event(
                args.get("title", ""),
                when_text,
                args.get("duration_minutes", ""),
            )
            return _ok(action, "Takvim etkinliği oluşturuldu.", path)

        if action == "CREATE_REMINDER":
            reminder = create_reminder(args.get("title", ""), args.get("when", ""))
            return _ok(action, "Hatırlatıcı oluşturuldu.", reminder.get("id", ""))

        if action == "LIST_REMINDERS":
            message = list_reminders()
            return _ok(action, message, "")

        if action == "COMPLETE_REMINDER":
            reminder = complete_reminder(args.get("title", ""))
            return _ok(action, "Hatırlatıcı tamamlandı.", reminder.get("id", ""))

        if action == "ADD_TODO":
            todo = add_todo(args.get("title", ""))
            return _ok(action, "Yapılacaklara eklendi.", todo.get("id", ""))

        if action == "LIST_TODOS":
            message = list_todos()
            return _ok(action, message, "")

        if action == "COMPLETE_TODO":
            todo = complete_todo(args.get("title", ""))
            return _ok(action, "Yapılacak tamamlandı.", todo.get("id", ""))

        if action == "TAKE_SCREENSHOT":
            path = take_screenshot()
            return _ok(action, f"Ekran görüntüsü kaydedildi: {path}", path)

        if action == "SEARCH_FILES":
            message = search_files(args.get("query", ""), args.get("folder", ""))
            return _ok(action, message, "")

        if action == "SYSTEM_INFO":
            message = system_info(args.get("topic", ""))
            return _ok(action, message, "")

        if action == "VOLUME_UP":
            volume_up()
            return _ok(action, "Ses artırıldı.", "")

        if action == "VOLUME_DOWN":
            volume_down()
            return _ok(action, "Ses kısıldı.", "")

        if action == "MUTE_VOLUME":
            mute_volume()
            return _ok(action, "Ses kapatıldı.", "")

        if action == "UNMUTE_VOLUME":
            unmute_volume()
            return _ok(action, "Ses açıldı.", "")

        if action == "VOLUME_CONTROL":
            message = volume_control(args.get("operation", ""))
            return _ok(action, message, "")

        if action == "PLAY_PAUSE_MEDIA":
            play_pause_media()
            return _ok(action, "Medya oynatma durumu değiştirildi.", "")

        if action == "COPY_TEXT_TO_CLIPBOARD":
            copy_text_to_clipboard(args.get("text", ""))
            return _ok(action, "Metin panoya kopyalandı.", "")

        if action == "ANSWER_ONLY":
            return _ok(action, args.get("message", "İşlem gerekmiyor."), "")

        if action == "ANSWER_NOVA_CAPABILITIES":
            return _ok(
                action,
                (
                    "Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı, "
                    "takvim ve benzeri güvenli masaüstü işlemlerinde yardımcı olabilirim."
                ),
                "",
            )

        if action == "OUT_OF_SCOPE_RESPONSE":
            return _ok(
                action,
                args.get(
                    "message",
                    "Ben masaüstü işlemlerine odaklı bir sesli asistanım. Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı ve takvim gibi bilgisayar işlemlerinde yardımcı olabilirim.",
                ),
                "",
            )

        if action == "UNSAFE_REQUEST":
            return _ok(action, args.get("message", "Bu işlem güvenlik nedeniyle uygulanmadı."), "")

        if action == "NEEDS_CLARIFICATION":
            return _ok(action, args.get("message", "Biraz daha bilgi verir misiniz?"), "")

        return _fail(action, f"Desteklenmeyen action: {action}")
    except Exception as exc:
        return _fail(action, str(exc))


def create_folder(path_text: str) -> Path:
    path = resolve_safe_desktop_path(path_text)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text_file(path_text: str, content: str) -> Path:
    path = resolve_safe_desktop_path(path_text)
    if path.suffix.lower() != ".txt":
        raise ValueError("Sadece .txt dosyası yazma desteklenir.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def open_folder(path_text: str) -> Path:
    path = resolve_safe_desktop_path(path_text)
    if not path.exists():
        raise FileNotFoundError(f"Klasör bulunamadı: {path}")
    if not path.is_dir():
        raise ValueError("OPEN_FOLDER sadece klasör açabilir.")
    os.startfile(path)  # type: ignore[attr-defined]
    return path


def open_app(app_name: str) -> str:
    normalized = " ".join(app_name.casefold().split())
    executable = ALLOWED_APPS.get(normalized)
    if not executable:
        allowed = ", ".join(sorted(ALLOWED_APPS))
        raise ValueError(f"Bu uygulama izinli değil. İzinli uygulamalar: {allowed}")
    resolved_executable = _resolve_allowed_executable(executable)
    subprocess.Popen([resolved_executable], shell=False)
    return app_name


def open_website(site_or_url: str) -> str:
    url = _resolve_safe_website(site_or_url)
    webbrowser.open(url)
    return url


def web_search(query: str) -> str:
    safe_query = " ".join(str(query or "").split())
    if not safe_query:
        raise ValueError("Aranacak konu belirtilmedi.")
    url = "https://www.google.com/search?q=" + quote_plus(safe_query)
    webbrowser.open(url)
    return url


def open_common_app(app_name: str) -> str:
    return open_app(app_name)


def create_note(folder: str = "", file_name: str = "", content: str = "") -> Path:
    base = _note_base_folder(folder)
    safe_file_name = _safe_txt_file_name(file_name or "nova_notu.txt")
    note_content = (content or "NOVA tarafından oluşturulan not.").strip()
    path = (base / safe_file_name).resolve()
    if not _is_under_allowed_root(path):
        raise ValueError("Güvenlik nedeniyle not konumu engellendi.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_content + "\n", encoding="utf-8")
    _record_nova_note(path)
    return path


def append_to_note(content: str, file_name: str = "") -> Path:
    note_content = str(content or "").strip()
    if not note_content:
        raise ValueError("Eklenecek metin belirtilmedi.")

    notes = _load_json_list(NOTES_INDEX_PATH)
    target = _find_recorded_note(notes, file_name)
    if target is None:
        raise ValueError("NOVA tarafından oluşturulmuş uygun not bulunamadı.")

    path = Path(str(target.get("path", ""))).resolve()
    if not path.exists() or path.suffix.lower() != ".txt" or not _is_under_allowed_root(path):
        raise ValueError("Not dosyası güvenli alanda bulunamadı.")

    with path.open("a", encoding="utf-8") as file:
        file.write(note_content + "\n")
    target["updated_at"] = datetime.now().isoformat(timespec="minutes")
    _save_json_list(NOTES_INDEX_PATH, notes)
    return path


def create_project_structure(path_text: str, folders_text: str = "") -> Path:
    root = resolve_safe_desktop_path(path_text or "Proje")
    root.mkdir(parents=True, exist_ok=True)
    folders = _project_folders(folders_text)
    for folder in folders:
        (root / _safe_folder_name(folder)).mkdir(parents=True, exist_ok=True)
    return root


def search_topic_and_save(topic: str, path_text: str = "", file_name: str = "") -> Path:
    clean_topic = " ".join((topic or DEFAULT_NEWS_TOPIC).split())
    safe_file_name = _safe_txt_file_name(file_name or f"{_safe_slug(clean_topic)}_ozet.txt")
    output_path = _resolve_news_output_path(path_text or safe_file_name, safe_file_name)
    try:
        news_item = fetch_latest_ai_news(clean_topic)
        summary = summarize_news(news_item)
        document = _build_topic_document(clean_topic, news_item, summary)
    except Exception as exc:
        document = (
            f"Konu: {clean_topic}\n\n"
            "İnternet kaynağına ulaşılamadı.\n"
            f"Detay: {exc}\n"
        )
    return write_text_file(str(output_path.relative_to(DESKTOP_DIR)), document)


def open_special_folder(folder: str) -> Path:
    key = _normalize_key(folder)
    path = SPECIAL_FOLDERS.get(key)
    if not path:
        allowed = ", ".join(sorted(SPECIAL_FOLDERS))
        raise ValueError(f"Bu özel klasör desteklenmiyor. Desteklenenler: {allowed}")
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(path)  # type: ignore[attr-defined]
    return path


def date_time_answer(question: str = "") -> str:
    now = datetime.now()
    normalized = _normalize_key(question)
    days = {
        0: "Pazartesi",
        1: "Salı",
        2: "Çarşamba",
        3: "Perşembe",
        4: "Cuma",
        5: "Cumartesi",
        6: "Pazar",
    }
    if "saat" in normalized:
        return f"Saat {now:%H:%M}."
    if "tarih" in normalized:
        return f"Bugünün tarihi {now:%d.%m.%Y}."
    if "gunlerden" in normalized or "hangi gun" in normalized or normalized.strip() in {"bugun ne", "bugun"}:
        return f"Bugün günlerden {days[now.weekday()]}."
    return f"Bugünün tarihi {now:%d.%m.%Y}."


def create_calendar_event(title: str, when_text: str, duration_minutes: str | int = 60) -> Path:
    event_title = _clean_title(title or _strip_time_words(when_text) or "NOVA Etkinliği")
    start_time = _parse_turkish_datetime(when_text)
    if start_time is None:
        raise ValueError("Tarih veya saat bilgisi anlaşılamadı.")
    try:
        duration = int(duration_minutes or 60)
    except (TypeError, ValueError):
        duration = 60
    duration = max(15, min(duration, 480))
    end_time = start_time + timedelta(minutes=duration)

    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"{start_time:%Y%m%d_%H%M}_{_safe_slug(event_title)}.ics"
    path = (CALENDAR_DIR / file_name).resolve()
    if not _is_under_base_dir(path):
        raise ValueError("Takvim dosyası güvenli alana yazılamadı.")

    content = _build_ics(event_title, start_time, end_time)
    path.write_text(content, encoding="utf-8")
    os.startfile(path)  # type: ignore[attr-defined]
    return path


def create_reminder(title: str, when_text: str) -> dict[str, Any]:
    reminder_title = _clean_title(title or _strip_time_words(when_text) or "NOVA hatırlatıcısı")
    due_time = _parse_turkish_datetime(when_text)
    if due_time is None:
        raise ValueError("Tarih veya saat bilgisi anlaşılamadı.")

    reminders = _load_json_list(REMINDERS_PATH)
    reminder = {
        "id": _next_id("reminder", reminders),
        "title": reminder_title,
        "due_time": due_time.isoformat(timespec="minutes"),
        "created_at": datetime.now().isoformat(timespec="minutes"),
        "completed": False,
        "announced": False,
    }
    reminders.append(reminder)
    _save_json_list(REMINDERS_PATH, reminders)
    return reminder


def list_reminders() -> str:
    reminders = [item for item in _load_json_list(REMINDERS_PATH) if not item.get("completed")]
    if not reminders:
        return "Kayıtlı hatırlatıcı bulunamadı."
    lines = []
    for item in reminders[:8]:
        due = _format_iso_datetime(item.get("due_time", ""))
        lines.append(f"{due} - {item.get('title', '')}")
    return "Hatırlatıcılarınız:\n" + "\n".join(lines)


def complete_reminder(title: str) -> dict[str, Any]:
    target = _normalize_key(title)
    reminders = _load_json_list(REMINDERS_PATH)
    candidates = [item for item in reminders if not item.get("completed")]
    if not candidates:
        raise ValueError("Kayıtlı hatırlatıcı bulunamadı.")

    best_item = None
    if target:
        for item in candidates:
            item_title = _normalize_key(item.get("title", ""))
            if target in item_title or item_title in target:
                best_item = item
                break
    if best_item is None and len(candidates) == 1:
        best_item = candidates[0]
    if best_item is None:
        raise ValueError("Hangi hatırlatıcıyı tamamlayacağımı belirtir misiniz?")

    best_item["completed"] = True
    best_item["completed_at"] = datetime.now().isoformat(timespec="minutes")
    _save_json_list(REMINDERS_PATH, reminders)
    return best_item


def get_due_reminders(mark_announced: bool = True) -> list[dict[str, Any]]:
    now = datetime.now()
    reminders = _load_json_list(REMINDERS_PATH)
    due_items = []
    changed = False
    for item in reminders:
        if item.get("completed") or item.get("announced"):
            continue
        try:
            due_time = datetime.fromisoformat(str(item.get("due_time", "")))
        except ValueError:
            continue
        if due_time <= now:
            due_items.append(item)
            if mark_announced:
                item["announced"] = True
                changed = True
    if changed:
        _save_json_list(REMINDERS_PATH, reminders)
    return due_items


def add_todo(title: str) -> dict[str, Any]:
    todo_title = _clean_title(title or "Yeni yapılacak")
    todos = _load_json_list(TODOS_PATH)
    todo = {
        "id": _next_id("todo", todos),
        "title": todo_title,
        "created_at": datetime.now().isoformat(timespec="minutes"),
        "completed": False,
    }
    todos.append(todo)
    _save_json_list(TODOS_PATH, todos)
    return todo


def list_todos() -> str:
    todos = [item for item in _load_json_list(TODOS_PATH) if not item.get("completed")]
    if not todos:
        return "Yapılacak listeniz boş."
    lines = [f"- {item.get('title', '')}" for item in todos[:10]]
    return "Yapılacaklarınız:\n" + "\n".join(lines)


def complete_todo(title: str) -> dict[str, Any]:
    target = _normalize_key(title)
    todos = _load_json_list(TODOS_PATH)
    best_item = None
    for item in todos:
        if item.get("completed"):
            continue
        item_title = _normalize_key(item.get("title", ""))
        if target and (target in item_title or item_title in target):
            best_item = item
            break
    if best_item is None:
        raise ValueError("Tamamlanacak yapılacak bulunamadı.")
    best_item["completed"] = True
    best_item["completed_at"] = datetime.now().isoformat(timespec="minutes")
    _save_json_list(TODOS_PATH, todos)
    return best_item


def take_screenshot() -> Path:
    screenshot_dir = resolve_safe_desktop_path(SCREENSHOTS_DIR_NAME)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = screenshot_dir / f"nova_ekran_goruntusu_{timestamp}.png"

    try:
        from PIL import ImageGrab

        image = ImageGrab.grab()
        image.save(png_path)
        return png_path
    except ImportError:
        bmp_path = screenshot_dir / f"nova_ekran_goruntusu_{timestamp}.bmp"
        _take_screenshot_bmp(bmp_path)
        return bmp_path


def search_files(query: str, folder: str = "") -> str:
    normalized_query = _normalize_key(query)
    if not normalized_query:
        raise ValueError("Hangi dosyayı aramamı istersiniz?")

    roots = _search_roots(folder)
    matches = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for current_root, _dirs, files in os.walk(root):
            current_path = Path(current_root)
            if not _is_under_search_root(current_path, roots):
                continue
            for file_name in files:
                if normalized_query in _normalize_key(file_name):
                    matches.append(current_path / file_name)
                    if len(matches) >= 10:
                        break
            if len(matches) >= 10:
                break
        if len(matches) >= 10:
            break

    if not matches:
        return "Eşleşen dosya bulunamadı."
    lines = [str(path) for path in matches]
    return "Bulunan dosyalar:\n" + "\n".join(lines)


def system_info(topic: str) -> str:
    normalized = _normalize_key(topic)
    if "pil" in normalized or "batarya" in normalized:
        return _battery_status()
    if "internet" in normalized or "bagli" in normalized:
        return _internet_status()
    if "disk" in normalized or "bos" in normalized or "alan" in normalized:
        total, used, free = shutil.disk_usage(DESKTOP_DIR.anchor or str(DESKTOP_DIR))
        return f"Diskte yaklaşık {_format_bytes(free)} boş alan var."
    return "Sistem bilgisi için pil, disk veya internet durumunu sorabilirsiniz."


def volume_up() -> None:
    _press_media_key(0xAF)


def volume_down() -> None:
    _press_media_key(0xAE)


def mute_volume() -> None:
    _press_media_key(0xAD)


def unmute_volume() -> None:
    _press_media_key(0xAD)


def volume_control(operation: str) -> str:
    normalized = _normalize_key(operation)
    if normalized in {"up", "artir", "arttir", "yukselt", "increase"}:
        volume_up()
        return "Ses artırıldı."
    if normalized in {"down", "kis", "azalt", "dusur", "decrease"}:
        volume_down()
        return "Ses kısıldı."
    if normalized in {"mute", "kapat", "sessiz", "sessize al"}:
        mute_volume()
        return "Ses kapatıldı."
    if normalized in {"unmute", "ac", "sessizden cikar", "sessizi kapat"}:
        unmute_volume()
        return "Ses açıldı."
    raise ValueError("Ses kontrol işlemi anlaşılamadı.")


def play_pause_media() -> None:
    _press_media_key(0xB3)


def copy_text_to_clipboard(text: str) -> None:
    value = str(text or "").strip()
    if not value:
        raise ValueError("Panoya kopyalanacak metin belirtilmedi.")
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(value)
        root.update()
        root.destroy()
    except Exception as exc:
        raise RuntimeError(f"Pano erişimi kullanılamadı: {exc}") from exc


def save_latest_ai_news(path_text: str, topic: str = DEFAULT_NEWS_TOPIC, file_name: str = DEFAULT_NEWS_FILE_NAME) -> Path:
    output_path = _resolve_news_output_path(path_text, file_name)
    news_item = fetch_latest_ai_news(topic)
    summary = summarize_news(news_item)
    document = build_news_document(news_item, summary)
    return write_text_file(str(output_path.relative_to(DESKTOP_DIR)), document)


def _resolve_safe_website(site_or_url: str) -> str:
    text = " ".join(str(site_or_url or "").strip().split())
    if not text:
        raise ValueError("Açılacak web sitesi belirtilmedi.")

    known_sites = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://github.com",
        "selçuk üniversitesi": "https://www.selcuk.edu.tr",
        "selcuk universitesi": "https://www.selcuk.edu.tr",
        "cecihome": "https://www.cecihome.com.tr",
        "ceci home": "https://www.cecihome.com.tr",
        "cecihome.com.tr": "https://www.cecihome.com.tr",
    }
    normalized = _normalize_key(text)
    if normalized in known_sites:
        return known_sites[normalized]

    candidate = text
    if "://" not in candidate:
        candidate = "https://" + candidate

    lowered_candidate = candidate.casefold()
    if lowered_candidate.startswith(("javascript:", "file:", "data:")):
        raise ValueError("Riskli web adresleri açılamaz.")

    parsed = urlparse(validate_public_url(candidate))
    host = (parsed.hostname or "").casefold()
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host):
        raise ValueError("Geçerli bir domain adresi belirtilmeli.")
    return parsed.geturl()


def _resolve_allowed_executable(executable: str) -> str:
    found = shutil.which(executable)
    if found:
        return found

    common_locations = {
        "chrome": [
            Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ],
        "code": [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft VS Code" / "Code.exe",
        ],
    }
    for path in common_locations.get(executable.casefold(), []):
        if path.exists():
            return str(path)

    return executable


def _note_base_folder(folder: str) -> Path:
    key = _normalize_key(folder)
    if key in {"documents", "belgeler"}:
        return DOCUMENTS_DIR
    return DESKTOP_DIR


def _record_nova_note(path: Path) -> None:
    notes = _load_json_list(NOTES_INDEX_PATH)
    resolved = str(path.resolve())
    now = datetime.now().isoformat(timespec="minutes")
    for note in notes:
        if str(note.get("path", "")) == resolved:
            note["updated_at"] = now
            break
    else:
        notes.append({"path": resolved, "created_at": now, "updated_at": now})
    _save_json_list(NOTES_INDEX_PATH, notes[-50:])


def _find_recorded_note(notes: list[dict[str, Any]], file_name: str = "") -> dict[str, Any] | None:
    candidates = []
    normalized_name = _normalize_key(file_name)
    for note in notes:
        path = Path(str(note.get("path", "")))
        if not path.exists():
            continue
        if normalized_name and normalized_name not in _normalize_key(path.name):
            continue
        candidates.append(note)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("updated_at", item.get("created_at", ""))), reverse=True)
    return candidates[0]


def _search_roots(folder: str) -> list[Path]:
    key = _normalize_key(folder)
    if key in {"desktop", "masaustu"}:
        return [SPECIAL_FOLDERS["desktop"]]
    if key in {"documents", "belgeler"}:
        return [SPECIAL_FOLDERS["documents"]]
    if key in {"downloads", "indirilenler"}:
        return [SPECIAL_FOLDERS["downloads"]]
    if key in {"pictures", "resimler"}:
        return [SPECIAL_FOLDERS["pictures"]]
    return [
        SPECIAL_FOLDERS["desktop"],
        SPECIAL_FOLDERS["documents"],
        SPECIAL_FOLDERS["downloads"],
        SPECIAL_FOLDERS["pictures"],
    ]


def _is_under_search_root(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved == root.resolve() or root.resolve() in resolved.parents for root in roots)


def _battery_status() -> str:
    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_byte),
            ("BatteryFlag", ctypes.c_byte),
            ("BatteryLifePercent", ctypes.c_byte),
            ("SystemStatusFlag", ctypes.c_byte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    status = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return "Pil durumu alınamadı."
    percent = int(status.BatteryLifePercent)
    if percent < 0 or percent > 100:
        return "Pil yüzdesi bu cihazda alınamadı."
    charging = "şarjda" if int(status.ACLineStatus) == 1 else "bataryada"
    return f"Pil %{percent}, cihaz {charging}."


def _internet_status() -> str:
    try:
        with socket.create_connection(("www.google.com", 443), timeout=3):
            return "İnternet bağlantısı var."
    except OSError:
        return "İnternet bağlantısı kontrolünde bağlantı kurulamadı."


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def _press_media_key(vk_code: int) -> None:
    user32 = ctypes.windll.user32
    keyeventf_keyup = 0x0002
    user32.keybd_event(vk_code, 0, 0, 0)
    user32.keybd_event(vk_code, 0, keyeventf_keyup, 0)


def _project_folders(folders_text: str) -> list[str]:
    defaults = ["kodlar", "raporlar", "kaynaklar", "belgeler", "çıktılar"]
    if not folders_text:
        return defaults
    splitter = r"\s*,\s*|\s*;\s*"
    if "," not in folders_text and ";" not in folders_text:
        splitter = r"\s+"
    custom = [
        item.strip(" .\"'")
        for item in re.split(splitter, folders_text)
        if item.strip(" .\"'")
    ]
    merged = defaults + custom
    unique = []
    for folder in merged:
        if folder and folder not in unique:
            unique.append(folder)
    return unique


def _build_topic_document(topic: str, news_item: dict[str, str], summary: str) -> str:
    return "\n".join(
        [
            f"Konu: {topic}",
            "",
            f"Başlık: {news_item.get('title', '')}",
            f"Kaynak: {news_item.get('source', '') or 'Bilinmiyor'}",
            f"Tarih: {news_item.get('published', '') or 'Bilinmiyor'}",
            f"Bağlantı: {news_item.get('link', '')}",
            "",
            "Kısa Özet:",
            summary.strip(),
            "",
        ]
    )


def _build_ics(title: str, start_time: datetime, end_time: datetime) -> str:
    created = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    uid = f"nova-{start_time:%Y%m%d%H%M%S}-{_safe_slug(title)}@local"
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//NOVA//Desktop Assistant//TR",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{created}",
            f"DTSTART:{start_time:%Y%m%dT%H%M%S}",
            f"DTEND:{end_time:%Y%m%dT%H%M%S}",
            f"SUMMARY:{_escape_ics(title)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def _parse_turkish_datetime(text: str) -> datetime | None:
    normalized = _normalize_key(text)
    now = datetime.now().replace(second=0, microsecond=0)

    relative_match = re.search(r"(\d+)\s*(dakika|saat)\s+sonra", normalized)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        return now + (timedelta(minutes=amount) if unit == "dakika" else timedelta(hours=amount))

    hour, minute = _extract_time(normalized)
    date_value = _extract_date(normalized, now)
    if date_value is None:
        return None
    if hour is None:
        hour, minute = 9, 0
    return date_value.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _extract_time(normalized: str) -> tuple[int | None, int]:
    match = re.search(r"saat\s*(\d{1,2})(?:[:.](\d{2}))?", normalized)
    if not match:
        match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", normalized)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
    else:
        word_hours = {
            "bire": 1,
            "ikiye": 14,
            "uce": 3,
            "dorde": 4,
            "bese": 5,
            "altiya": 6,
            "yediye": 7,
            "sekize": 8,
            "dokuza": 9,
            "ona": 10,
            "on bire": 11,
            "on ikiye": 12,
        }
        for word, value in word_hours.items():
            if word in normalized:
                return value, 0
        return None, 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, 0
    return hour, minute


def _extract_date(normalized: str, now: datetime) -> datetime | None:
    if "bugun" in normalized:
        return now
    if "yarin" in normalized:
        return now + timedelta(days=1)

    weekdays = {
        "pazartesi": 0,
        "sali": 1,
        "carsamba": 2,
        "persembe": 3,
        "cuma": 4,
        "cumartesi": 5,
        "pazar": 6,
    }
    for name, weekday in weekdays.items():
        if name in normalized:
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return now + timedelta(days=days_ahead)

    numeric = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b", normalized)
    if numeric:
        day = int(numeric.group(1))
        month = int(numeric.group(2))
        year = int(numeric.group(3) or now.year)
        try:
            candidate = now.replace(year=year, month=month, day=day)
            if candidate.date() < now.date() and not numeric.group(3):
                candidate = candidate.replace(year=year + 1)
            return candidate
        except ValueError:
            return None

    months = {
        "ocak": 1,
        "subat": 2,
        "mart": 3,
        "nisan": 4,
        "mayis": 5,
        "haziran": 6,
        "temmuz": 7,
        "agustos": 8,
        "eylul": 9,
        "ekim": 10,
        "kasim": 11,
        "aralik": 12,
    }
    month_match = re.search(r"\b(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?\b", normalized)
    if month_match and month_match.group(2) in months:
        day = int(month_match.group(1))
        month = months[month_match.group(2)]
        year = int(month_match.group(3) or now.year)
        try:
            candidate = now.replace(year=year, month=month, day=day)
            if candidate.date() < now.date() and not month_match.group(3):
                candidate = candidate.replace(year=year + 1)
            return candidate
        except ValueError:
            return None

    return None


def _strip_time_words(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\b(bugün|bugun|yarın|yarin)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(pazartesi|salı|sali|çarşamba|carsamba|perşembe|persembe|cuma|cumartesi|pazar)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}[:.]\d{2}\b", "", cleaned)
    cleaned = re.sub(r"\bsaat\s+\d{1,2}(?:[:.]\d{2})?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+\s*(?:dakika|saat)\s+sonra\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:bire|ikiye|üçe|uce|dörde|dorde|beşe|bese|altıya|altiya|yediye|sekize|dokuza|ona|on bire|on ikiye)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:ekle|oluştur|olustur|hatırlat|hatirlat|randevusu|randevu)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[’'` ]*(?:e|a|de|da|ye|ya)\s+", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.strip(" .\"'").split())


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"\b(?:bana|beni|yapılacaklara|yapilacaklara|listeye)\b", "", str(title or ""), flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:ekle|oluştur|olustur|hatırlat|hatirlat|kaydet|işaretle|isaretle)\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.strip(" .\"'").split()) or "NOVA"


def _escape_ics(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save_json_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_id(prefix: str, items: list[dict[str, Any]]) -> str:
    return f"{prefix}_{len(items) + 1}_{datetime.now():%Y%m%d%H%M%S}"


def _format_iso_datetime(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def _is_under_base_dir(path: Path) -> bool:
    base = BASE_DIR.resolve()
    resolved = path.resolve()
    return resolved == base or base in resolved.parents


def _take_screenshot_bmp(path: Path) -> None:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, 0, 0, 0x00CC0020)

    row_size = ((width * 3 + 3) // 4) * 4
    image_size = row_size * height
    buffer = ctypes.create_string_buffer(image_size)

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    header = BitmapInfoHeader()
    header.biSize = ctypes.sizeof(BitmapInfoHeader)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 24
    header.biCompression = 0
    header.biSizeImage = image_size

    try:
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        file_header_size = 14
        info_header_size = ctypes.sizeof(BitmapInfoHeader)
        pixel_offset = file_header_size + info_header_size
        file_size = pixel_offset + image_size
        with path.open("wb") as file:
            file.write(struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset))
            file.write(bytes(header))
            file.write(buffer.raw)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)


def resolve_safe_desktop_path(path_text: str) -> Path:
    cleaned = _clean_path_text(path_text)
    if not cleaned:
        raise ValueError("Boş path kabul edilmez.")

    candidate = Path(cleaned)
    if candidate.is_absolute():
        raise ValueError("Mutlak path desteklenmez; Masaüstü'ne göre göreli path kullanın.")

    resolved = (DESKTOP_DIR / candidate).resolve()
    if not _is_under_allowed_root(resolved):
        raise ValueError("Güvenlik nedeniyle Masaüstü dışına çıkış engellendi.")
    return resolved


def _resolve_news_output_path(path_text: str, file_name: str) -> Path:
    path = resolve_safe_desktop_path(path_text)
    if path.suffix.lower() == ".txt":
        return path
    safe_file_name = Path(_clean_path_text(file_name)).name
    if not safe_file_name.lower().endswith(".txt"):
        safe_file_name = DEFAULT_NEWS_FILE_NAME
    return path / safe_file_name


def _clean_path_text(path_text: str) -> str:
    cleaned = str(path_text or "").strip().replace("\\", "/")
    lowered = cleaned.casefold().strip("/")
    for prefix in ("masaustu/", "masa\u00fcst\u00fc/", "desktop/"):
        if lowered.startswith(prefix):
            cleaned = cleaned.split("/", 1)[1]
            break
    if ".." in Path(cleaned).parts:
        raise ValueError("Path traversal girişimi engellendi.")
    return cleaned


def _is_under_allowed_root(path: Path) -> bool:
    return any(path == root.resolve() or root.resolve() in path.parents for root in ALLOWED_ROOTS)


def _safe_txt_file_name(file_name: str) -> str:
    name = Path(_clean_path_text(file_name or "nova_notu.txt")).name
    stem = _safe_slug(Path(name).stem)
    if not stem:
        stem = "nova_notu"
    return stem + ".txt"


def _safe_folder_name(folder_name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", str(folder_name or "")).strip()
    if not cleaned or cleaned in {".", ".."}:
        return "klasor"
    return cleaned


def _safe_slug(value: str) -> str:
    normalized = _normalize_key(value)
    cleaned = re.sub(r"[^a-z0-9_-]+", "_", normalized).strip("_")
    return cleaned or "nova"


def _normalize_key(value: str) -> str:
    lowered = str(value or "").casefold().replace("ı", "i")
    normalized = unicodedata.normalize("NFKD", lowered)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(ascii_text.split())


def _ok(action: str, message: str, path_or_value: object) -> dict[str, Any]:
    if isinstance(message, dict):
        screen_message = str(message.get("screen_message") or message.get("message") or "İşlem tamamlandı.")
        spoken_message = str(message.get("spoken_message") or screen_message)
        value = str(message.get("path") or path_or_value or "")
        return {
            "action": action,
            "success": True,
            "message": screen_message,
            "spoken_message": spoken_message,
            "value": value,
        }
    return {"action": action, "success": True, "message": message, "value": str(path_or_value)}


def _fail(action: str, message: str) -> dict[str, Any]:
    return {"action": action, "success": False, "message": message}


def _is_cancelled(cancel_event: Any) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def _cancelled_result() -> dict[str, Any]:
    return {"action": "CANCELLED", "success": False, "stopped": True, "message": "İşlem durduruldu."}


def _as_bool(value: str) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "evet", "yes", "kaydet"}
