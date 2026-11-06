from __future__ import annotations

import ctypes
import json
import re
import subprocess
import sys
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from app.audio_utils import DEFAULT_SAMPLE_RATE, normalize_turkish_for_wake, record_until_silence
from app.config import WAKE_RECORD_SECONDS, WAKE_WAIT_SECONDS, WHISPER_MODEL
from app.tools import get_due_reminders
from app.tts import speak


BASE_DIR = Path(__file__).resolve().parent
APP_PATH = BASE_DIR / "nova_app.py"
DATA_DIR = BASE_DIR / "data"
RECORDINGS_DIR = BASE_DIR / "recordings"
WAKE_AUDIO_PATH = RECORDINGS_DIR / "wake_word.wav"
WAKE_EVENT_PATH = DATA_DIR / "wake_event.json"
LISTENING_LOCK_PATH = DATA_DIR / "listening_lock.json"

MODEL_SIZE = WHISPER_MODEL or "small"
COOLDOWN_SECONDS = 2.2
WINDOW_TITLE = "NOVA Asistan"
INITIAL_PROMPT = "Türkçe uyandırma kelimesi: Hey Nova. Sadece Hey Nova ifadesini dinle."

WAKE_PHRASES = (
    "hey nova",
    "merhaba nova",
    "nova asistan",
    "hey nava",
    "merhaba nava",
    "hey novava",
    "hey novaova",
    "hey novaovava",
    "hey novova",
    "no va",
)

FUZZY_TARGETS = ("hey nova", "merhaba nova", "nova asistan")
FUZZY_THRESHOLD = 0.70


def main() -> None:
    print("NOVA aktif dinleme başlatıldı.", flush=True)
    print("Bu pencere sadece 'Hey Nova' uyandırma ifadesini bekler.", flush=True)
    print("'Hey Nova' algılanınca arayüz komutunuzu ayrıca dinler.", flush=True)
    print("Çıkmak için bu pencereyi kapatın veya Ctrl+C kullanın.\n", flush=True)

    model = load_wake_model()
    last_wake_time = 0.0

    while True:
        try:
            check_due_reminders()
            if is_microphone_locked():
                time.sleep(0.25)
                continue

            print("Hey Nova bekleniyor...", flush=True)
            audio_result = record_wake_audio()
            if not audio_result.get("speech_started"):
                continue

            raw_text = transcribe_audio(model, Path(audio_result["path"]))
            normalized_text = normalize_wake_text(raw_text)
            wake_accepted = is_wake_word(normalized_text)

            print(f"Algılanan ham metin: {raw_text or '(boş)'}", flush=True)
            print(f"Normalize edilen metin: {normalized_text or '(boş)'}", flush=True)
            print(f"Wake kabul edildi mi?: {'Evet' if wake_accepted else 'Hayır'}", flush=True)

            if not wake_accepted:
                continue

            now = time.time()
            if now - last_wake_time < COOLDOWN_SECONDS:
                print("Uyandırma algılandı ama kısa bekleme aktif.", flush=True)
                continue

            last_wake_time = now
            write_wake_event()
            wake_nova()
        except KeyboardInterrupt:
            print("\nNOVA aktif dinleme kapatıldı.", flush=True)
            break
        except Exception as exc:
            print(f"Hata: {exc}", flush=True)
            time.sleep(1)


def load_wake_model():
    from faster_whisper import WhisperModel

    print(f"Wake word modeli yükleniyor: {MODEL_SIZE}", flush=True)
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def record_wake_audio() -> dict:
    # Kısa, adaptif kayıt: konuşma başlamazsa Whisper çağrısı yapılmaz.
    return record_until_silence(
        WAKE_AUDIO_PATH,
        max_seconds=float(WAKE_RECORD_SECONDS or 4.5),
        wait_for_speech_seconds=float(WAKE_WAIT_SECONDS or 3.0),
        min_record_seconds=0.45,
        silence_after_seconds=0.55,
        sample_rate=DEFAULT_SAMPLE_RATE,
        speech_rms_threshold=0.004,
        speech_peak_threshold=0.016,
        save_silent=False,
    )


def transcribe_audio(model, audio_path: Path) -> str:
    segments, _info = model.transcribe(
        str(audio_path),
        language="tr",
        task="transcribe",
        initial_prompt=INITIAL_PROMPT,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 150},
        beam_size=3,
        condition_on_previous_text=False,
        temperature=0,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return " ".join(text.split())


def normalize_wake_text(text: str) -> str:
    return normalize_turkish_for_wake(text)


def is_wake_word(text: str) -> bool:
    normalized = normalize_wake_text(text)
    if not normalized:
        return False

    padded = f" {normalized} "
    if any(f" {phrase} " in padded for phrase in WAKE_PHRASES):
        return True

    words = normalized.split()
    candidates = {normalized}
    for index in range(len(words) - 1):
        candidates.add(f"{words[index]} {words[index + 1]}")
    for index in range(len(words) - 2):
        candidates.add(f"{words[index]} {words[index + 1]} {words[index + 2]}")

    return any(
        _is_plausible_wake_candidate(candidate) and _similarity(candidate, target) >= FUZZY_THRESHOLD
        for candidate in candidates
        for target in FUZZY_TARGETS
    )


def write_wake_event() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    event = {
        "id": uuid.uuid4().hex,
        "created_at": time.time(),
        "command": "",
        "mode": "listen_after_wake",
    }
    WAKE_EVENT_PATH.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")


def wake_nova() -> None:
    hwnd = find_nova_window()
    if hwnd:
        print("NOVA uyandırıldı. Arayüz zaten açık.", flush=True)
        bring_window_to_front(hwnd)
        return

    pythonw_path = get_pythonw_path()
    subprocess.Popen(
        [str(pythonw_path), str(APP_PATH), "--wake"],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    print("NOVA uyandırıldı.", flush=True)


def check_due_reminders() -> None:
    for reminder in get_due_reminders(mark_announced=True):
        title = reminder.get("title", "Bir hatırlatıcınız var.")
        message = f"Hatırlatma: {title}"
        print(message, flush=True)
        speak(message)


def is_microphone_locked() -> bool:
    try:
        if not LISTENING_LOCK_PATH.exists():
            return False
        data = json.loads(LISTENING_LOCK_PATH.read_text(encoding="utf-8"))
        if not data.get("locked"):
            return False
        return time.time() - float(data.get("created_at", 0)) < 20
    except Exception:
        return False


def get_pythonw_path() -> Path:
    executable = Path(sys.executable)
    pythonw_path = executable.with_name("pythonw.exe")
    if pythonw_path.exists():
        return pythonw_path
    return executable


def find_nova_window() -> int | None:
    user32 = ctypes.windll.user32
    found: int | None = None

    def enum_handler(hwnd, _lparam):
        nonlocal found
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if WINDOW_TITLE.casefold() in buffer.value.casefold():
            found = int(hwnd)
            return False
        return True

    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(enum_windows_proc(enum_handler), 0)
    return found


def bring_window_to_front(hwnd: int) -> None:
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception as exc:
        print(f"NOVA penceresi öne getirilemedi: {exc}", flush=True)


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _is_plausible_wake_candidate(candidate: str) -> bool:
    if not candidate:
        return False
    if any(marker in candidate for marker in ("nov", "nav", "no va")):
        return True
    return _similarity(candidate, "hey nova") >= FUZZY_THRESHOLD


if __name__ == "__main__":
    main()
