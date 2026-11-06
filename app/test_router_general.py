from __future__ import annotations

from app.command_interpreter import interpret_user_intent


TEST_COMMANDS = [
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
    for text in TEST_COMMANDS:
        intent = interpret_user_intent(text)
        print("-" * 72)
        print(f"Girdi: {text}")
        print(f"Kategori: {intent.get('category')}")
        print(f"Action: {intent.get('action')}")
        print(f"Args: {intent.get('args')}")
        print(f"Mesaj: {intent.get('message')}")


if __name__ == "__main__":
    main()
