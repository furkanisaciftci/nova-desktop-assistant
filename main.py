from __future__ import annotations

import json
import sys

from app.assistant_core import run_assistant_command


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def print_json(title: str, data: object) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_warning(warning: object) -> None:
    if warning:
        print("\n=== Uyarı ===")
        print(warning)


def print_results(results: list[dict[str, object]]) -> None:
    print("\n=== İşlem Sonuçları ===")
    for result in results:
        step = result.get("step")
        prefix = f"{step}. " if step else "- "
        status = "Başarılı" if result.get("success") else "Başarısız"
        print(f"{prefix}{result.get('action')}: {status} - {result.get('message')}")


def main() -> None:
    configure_console()
    print("NOVA - LLM Destekli Otonom Masaüstü Asistanı MVP")
    print("Çıkış için: q, quit, exit\n")

    while True:
        try:
            user_command = input("Komutunuz: ").strip()
        except EOFError:
            print("\nGörüşmek üzere.")
            break

        if user_command.lower() in {"q", "quit", "exit"}:
            print("Görüşmek üzere.")
            break
        if not user_command:
            continue

        response = run_assistant_command(user_command)
        print_warning(response.get("warning"))
        print_json("Üretilen Plan", response["plan"])
        print_results(response["results"])


if __name__ == "__main__":
    main()
