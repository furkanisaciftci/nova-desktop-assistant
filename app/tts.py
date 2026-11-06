from __future__ import annotations

import asyncio
import ctypes
import hashlib
import re
from pathlib import Path
from time import perf_counter
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = BASE_DIR / "recordings"
CACHE_DIR = RECORDINGS_DIR / "tts_cache"
EDGE_TTS_OUTPUT_PATH = RECORDINGS_DIR / "tts_output.mp3"
WELCOME_SOUND_PATH = BASE_DIR / "assets" / "audio" / "welcome.wav"

EDGE_VOICES = ("tr-TR-EmelNeural", "tr-TR-AhmetNeural")
VOICE_HINTS = ("Turkish", "tr-TR", "Tolga", "Microsoft Tolga", "Microsoft Seda")
DEFAULT_RATE = 138
DEFAULT_VOLUME = 1.0
WELCOME_TEXT = "Buyurun, sizi dinliyorum."


def speak(text: str) -> dict[str, Any]:
    """Speak text with edge-tts first, then pyttsx3 fallback. Never crash NOVA."""
    start = perf_counter()
    message = sanitize_spoken_text(str(text or "").strip())
    if not message:
        return {"spoken": False, "engine": None, "error": "Boş metin seslendirilemez.", "voice": None}

    edge_result = _speak_with_edge_tts(message)
    if edge_result.get("spoken"):
        print(f"[PERF] TTS başlatma/çalma: {perf_counter() - start:.1f} sn", flush=True)
        return edge_result

    pyttsx3_result = _speak_with_pyttsx3(message)
    if pyttsx3_result.get("spoken"):
        print(f"[PERF] TTS başlatma/çalma: {perf_counter() - start:.1f} sn", flush=True)
        return pyttsx3_result

    return {
        "spoken": False,
        "engine": None,
        "error": edge_result.get("error") or pyttsx3_result.get("error"),
        "voice": None,
    }


def stop_speech() -> dict[str, Any]:
    """Best-effort stop for currently playing MCI audio. pyttsx3 may not be interruptible."""
    try:
        _mci_command("stop nova_tts", raise_on_error=False)
        _mci_command("close nova_tts", raise_on_error=False)
        return {"stopped": True, "error": None}
    except Exception as exc:
        print(f"TTS durdurulamadı: {exc}", flush=True)
        return {"stopped": False, "error": str(exc)}


def sanitize_spoken_text(text: str) -> str:
    """Keep TTS short and prevent reading URLs/source lists aloud."""
    value = str(text or "").strip()
    if not value:
        return ""
    if re.search(r"https?://|www\.|doi\.org|arxiv\.org", value, re.IGNORECASE):
        if "akademik" in value.casefold() or "kaynak" in value.casefold():
            return "Kaynaklar ekranda gösteriliyor."
        return "Kaynak bağlantısı ekranda gösteriliyor."
    value = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", r"\1", value)
    value = re.sub(r"(?:https?://|www\.)\S+", "", value)
    value = re.sub(r"\b(?:doi|arxiv)\s*[:/]\S+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(?is)Kaynak bağlantıları:.*", "Kaynaklar ekranda gösteriliyor.", value)
    value = " ".join(value.split())
    if len(value) > 180:
        value = value[:177].rstrip() + "..."
    return value


def play_welcome_sound() -> dict[str, Any]:
    """Play a recorded Turkish welcome if available, otherwise use speak fallback."""
    if WELCOME_SOUND_PATH.exists():
        try:
            import sounddevice as sd
            import soundfile as sf

            audio_data, sample_rate = sf.read(str(WELCOME_SOUND_PATH), dtype="float32")
            sd.play(audio_data, sample_rate)
            sd.wait()
            return {"played_file": True, "spoken": False, "engine": "wav", "error": None, "path": str(WELCOME_SOUND_PATH)}
        except Exception as exc:
            print(f"welcome.wav çalınamadı: {exc}", flush=True)

    fallback_result = speak(WELCOME_TEXT)
    return {
        "played_file": False,
        "spoken": fallback_result.get("spoken", False),
        "engine": fallback_result.get("engine"),
        "error": fallback_result.get("error"),
        "path": str(WELCOME_SOUND_PATH),
    }


def list_voices() -> list[dict[str, str]]:
    try:
        import pyttsx3

        engine = pyttsx3.init()
        voices = engine.getProperty("voices") or []
        return [
            {
                "id": str(getattr(voice, "id", "")),
                "name": str(getattr(voice, "name", "")),
            }
            for voice in voices
        ]
    except Exception as exc:
        print(f"TTS voice listesi alınamadı: {exc}", flush=True)
        return []


def _speak_with_edge_tts(message: str) -> dict[str, Any]:
    try:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = _tts_cache_path(message)
        if cache_path.exists():
            _play_mp3(cache_path)
            return {"spoken": True, "engine": "edge-tts-cache", "error": None, "voice": None}

        last_error = None
        for voice in EDGE_VOICES:
            try:
                asyncio.run(_create_edge_tts_file(message, voice, cache_path))
                _play_mp3(cache_path)
                return {"spoken": True, "engine": "edge-tts", "error": None, "voice": voice}
            except Exception as exc:
                last_error = exc
                print(f"edge-tts hatası ({voice}): {exc}", flush=True)
        return {"spoken": False, "engine": "edge-tts", "error": str(last_error), "voice": None}
    except Exception as exc:
        print(f"edge-tts genel hatası: {exc}", flush=True)
        return {"spoken": False, "engine": "edge-tts", "error": str(exc), "voice": None}


def _tts_cache_path(message: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.mp3"


async def _create_edge_tts_file(message: str, voice: str, output_path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(message, voice)
    await communicate.save(str(output_path))


def _play_mp3(path: Path) -> None:
    _mci_command(f'open "{path}" type mpegvideo alias nova_tts')
    try:
        _mci_command("play nova_tts wait")
    finally:
        _mci_command("close nova_tts", raise_on_error=False)


def _mci_command(command: str, raise_on_error: bool = True) -> None:
    winmm = ctypes.windll.winmm
    error_code = winmm.mciSendStringW(command, None, 0, None)
    if error_code and raise_on_error:
        buffer = ctypes.create_unicode_buffer(255)
        winmm.mciGetErrorStringW(error_code, buffer, 255)
        raise RuntimeError(buffer.value or f"MCI hata kodu: {error_code}")


def _speak_with_pyttsx3(message: str) -> dict[str, Any]:
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", DEFAULT_RATE)
        engine.setProperty("volume", DEFAULT_VOLUME)
        selected_voice = _select_turkish_voice(engine)
        engine.say(message)
        engine.runAndWait()
        return {"spoken": True, "engine": "pyttsx3", "error": None, "voice": selected_voice}
    except Exception as exc:
        print(f"pyttsx3 hatası: {exc}", flush=True)
        return {"spoken": False, "engine": "pyttsx3", "error": str(exc), "voice": None}


def _select_turkish_voice(engine: Any) -> str | None:
    voices = engine.getProperty("voices") or []
    for voice in voices:
        voice_id = str(getattr(voice, "id", ""))
        voice_name = str(getattr(voice, "name", ""))
        searchable = f"{voice_id} {voice_name}"
        if any(hint.casefold() in searchable.casefold() for hint in VOICE_HINTS):
            engine.setProperty("voice", voice_id)
            return voice_name or voice_id
    return None
