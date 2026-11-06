from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    description: str
    parameters: tuple[str, ...]
    safe: bool
    examples: tuple[str, ...]
    executor: str


ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "CREATE_FOLDER": ActionDefinition(
        name="CREATE_FOLDER",
        description="Masaüstü altında güvenli klasör oluşturur.",
        parameters=("path",),
        safe=True,
        examples=("Masaüstünde Projeler klasörü oluştur", "Sunum klasörü aç"),
        executor="create_folder",
    ),
    "WRITE_TEXT_FILE": ActionDefinition(
        name="WRITE_TEXT_FILE",
        description="Masaüstü altında .txt metin dosyası yazar.",
        parameters=("path", "content"),
        safe=True,
        examples=("Masaüstüne not.txt dosyası yaz",),
        executor="write_text_file",
    ),
    "OPEN_FOLDER": ActionDefinition(
        name="OPEN_FOLDER",
        description="Masaüstü altındaki izinli bir klasörü açar.",
        parameters=("path",),
        safe=True,
        examples=("Projeler klasörünü aç",),
        executor="open_folder",
    ),
    "OPEN_SPECIAL_FOLDER": ActionDefinition(
        name="OPEN_SPECIAL_FOLDER",
        description="Desktop, Documents, Downloads veya Pictures klasörünü açar.",
        parameters=("folder",),
        safe=True,
        examples=("Belgeler klasörünü aç", "İndirilenler'i aç", "Masaüstünü aç"),
        executor="open_special_folder",
    ),
    "OPEN_APP": ActionDefinition(
        name="OPEN_APP",
        description="Eski uyumluluk için whitelist uygulama açar.",
        parameters=("app_name",),
        safe=True,
        examples=("Not defterini aç",),
        executor="open_app",
    ),
    "OPEN_COMMON_APP": ActionDefinition(
        name="OPEN_COMMON_APP",
        description="Not Defteri, Hesap Makinesi, Paint, WordPad, VS Code veya Chrome gibi whitelist uygulamaları açar.",
        parameters=("app_name",),
        safe=True,
        examples=("Hesap makinesini aç", "VS Code başlat", "Chrome'u aç"),
        executor="open_common_app",
    ),
    "OPEN_WEBSITE": ActionDefinition(
        name="OPEN_WEBSITE",
        description="Güvenli http/https web sitesini varsayılan tarayıcıda açar.",
        parameters=("site", "url"),
        safe=True,
        examples=("Google'a gir", "YouTube sayfasını aç", "cecihome.com.tr sitesini başlat"),
        executor="open_website",
    ),
    "WEB_SEARCH": ActionDefinition(
        name="WEB_SEARCH",
        description="Verilen konuyu Google araması olarak açar.",
        parameters=("query",),
        safe=True,
        examples=("Yapay zeka haberlerini ara", "Python pywebview nedir araştır"),
        executor="web_search",
    ),
    "WEB_RESEARCH_SUMMARY": ActionDefinition(
        name="WEB_RESEARCH_SUMMARY",
        description="Verilen konu hakkında web kaynaklarından kısa özet hazırlar.",
        parameters=("topic",),
        safe=True,
        examples=("Python pywebview nedir araştır", "Yapay zeka haberlerini özetle"),
        executor="web_research_summary",
    ),
    "WEB_RESEARCH_SAVE": ActionDefinition(
        name="WEB_RESEARCH_SAVE",
        description="Verilen konu hakkında araştırma raporunu Masaüstündeki NOVA_Research klasörüne kaydeder.",
        parameters=("topic", "file_name"),
        safe=True,
        examples=("Siber güvenlik hakkında kaynaklı rapor hazırla", "Araştırma yap ve masaüstüne kaydet"),
        executor="web_research_save",
    ),
    "SUMMARIZE_URL": ActionDefinition(
        name="SUMMARIZE_URL",
        description="Güvenli http/https URL içeriğini kısa özetler.",
        parameters=("url",),
        safe=True,
        examples=("Bu siteyi özetle: https://example.com",),
        executor="summarize_url",
    ),
    "LATEST_NEWS_BY_TOPIC": ActionDefinition(
        name="LATEST_NEWS_BY_TOPIC",
        description="Verilen konu hakkında son haberleri RSS/web kaynağından özetler.",
        parameters=("topic",),
        safe=True,
        examples=("Son teknoloji haberlerini özetle", "Yapay zeka haberlerini özetle"),
        executor="latest_news_by_topic",
    ),
    "OFFICIAL_INFO_SEARCH": ActionDefinition(
        name="OFFICIAL_INFO_SEARCH",
        description="Resmi kaynak öncelikli bilgi araması yapar ve kaynak bağlantısı döndürür.",
        parameters=("topic",),
        safe=True,
        examples=("Selçuk Üniversitesi akademik takvimini resmi siteden araştır",),
        executor="official_info_search",
    ),
    "ACADEMIC_SEARCH": ActionDefinition(
        name="ACADEMIC_SEARCH",
        description="Akademik makale, bilimsel kaynak, literatür ve paper istekleri için kaynaklı akademik arama yapar.",
        parameters=("topic", "max_results", "save_to_file", "summary_level"),
        safe=True,
        examples=(
            "Yapay zeka ile ilgili akademik makaleler bul",
            "Bilimsel kaynakları araştır",
            "Literatür taraması yap ve kaynaklarıyla özetle",
        ),
        executor="academic_search",
    ),
    "GENERAL_AI_ANSWER": ActionDefinition(
        name="GENERAL_AI_ANSWER",
        description="Genel bilgi, açıklama, kavram anlatımı ve öneri isteklerine uzun Türkçe cevap üretir; sistem işlemi yapmaz.",
        parameters=("question", "mode"),
        safe=True,
        examples=(
            "Büyük dil modelleri nedir?",
            "Büyük dil modelleri ilk ne zaman ve nerede kullanılmış?",
            "Yapay zeka ajanları nasıl çalışır?",
            "Transformer mimarisi neden önemlidir?",
            "PyWebView ne işe yarar?",
        ),
        executor="generate_ai_answer",
    ),
    "RESEARCH_AND_EXPLAIN": ActionDefinition(
        name="RESEARCH_AND_EXPLAIN",
        description="Güncel veya kaynaklı araştırma isteklerinde web kaynağına dayalı açıklama üretir; sistem işlemi yapmaz.",
        parameters=("topic",),
        safe=True,
        examples=("Konuyu güncel kaynaklarla araştır", "Yapay zeka ajanları hakkında kaynaklı araştırma yap"),
        executor="generate_ai_answer",
    ),
    "PRACTICAL_GUIDE": ActionDefinition(
        name="PRACTICAL_GUIDE",
        description="Nasıl yapılır, malzeme seçimi ve proje sunumu gibi istekler için adım adım pratik rehber üretir.",
        parameters=("question",),
        safe=True,
        examples=("Masa yapacağım hangi malzemeleri kullanmalıyım?", "Projeyi hocaya nasıl sunmalıyım?"),
        executor="generate_ai_answer",
    ),
    "LOCATION_INFO": ActionDefinition(
        name="LOCATION_INFO",
        description="Şehir, yer, kurum, mekan veya lokasyon hakkında açıklayıcı bilgi üretir.",
        parameters=("topic",),
        safe=True,
        examples=("Konya hakkında bilgi ver", "Meram'da ne yapılır?", "Selçuk Üniversitesi hakkında bilgi ver"),
        executor="generate_ai_answer",
    ),
    "UNSAFE_OR_BLOCKED": ActionDefinition(
        name="UNSAFE_OR_BLOCKED",
        description="Zararlı, yasa dışı veya güvenlik riski taşıyan genel bilgi isteklerini güvenli şekilde reddeder.",
        parameters=("message",),
        safe=True,
        examples=("Zararlı yazılım yaz", "Şifreleri nasıl çalarım?"),
        executor="answer_only",
    ),
    "CREATE_NOTE": ActionDefinition(
        name="CREATE_NOTE",
        description="Masaüstü veya Belgeler içine güvenli .txt not dosyası oluşturur.",
        parameters=("folder", "file_name", "content"),
        safe=True,
        examples=("Masaüstüne not oluştur ve içine proje sunumu yarın yaz", "Belgelerime toplantı notu kaydet"),
        executor="create_note",
    ),
    "APPEND_TO_NOTE": ActionDefinition(
        name="APPEND_TO_NOTE",
        description="NOVA tarafından oluşturulmuş güvenli .txt not dosyasına metin ekler.",
        parameters=("content", "file_name"),
        safe=True,
        examples=("Son nota şunu ekle", "Notuma bunu ekle"),
        executor="append_to_note",
    ),
    "CREATE_PROJECT_STRUCTURE": ActionDefinition(
        name="CREATE_PROJECT_STRUCTURE",
        description="Masaüstünde proje klasörü ve güvenli alt klasörler oluşturur.",
        parameters=("path", "folders"),
        safe=True,
        examples=("BitirmeProjesi proje yapısı oluştur", "SunumProjesi içine kodlar raporlar klasörlerini ekle"),
        executor="create_project_structure",
    ),
    "SAVE_LATEST_AI_NEWS": ActionDefinition(
        name="SAVE_LATEST_AI_NEWS",
        description="Son yapay zeka haberini özetleyip .txt dosyasına kaydeder.",
        parameters=("path", "topic", "file_name"),
        safe=True,
        examples=("Son yapay zeka haberini Projeler klasörüne kaydet",),
        executor="save_latest_ai_news",
    ),
    "SEARCH_TOPIC_AND_SAVE": ActionDefinition(
        name="SEARCH_TOPIC_AND_SAVE",
        description="Konu hakkında kısa internet/haber özeti hazırlayıp masaüstüne .txt kaydeder.",
        parameters=("topic", "path", "file_name"),
        safe=True,
        examples=("Siber güvenlik hakkında kısa özet hazırla", "Yapay zeka hakkında araştırma yap ve kaydet"),
        executor="search_topic_and_save",
    ),
    "CREATE_CALENDAR_EVENT": ActionDefinition(
        name="CREATE_CALENDAR_EVENT",
        description="Takvim/randevu için güvenli .ics dosyası oluşturur ve açar.",
        parameters=("title", "date", "time", "when", "duration_minutes"),
        safe=True,
        examples=("Yarın saat 2'ye toplantı ekle", "Yarın 14:00 toplantım var takvime koy"),
        executor="create_calendar_event",
    ),
    "CREATE_REMINDER": ActionDefinition(
        name="CREATE_REMINDER",
        description="Yerel JSON dosyasına hatırlatıcı ekler.",
        parameters=("title", "when"),
        safe=True,
        examples=("Bana 10 dakika sonra su içmeyi hatırlat",),
        executor="create_reminder",
    ),
    "LIST_REMINDERS": ActionDefinition(
        name="LIST_REMINDERS",
        description="Aktif yerel hatırlatıcıları listeler.",
        parameters=(),
        safe=True,
        examples=("Hatırlatıcılarımı listele",),
        executor="list_reminders",
    ),
    "COMPLETE_REMINDER": ActionDefinition(
        name="COMPLETE_REMINDER",
        description="Yerel hatırlatıcıyı tamamlandı işaretler.",
        parameters=("title",),
        safe=True,
        examples=("Su içme hatırlatıcısını tamamlandı yap",),
        executor="complete_reminder",
    ),
    "ADD_TODO": ActionDefinition(
        name="ADD_TODO",
        description="Yerel yapılacaklar listesine madde ekler.",
        parameters=("title",),
        safe=True,
        examples=("Yapılacaklara rapor yazmayı ekle",),
        executor="add_todo",
    ),
    "LIST_TODOS": ActionDefinition(
        name="LIST_TODOS",
        description="Aktif yapılacakları listeler.",
        parameters=(),
        safe=True,
        examples=("Yapılacaklarımı listele",),
        executor="list_todos",
    ),
    "COMPLETE_TODO": ActionDefinition(
        name="COMPLETE_TODO",
        description="Yerel yapılacak maddesini tamamlandı işaretler.",
        parameters=("title",),
        safe=True,
        examples=("Rapor yazmayı tamamlandı işaretle",),
        executor="complete_todo",
    ),
    "TAKE_SCREENSHOT": ActionDefinition(
        name="TAKE_SCREENSHOT",
        description="Masaüstündeki NOVA_Screenshots klasörüne ekran görüntüsü kaydeder.",
        parameters=(),
        safe=True,
        examples=("Ekran görüntüsü al ve masaüstüne kaydet",),
        executor="take_screenshot",
    ),
    "SEARCH_FILES": ActionDefinition(
        name="SEARCH_FILES",
        description="Desktop, Documents, Downloads veya Pictures içinde dosya arar.",
        parameters=("query", "folder"),
        safe=True,
        examples=("Masaüstünde rapor dosyasını ara", "Belgelerde staj geçen dosyaları bul"),
        executor="search_files",
    ),
    "SYSTEM_INFO": ActionDefinition(
        name="SYSTEM_INFO",
        description="Pil, disk boş alanı veya internet bağlantısı hakkında basit bilgi verir.",
        parameters=("topic",),
        safe=True,
        examples=("Pil yüzde kaç", "Diskte ne kadar boş yer var", "İnternet bağlı mı"),
        executor="system_info",
    ),
    "VOLUME_UP": ActionDefinition(
        name="VOLUME_UP",
        description="Sistem sesini güvenli medya tuşuyla artırır.",
        parameters=(),
        safe=True,
        examples=("Sesi artır",),
        executor="volume_up",
    ),
    "VOLUME_DOWN": ActionDefinition(
        name="VOLUME_DOWN",
        description="Sistem sesini güvenli medya tuşuyla azaltır.",
        parameters=(),
        safe=True,
        examples=("Sesi kıs",),
        executor="volume_down",
    ),
    "MUTE_VOLUME": ActionDefinition(
        name="MUTE_VOLUME",
        description="Sistem sesini güvenli medya tuşuyla kapatır.",
        parameters=(),
        safe=True,
        examples=("Sesi kapat",),
        executor="mute_volume",
    ),
    "UNMUTE_VOLUME": ActionDefinition(
        name="UNMUTE_VOLUME",
        description="Sistem sesini güvenli medya tuşuyla açar.",
        parameters=(),
        safe=True,
        examples=("Sesi aç",),
        executor="unmute_volume",
    ),
    "PLAY_PAUSE_MEDIA": ActionDefinition(
        name="PLAY_PAUSE_MEDIA",
        description="Medya oynatma/duraklatma tuşunu gönderir.",
        parameters=(),
        safe=True,
        examples=("Müziği durdur", "Devam ettir"),
        executor="play_pause_media",
    ),
    "COPY_TEXT_TO_CLIPBOARD": ActionDefinition(
        name="COPY_TEXT_TO_CLIPBOARD",
        description="Kullanıcının verdiği metni panoya kopyalar.",
        parameters=("text",),
        safe=True,
        examples=("Şunu panoya kopyala", "Bu metni kopyala"),
        executor="copy_text_to_clipboard",
    ),
    "VOLUME_CONTROL": ActionDefinition(
        name="VOLUME_CONTROL",
        description="Sistem sesini güvenli medya tuşlarıyla artırır, azaltır, kapatır veya açar.",
        parameters=("operation",),
        safe=True,
        examples=("Sesi biraz artır", "Sesi kapat", "Sessizden çıkar"),
        executor="volume_control",
    ),
    "DATE_TIME_ANSWER": ActionDefinition(
        name="DATE_TIME_ANSWER",
        description="Saat, tarih ve gün sorularını cevaplar.",
        parameters=("question",),
        safe=True,
        examples=("Saat kaç", "Bugünün tarihi ne", "Bugün günlerden ne"),
        executor="date_time_answer",
    ),
    "ANSWER_NOVA_CAPABILITIES": ActionDefinition(
        name="ANSWER_NOVA_CAPABILITIES",
        description="NOVA'nın desteklediği güvenli masaüstü işlemlerini açıklar.",
        parameters=(),
        safe=True,
        examples=("Ne yapabilirsin?", "Hangi işlemleri destekliyorsun?"),
        executor="answer_only",
    ),
    "OUT_OF_SCOPE_RESPONSE": ActionDefinition(
        name="OUT_OF_SCOPE_RESPONSE",
        description="Masaüstü asistanlığı dışındaki sohbetleri kapsam mesajıyla yanıtlar.",
        parameters=("message",),
        safe=True,
        examples=("Bugün ne yesem?", "Film öner"),
        executor="answer_only",
    ),
    "UNSAFE_REQUEST": ActionDefinition(
        name="UNSAFE_REQUEST",
        description="Tehlikeli veya yasak isteği güvenlik nedeniyle reddeder.",
        parameters=("message",),
        safe=True,
        examples=("Dosyaları sil", "PowerShell komutu çalıştır"),
        executor="answer_only",
    ),
    "NEEDS_CLARIFICATION": ActionDefinition(
        name="NEEDS_CLARIFICATION",
        description="Desteklenen işlem için eksik kritik bilgiyi kullanıcıdan ister.",
        parameters=("message",),
        safe=True,
        examples=("Takvimde yarın için sunum",),
        executor="answer_only",
    ),
    "ANSWER_ONLY": ActionDefinition(
        name="ANSWER_ONLY",
        description="Desteklenmeyen veya işlem gerektirmeyen komutlara sadece metin cevabı verir.",
        parameters=("message",),
        safe=True,
        examples=("NOVA'nın desteklediği masaüstü işlemleri hakkında kısa cevap ver.",),
        executor="answer_only",
    ),
    "MULTI_STEP": ActionDefinition(
        name="MULTI_STEP",
        description="Yalnızca güvenli action'lardan oluşan çok adımlı plan.",
        parameters=("steps",),
        safe=True,
        examples=("Klasör oluştur, haber kaydet ve klasörü aç",),
        executor="execute_plan",
    ),
}

