from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("NOVA_OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "8").strip() or "8")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/") or "http://localhost:11434"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b"
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90").strip() or "90")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().casefold() or "gemini"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip() or "small"
VOICE_RECORD_SECONDS = int(os.getenv("VOICE_RECORD_SECONDS", "7").strip() or "7")
NOVA_MIC_DEVICE = os.getenv("NOVA_MIC_DEVICE", "").strip()
WAKE_RECORD_SECONDS = float(os.getenv("WAKE_RECORD_SECONDS", "4.5").strip() or "4.5")
WAKE_WAIT_SECONDS = float(os.getenv("WAKE_WAIT_SECONDS", "3.0").strip() or "3.0")

USER_HOME = Path.home()
DESKTOP_DIR = USER_HOME / "Desktop"
DOCUMENTS_DIR = USER_HOME / "Documents"
DOWNLOADS_DIR = USER_HOME / "Downloads"
PICTURES_DIR = USER_HOME / "Pictures"
ALLOWED_ROOTS = (DESKTOP_DIR, DOCUMENTS_DIR)

SPECIAL_FOLDERS = {
    "desktop": DESKTOP_DIR,
    "masaüstü": DESKTOP_DIR,
    "masaustu": DESKTOP_DIR,
    "documents": DOCUMENTS_DIR,
    "belgeler": DOCUMENTS_DIR,
    "downloads": DOWNLOADS_DIR,
    "indirilenler": DOWNLOADS_DIR,
    "pictures": PICTURES_DIR,
    "resimler": PICTURES_DIR,
}

DEFAULT_NEWS_TOPIC = "yapay zeka"
DEFAULT_NEWS_FILE_NAME = "son_yapay_zeka_haberi.txt"

ALLOWED_APPS = {
    "notepad": "notepad.exe",
    "not defteri": "notepad.exe",
    "hesap makinesi": "calc.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "wordpad": "write.exe",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "chrome": "chrome",
    "google chrome": "chrome",
    "word": "winword",
    "microsoft word": "winword",
    "excel": "excel",
    "microsoft excel": "excel",
    "powerpoint": "powerpnt",
    "power point": "powerpnt",
    "microsoft powerpoint": "powerpnt",
    "dosya gezgini": "explorer.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
}
