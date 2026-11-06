from __future__ import annotations

from app.command_interpreter import interpret_user_intent


tests = [
    "Yapay zeka haberlerini özetle",
    "Yapay zeka hakkında araştırma yap ve masaüstüne kaydet",
    "Python pywebview nedir araştır",
    "Selçuk Üniversitesi akademik takvimini resmi siteden araştır",
    "Son teknoloji haberlerini özetle",
    "Siber güvenlik hakkında kaynaklı rapor hazırla",
    "Bu siteyi özetle: https://example.com",
    "javascript:alert(1) sitesini aç",
    "file:///C:/Windows/system32 sitesini aç",
]


def main() -> None:
    for text in tests:
        intent = interpret_user_intent(text)
        print(f"{text} -> {intent['category']} / {intent.get('action')} / {intent.get('args')}")


if __name__ == "__main__":
    main()
