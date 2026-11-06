from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

from app.audio_utils import DEFAULT_SAMPLE_RATE, record_until_silence
from app.config import VOICE_RECORD_SECONDS, WHISPER_MODEL


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RECORDINGS_DIR = BASE_DIR / "recordings"
LAST_RECORDING_PATH = RECORDINGS_DIR / "last_command.wav"
LISTENING_LOCK_PATH = DATA_DIR / "listening_lock.json"

DEFAULT_DURATION_SECONDS = max(int(VOICE_RECORD_SECONDS or 7), 7)
DEFAULT_MODEL_SIZE = WHISPER_MODEL or "small"
VOICE_COMMAND_INITIAL_PROMPT = (
    "Türkçe masaüstü asistan komutları. Kısa ve doğal konuşma: "
    "saat kaç, Google aç, klasör oluştur, not oluştur, takvim ekle, "
    "hatırlatıcı kur, yapılacaklara ekle, ekran görüntüsü al, "
    "yapay zeka hakkında araştırma yap."
)

_whisper_model = None


def transcribe_microphone_command(duration_seconds: int = DEFAULT_DURATION_SECONDS) -> dict[str, Any]:
    """Mikrofondan komut alır ve metne çevirir. Bu fonksiyon doğrudan işlem çalıştırmaz."""
    total_start = perf_counter()
    with microphone_lock():
        audio_result = record_microphone_audio(duration_seconds)
        record_elapsed = perf_counter() - total_start
        if not audio_result.get("speech_started"):
            raise RuntimeError("Ses algılanamadı, tekrar deneyebilirsiniz.")
        transcribe_start = perf_counter()
        text = transcribe_audio_file(Path(audio_result["path"]))
    transcribe_elapsed = perf_counter() - transcribe_start
    if not text:
        raise RuntimeError("Ses algılanamadı, tekrar deneyebilirsiniz.")

    total_elapsed = perf_counter() - total_start
    print(
        f"[PERF] Ses kaydı: {record_elapsed:.1f} sn | "
        f"Whisper çözümleme: {transcribe_elapsed:.1f} sn | "
        f"Ses toplam: {total_elapsed:.1f} sn | "
        f"Metin: {text}",
        flush=True,
    )
    return {
        "text": text,
        "audio_path": str(audio_result["path"]),
        "duration_seconds": audio_result.get("duration_seconds", duration_seconds),
        "peak_level": audio_result.get("peak_level", 0),
        "rms_level": audio_result.get("rms_level", 0),
    }


def record_microphone_audio(duration_seconds: int = DEFAULT_DURATION_SECONDS) -> dict[str, Any]:
    try:
        import sounddevice  # noqa: F401
        import soundfile  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Ses kaydı için sounddevice ve soundfile kurulmalı.") from exc

    try:
        max_seconds = max(float(duration_seconds or DEFAULT_DURATION_SECONDS), 7.0)
        return record_until_silence(
            LAST_RECORDING_PATH,
            max_seconds=max_seconds,
            wait_for_speech_seconds=4.0,
            min_record_seconds=0.75,
            silence_after_seconds=0.95,
            sample_rate=DEFAULT_SAMPLE_RATE,
            save_silent=True,
        )
    except Exception as exc:
        raise RuntimeError(f"Mikrofon cihazı kullanılamadı: {exc}") from exc


def transcribe_audio_file(audio_path: Path) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Ses tanıma için faster-whisper kurulmalı.") from exc

    model = _get_whisper_model(WhisperModel)
    segments, _info = model.transcribe(
        str(audio_path),
        language="tr",
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 250},
        condition_on_previous_text=False,
        temperature=0,
        initial_prompt=VOICE_COMMAND_INITIAL_PROMPT,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return " ".join(text.split())


def _get_whisper_model(model_class: type) -> Any:
    global _whisper_model
    if _whisper_model is None:
        start = perf_counter()
        print(f"[PERF] Whisper modeli yükleniyor: {DEFAULT_MODEL_SIZE}", flush=True)
        _whisper_model = model_class(DEFAULT_MODEL_SIZE, device="cpu", compute_type="int8")
        print(f"[PERF] Whisper model yükleme: {perf_counter() - start:.1f} sn", flush=True)
    return _whisper_model


@contextmanager
def microphone_lock() -> Iterator[None]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LISTENING_LOCK_PATH.write_text(
            json.dumps({"locked": True, "created_at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    try:
        yield
    finally:
        try:
            LISTENING_LOCK_PATH.write_text(
                json.dumps({"locked": False, "created_at": time.time()}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass


def warm_up_voice_model() -> None:
    try:
        from faster_whisper import WhisperModel

        _get_whisper_model(WhisperModel)
    except Exception as exc:
        print(f"[PERF] Whisper ön yükleme atlandı: {exc}", flush=True)
