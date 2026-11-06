from __future__ import annotations

from app.audio_utils import list_input_devices, record_until_silence
from app.voice_input import transcribe_audio_file
from pathlib import Path


def main() -> None:
    print("\nNOVA Mikrofon Testi")
    print("------------------")
    print("Giriş cihazları:")
    for device in list_input_devices():
        print(f"[{device['index']}] {device['name']}  | kanal: {device['max_input_channels']}")

    print("\n5 saniye içinde normal sesle şunu söyleyin: Hey Nova saat kaç")
    result = record_until_silence(
        Path("recordings/mic_test.wav"),
        max_seconds=7,
        wait_for_speech_seconds=5,
        silence_after_seconds=0.9,
        min_record_seconds=0.7,
        save_silent=True,
    )
    print(f"\nKonuşma başladı mı: {result.get('speech_started')}")
    print(f"Ses seviyesi peak: {result.get('peak_level'):.5f}")
    print(f"Ses seviyesi rms : {result.get('rms_level'):.5f}")
    print(f"Kayıt dosyası    : {result.get('path')}")

    if not result.get("speech_started"):
        print("\nSonuç: Mikrofon sesi çok düşük veya yanlış mikrofon seçili.")
        return

    try:
        text = transcribe_audio_file(Path(result["path"]))
        print(f"Algılanan metin  : {text}")
    except Exception as exc:
        print(f"Whisper test hatası: {exc}")


if __name__ == "__main__":
    main()
