from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1


def get_input_device() -> int | str | None:
    """Selects the input device configured by NOVA_MIC_DEVICE.

    NOVA_MIC_DEVICE may be a device index or a part of the microphone name.
    If not configured, sounddevice uses the Windows default input device.
    """
    device_value = os.getenv("NOVA_MIC_DEVICE", "").strip()
    if not device_value:
        return None

    if device_value.isdigit():
        return int(device_value)

    try:
        import sounddevice as sd

        devices = sd.query_devices()
        needle = device_value.casefold()
        for index, device in enumerate(devices):
            name = str(device.get("name", ""))
            max_inputs = int(device.get("max_input_channels", 0) or 0)
            if max_inputs > 0 and needle in name.casefold():
                return index
    except Exception:
        return None

    return None


def list_input_devices() -> list[dict[str, Any]]:
    import sounddevice as sd

    devices = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_input_channels", 0) or 0) <= 0:
            continue
        devices.append(
            {
                "index": index,
                "name": str(device.get("name", "")),
                "default_samplerate": float(device.get("default_samplerate", 0) or 0),
                "max_input_channels": int(device.get("max_input_channels", 0) or 0),
            }
        )
    return devices


def normalize_audio(samples: np.ndarray, target_peak: float = 0.82) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 0:
        return audio
    if peak < 0.35:
        gain = min(target_peak / peak, 28.0)
        audio = np.clip(audio * gain, -1.0, 1.0)
    return audio.astype(np.float32)


def trim_silence(samples: np.ndarray, threshold: float = 0.006, padding_ms: int = 180, sample_rate: int = DEFAULT_SAMPLE_RATE) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    if audio.size == 0:
        return audio

    mono = np.abs(audio.reshape(-1))
    above = np.where(mono > threshold)[0]
    if above.size == 0:
        return audio

    padding = int(sample_rate * padding_ms / 1000)
    start = max(int(above[0]) - padding, 0)
    end = min(int(above[-1]) + padding, audio.shape[0] - 1)
    return audio[start : end + 1]


def record_until_silence(
    output_path: Path,
    *,
    max_seconds: float = 8.0,
    wait_for_speech_seconds: float = 4.0,
    min_record_seconds: float = 0.65,
    silence_after_seconds: float = 0.85,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    speech_rms_threshold: float | None = None,
    speech_peak_threshold: float | None = None,
    save_silent: bool = True,
) -> dict[str, Any]:
    """Records until speech ends instead of waiting for a fixed duration.

    This is intentionally simple and offline. It avoids an extra dependency and
    works better than fixed five-second chunks for short Turkish voice commands.
    """
    import sounddevice as sd
    import soundfile as sf

    output_path.parent.mkdir(parents=True, exist_ok=True)

    block_size = 1024
    device = get_input_device()
    frames: list[np.ndarray] = []
    noise_rms_values: list[float] = []
    speech_started = False
    speech_start_time: float | None = None
    last_voice_time: float | None = None
    start_time = time.monotonic()

    # Conservative defaults: low enough for laptop microphones, high enough to
    # ignore most fan/room noise. They are adapted by the first blocks.
    base_rms_threshold = speech_rms_threshold or float(os.getenv("NOVA_SPEECH_RMS", "0.0045") or "0.0045")
    base_peak_threshold = speech_peak_threshold or float(os.getenv("NOVA_SPEECH_PEAK", "0.018") or "0.018")

    with sd.InputStream(
        samplerate=sample_rate,
        channels=DEFAULT_CHANNELS,
        dtype="float32",
        blocksize=block_size,
        device=device,
    ) as stream:
        while True:
            block, overflowed = stream.read(block_size)
            if overflowed:
                pass
            block = np.asarray(block, dtype=np.float32)
            frames.append(block.copy())

            now = time.monotonic()
            elapsed = now - start_time
            rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0
            peak = float(np.max(np.abs(block))) if block.size else 0.0

            if not speech_started and elapsed < 0.45:
                noise_rms_values.append(rms)

            ambient = float(np.median(noise_rms_values)) if noise_rms_values else 0.0
            adaptive_rms = max(base_rms_threshold, ambient * 3.0)
            adaptive_peak = max(base_peak_threshold, ambient * 8.0)
            has_voice = rms >= adaptive_rms or peak >= adaptive_peak

            if has_voice:
                if not speech_started:
                    speech_started = True
                    speech_start_time = now
                last_voice_time = now

            if speech_started:
                speech_elapsed = now - (speech_start_time or now)
                silence_elapsed = now - (last_voice_time or now)
                if speech_elapsed >= min_record_seconds and silence_elapsed >= silence_after_seconds:
                    break
                if elapsed >= max_seconds:
                    break
            else:
                if elapsed >= wait_for_speech_seconds:
                    break
                if elapsed >= max_seconds:
                    break

    if frames:
        audio = np.concatenate(frames, axis=0)
    else:
        audio = np.zeros((0, 1), dtype=np.float32)

    peak_level = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms_level = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0

    if speech_started:
        audio = trim_silence(audio, threshold=max(base_peak_threshold * 0.35, 0.005), sample_rate=sample_rate)
        audio = normalize_audio(audio)
        sf.write(output_path, audio, sample_rate)
    elif save_silent:
        sf.write(output_path, audio, sample_rate)

    return {
        "path": output_path,
        "speech_started": speech_started,
        "duration_seconds": round(float(audio.shape[0] / sample_rate), 2) if audio.size else 0.0,
        "peak_level": peak_level,
        "rms_level": rms_level,
        "device": device,
    }


def normalize_turkish_for_wake(text: str) -> str:
    value = str(text or "").casefold()
    replacements = {
        "ı": "i",
        "i̇": "i",
        "növa": "nova",
        "nóva": "nova",
        "nava": "nova",
        "no va": "nova",
        "nov a": "nova",
        "hey no": "hey nova",
        "hey n": "hey nova",
        "he nova": "hey nova",
        "hay nova": "hey nova",
        "ey nova": "hey nova",
        "hey no va": "hey nova",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r"\bhey\s+nov(?:a|o|ov|ova|ava|avava|ovava|oa|aa)+\b", "hey nova", value)
    value = re.sub(r"\bnov(?:a|o|ov|ova|ava|avava|ovava|oa|aa)+\b", "nova", value)
    value = re.sub(r"[^\w\sçğıöşü]", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value
