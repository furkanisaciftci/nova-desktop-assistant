from __future__ import annotations

from typing import Any

import requests

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS


def generate_with_ollama(prompt: str, *, json_mode: bool = False, timeout: float | None = None) -> str:
    """Call the local Ollama generate API and return plain text."""
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2 if json_mode else 0.35,
            "num_predict": 900 if json_mode else 1800,
        },
    }
    if json_mode:
        payload["format"] = "json"

    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json=payload,
        timeout=timeout or OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return str(data.get("response", "")).strip()