PARAMETER_DESCRIPTIONS: dict[str, str] = {
    "path": "Masaüstü köküne göre güvenli klasör veya dosya yolu.",
    "content": "Yazılacak metin içeriği.",
    "folder": "desktop, documents, downloads veya pictures gibi izinli klasör anahtarı.",
    "app_name": "Açılacak whitelist uygulama adı.",
    "site": "Bilinen güvenli site kısa adı.",
    "url": "Yalnızca public http/https URL.",
    "query": "Web araması veya dosya araması metni.",
    "topic": "Araştırılacak veya özetlenecek konu.",
    "max_results": "Gösterilecek en fazla akademik kaynak sayısı.",
    "save_to_file": "Akademik rapor dosyaya kaydedilsin mi: true veya false.",
    "summary_level": "Özet seviyesi: short veya medium.",
    "file_name": "Güvenli .txt dosya adı.",
    "folders": "Virgülle ayrılmış alt klasör adları.",
    "title": "Etkinlik, hatırlatıcı veya yapılacak başlığı.",
    "date": "Etkinlik tarihi.",
    "time": "Etkinlik saati.",
    "when": "Kullanıcının verdiği doğal tarih/saat ifadesi.",
    "duration_minutes": "Etkinlik süresi, dakika.",
    "message": "Kullanıcıya gösterilecek kısa cevap.",
    "question": "Saat/tarih veya genel cevap modunda cevaplanacak soru.",
    "mode": "Cevap modu: general, guide, research veya location.",
    "text": "Panoya kopyalanacak metin.",
    "operation": "Ses kontrol işlemi: up, down, mute veya unmute.",
    "steps": "MULTI_STEP içindeki güvenli action adımları.",
}

