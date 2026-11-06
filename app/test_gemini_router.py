from __future__ import annotations

from app.command_interpreter import interpret_user_intent
from app.config import LLM_PROVIDER


TEST_COMMANDS = [
    "Yapay zeka ile ilgili akademik makaleler araştır ve kaynaklarıyla özetle",
    "Google’a girip bana yapay zeka ile ilgili makaleler bulabilir misin",
    "Pywebview hakkında bilimsel kaynakları bul",
    "Yapay zeka ile ilgili akademik kaynakları masaüstüne rapor olarak kaydet",
    "internetten biraz bakıp yapay zeka konusunu toparlar mısın",
    "bu konuyla ilgili kaynaklı kısa bir rapor çıkar: siber güvenlik",
    "pywebview ne işe yarıyor araştırıp özet geç",
    "selçuk üniversitesinin akademik takvimi resmi kaynakta var mı bak",
    "yarın sunumum var bunu takvime eklemek istiyorum",
    "hatırlatmalarımı bir açar mısın",
    "şu anda ekrandaki görüntüyü kaydet",
    "görevlerimi gösterir misin",
    "masaüstüne proje için düzenli bir klasör yapısı kur",
    "merhaba nasılsın",
    "sence bugün ne yesem",
    "bilgisayardaki dosyaları sil",
    "gogle gir",
    "sat kaç",
]


def main() -> None:
    print(f"Provider ayarı: {LLM_PROVIDER}")
    for text in TEST_COMMANDS:
        intent = interpret_user_intent(text)
        print("-" * 72)
        print(f"input: {text}")
        print(f"provider: {intent.get('provider', 'fallback/local')}")
        print(f"category: {intent.get('category')}")
        print(f"action: {intent.get('action')}")
        print(f"args: {intent.get('args')}")
        print(f"message: {intent.get('message')}")


if __name__ == "__main__":
    main()