OPTIONAL_PARAMETERS: dict[str, set[str]] = {
    "OPEN_WEBSITE": {"site", "url"},
    "WEB_RESEARCH_SAVE": {"file_name"},
    "CREATE_NOTE": {"folder", "file_name", "content"},
    "APPEND_TO_NOTE": {"file_name"},
    "CREATE_PROJECT_STRUCTURE": {"folders"},
    "SAVE_LATEST_AI_NEWS": {"path", "topic", "file_name"},
    "SEARCH_TOPIC_AND_SAVE": {"path", "file_name"},
    "CREATE_CALENDAR_EVENT": {"date", "time", "when", "duration_minutes"},
    "SEARCH_FILES": {"folder"},
    "SYSTEM_INFO": {"topic"},
    "DATE_TIME_ANSWER": {"question"},
    "ACADEMIC_SEARCH": {"max_results", "save_to_file", "summary_level"},
    "GENERAL_AI_ANSWER": {"mode"},
    "ANSWER_NOVA_CAPABILITIES": set(),
    "UNSAFE_OR_BLOCKED": {"message"},
    "OUT_OF_SCOPE_RESPONSE": {"message"},
    "UNSAFE_REQUEST": {"message"},
    "NEEDS_CLARIFICATION": {"message"},
}


def safe_action_names() -> set[str]:
    return {name for name, action in ACTION_REGISTRY.items() if action.safe}


def action_arg_keys(action_name: str) -> tuple[str, ...]:
    action = ACTION_REGISTRY.get(action_name)
    return action.parameters if action else ()


def registry_for_prompt() -> str:
    lines = []
    for action in ACTION_REGISTRY.values():
        if not action.safe:
            continue
        examples = "; ".join(action.examples)
        params = ", ".join(action.parameters) if action.parameters else "parametre yok"
        lines.append(
            f"- {action.name}: {action.description} Parametreler: {params}. "
            f"Örnek niyetler: {examples}. Çalıştırıcı: {action.executor}."
        )
    return "\n".join(lines)


def registry_schema() -> dict[str, dict[str, Any]]:
    """Return a compact machine-readable tool schema for the LLM intent router."""
    schema: dict[str, dict[str, Any]] = {}
    for action in ACTION_REGISTRY.values():
        if not action.safe:
            continue
        optional = OPTIONAL_PARAMETERS.get(action.name, set())
        parameters = {
            param: {
                "type": "string" if param != "steps" else "array",
                "required": param not in optional,
                "description": PARAMETER_DESCRIPTIONS.get(param, "Action parametresi."),
            }
            for param in action.parameters
        }
        schema[action.name] = {
            "name": action.name,
            "description": action.description,
            "parameters": parameters,
            "safety": "safe" if action.safe else "blocked",
            "examples": list(action.examples),
            "executor": action.executor,
        }
    return schema


def registry_schema_for_prompt() -> str:
    return json.dumps(registry_schema(), ensure_ascii=False, indent=2)
