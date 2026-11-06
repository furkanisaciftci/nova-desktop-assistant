from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

from app.config import DESKTOP_DIR
from app.news import fetch_latest_ai_news, summarize_news


RESEARCH_DIR = DESKTOP_DIR / "NOVA_Research"
USER_AGENT = "NOVA-Assistant/1.0"
UNSAFE_URL_MESSAGE = "Bu işlem güvenlik nedeniyle uygulanmadı."


def web_research_summary(topic: str) -> dict[str, Any]:
    clean_topic = _clean_topic(topic)
    if not clean_topic:
        return _message_result("Hangi konuyu araştırmamı istersiniz?", "Hangi konuyu araştırmamı istersiniz?")

    result = _search_duckduckgo(clean_topic)
    if not result:
        return _message_result("İnternet kaynağına ulaşılamadı.", "İnternet kaynağına ulaşılamadı.")

    screen = "\n".join([
        f"{clean_topic} hakkında kısa araştırma tamamlandı.",
        "",
        "Özet:",
        f"- {_shorten(result.get('snippet', '') or result.get('title', ''), 520)}",
        "",
        "Kaynaklar:",
        f"1. {result.get('title', 'Bilinmiyor')}",
        f"   {result.get('url', '')}",
    ]).strip()
    spoken = f"{clean_topic} araştırması tamamlandı. Özet ve kaynaklar ekranda gösteriliyor."
    return _message_result(screen, spoken)


def web_research_save(topic: str, file_name: str = "") -> dict[str, Any]:
    clean_topic = _clean_topic(topic)
    if not clean_topic:
        raise ValueError("Hangi konuyu araştırmamı istersiniz?")

    summary = web_research_summary(clean_topic)
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_file_name(file_name or f"{clean_topic}_rapor.txt")
    path = (RESEARCH_DIR / safe_name).resolve()
    if RESEARCH_DIR.resolve() not in path.parents and path != RESEARCH_DIR.resolve():
        raise ValueError("Araştırma raporu güvenli klasör dışına yazılamaz.")
    path.write_text(str(summary.get("screen_message", "")) + "\n", encoding="utf-8")
    screen = f"Araştırma raporu kaydedildi.\n\nDosya: {path}"
    return _message_result(screen, "Araştırma raporu kaydedildi.", path=str(path))


def summarize_url(url: str) -> dict[str, Any]:
    safe_url = validate_public_url(url)
    try:
        response = requests.get(safe_url, timeout=10, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
    except Exception:
        return _message_result("Sayfa içeriğine ulaşılamadı.", "Sayfa içeriğine ulaşılamadı.")

    text = _html_to_text(response.text)
    if not text:
        return _message_result("Sayfa içeriğine ulaşılamadı.", "Sayfa içeriğine ulaşılamadı.")

    screen = "\n".join(
        [
            "Sayfa Özeti:",
            _shorten(text, 700),
            "",
            "Kaynak bağlantıları:",
            f"1. {safe_url}",
        ]
    )
    return _message_result(screen, "Sayfa özeti hazırlandı. Kaynak bağlantısı ekranda gösteriliyor.")


def latest_news_by_topic(topic: str) -> dict[str, Any]:
    clean_topic = _clean_topic(topic) or "güncel haberler"
    try:
        item = fetch_latest_ai_news(clean_topic)
        summary = summarize_news(item)
    except Exception:
        return _message_result("İnternet kaynağına ulaşılamadı.", "İnternet kaynağına ulaşılamadı.")

    heading_topic = clean_topic if "haber" not in clean_topic.casefold() else clean_topic.replace(" haberleri", "").replace(" haberlerini", "")
    screen = "\n".join(
        [
            f"{heading_topic} haberleri özetlendi.",
            "",
            f"Başlık: {item.get('title', '')}",
            f"Kaynak: {item.get('source', '') or 'Bilinmiyor'}",
            f"Tarih: {item.get('published', '') or 'Bilinmiyor'}",
            "",
            "Kısa özet:",
            summary.strip(),
            "",
            "Kaynak bağlantıları:",
            f"1. {item.get('link', '')}",
        ]
    ).strip()
    return _message_result(screen, f"{heading_topic} haberleri özetlendi. Kaynak bağlantısı ekranda gösteriliyor.")


def official_info_search(topic: str) -> dict[str, Any]:
    clean_topic = _clean_topic(topic)
    if not clean_topic:
        return _message_result("Hangi konuyu araştırmamı istersiniz?", "Hangi konuyu araştırmamı istersiniz?")

    query = clean_topic
    if "selçuk" in clean_topic.casefold() or "selcuk" in clean_topic.casefold():
        query = f"site:selcuk.edu.tr {clean_topic}"
    elif "üniversite" in clean_topic.casefold() or "universite" in clean_topic.casefold():
        query = f"{clean_topic} resmi site"

    result = _search_duckduckgo(query)
    if not result:
        return _message_result("Resmi kaynağa ulaşılamadı.", "Resmi kaynağa ulaşılamadı.")

    screen = "\n".join(
        [
            f"Resmi kaynak araması: {clean_topic}",
            "",
            _shorten(result.get("snippet", "") or result.get("title", ""), 520),
            "",
            "Kaynaklar:",
            f"1. {result.get('title', 'Bilinmiyor')}",
            "",
            "Kaynak bağlantıları:",
            f"1. {result.get('url', '')}",
        ]
    ).strip()
    return _message_result(screen, "Resmi kaynak araması tamamlandı. Sonuç ekranda gösteriliyor.")


def academic_search(
    topic: str,
    max_results: int = 5,
    save_to_file: bool = False,
    summary_level: str = "medium",
) -> dict[str, Any]:
    clean_topic = _clean_topic(topic)
    if not clean_topic:
        return _message_result("Hangi konuda akademik kaynak aramamı istersiniz?", "Hangi konuda akademik kaynak aramamı istersiniz?", items=[])

    limit = max(1, min(int(max_results or 5), 5))
    search_query = _academic_query(clean_topic)
    items = _arxiv_search(search_query, limit)
    if len(items) < limit:
        existing_urls = {item.get("url", "") for item in items}
        for item in _crossref_search(search_query, limit - len(items)):
            if item.get("url", "") not in existing_urls:
                items.append(item)
                existing_urls.add(item.get("url", ""))
            if len(items) >= limit:
                break
    if not items:
        items = _academic_web_fallback(clean_topic)

    if not items:
        return _message_result("Akademik kaynaklara ulaşılamadı.", "Akademik kaynaklara ulaşılamadı.", topic=clean_topic, items=[])

    summary = _academic_summary(clean_topic, items, summary_level)
    screen = _format_academic_screen(clean_topic, summary, items)
    spoken = "Akademik kaynaklar bulundu. Özet ve kaynak bağlantıları ekranda gösteriliyor."
    path = ""
    if save_to_file:
        path = str(_save_academic_report(clean_topic, summary, items))
        screen += f"\n\nRapor kaydedildi:\n{path}"
        spoken = "Akademik araştırma raporu kaydedildi."

    return {
        "topic": clean_topic,
        "summary": summary,
        "items": items,
        "screen_message": screen,
        "spoken_message": spoken,
        "path": path,
    }


def validate_public_url(url: str) -> str:
    candidate = str(url or "").strip()
    if not candidate:
        raise ValueError("URL belirtilmedi.")
    if "://" not in candidate:
        candidate = "https://" + candidate
    lowered = candidate.casefold()
    if lowered.startswith(("javascript:", "file:", "data:")):
        raise ValueError(UNSAFE_URL_MESSAGE)
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(UNSAFE_URL_MESSAGE)
    host = (parsed.hostname or "").casefold()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(UNSAFE_URL_MESSAGE)
    if host.startswith("10.") or host.startswith("192.168.") or re.match(r"172\.(1[6-9]|2\d|3[01])\.", host):
        raise ValueError(UNSAFE_URL_MESSAGE)
    return candidate


def _search_duckduckgo(query: str) -> dict[str, str] | None:
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=10,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except Exception:
        return None

    html = response.text
    match = re.search(
        r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return {
        "title": _html_to_text(match.group("title")),
        "url": _clean_search_url(unescape(match.group("url"))),
        "snippet": _html_to_text(match.group("snippet")),
    }


def _clean_search_url(url: str) -> str:
    value = str(url or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if "duckduckgo.com" in (parsed.hostname or ""):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return value


def _arxiv_search(topic: str, limit: int) -> list[dict[str, str]]:
    try:
        response = requests.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{topic}",
                "start": 0,
                "max_results": limit,
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            timeout=12,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except Exception:
        return []

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", ns):
        title = _html_to_text(entry.findtext("atom:title", default="", namespaces=ns))
        url = _clean_topic(entry.findtext("atom:id", default="", namespaces=ns))
        published = _clean_topic(entry.findtext("atom:published", default="", namespaces=ns))
        summary = _html_to_text(entry.findtext("atom:summary", default="", namespaces=ns))
        authors = [
            _html_to_text(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        year = published[:4] if published else "Belirtilmemiş"
        items.append(
            {
                "title": title or "Başlık belirtilmemiş",
                "authors": ", ".join(author for author in authors if author) or "Belirtilmemiş",
                "year": year or "Belirtilmemiş",
                "source": "arXiv",
                "url": url,
                "short_note": _shorten(summary, 220) or "Konu ile ilişkili akademik kaynak.",
            }
        )
        if len(items) >= limit:
            break
    return items


def _crossref_search(topic: str, limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        return []
    try:
        response = requests.get(
            "https://api.crossref.org/works",
            params={"query": topic, "rows": limit},
            timeout=12,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    items: list[dict[str, str]] = []
    for item in data.get("message", {}).get("items", []):
        title_values = item.get("title") or []
        title = _html_to_text(title_values[0] if title_values else "")
        authors = _format_crossref_authors(item.get("author") or [])
        year = _crossref_year(item)
        url = str(item.get("URL") or "")
        container = item.get("container-title") or []
        source = _html_to_text(container[0] if container else "Crossref")
        if not title:
            continue
        items.append(
            {
                "title": title,
                "authors": authors or "Belirtilmemiş",
                "year": year or "Belirtilmemiş",
                "source": source or "Crossref",
                "url": url,
                "short_note": "Crossref kaydında konu ile ilişkili akademik yayın olarak listeleniyor.",
            }
        )
        if len(items) >= limit:
            break
    return items


def _academic_web_fallback(topic: str) -> list[dict[str, str]]:
    result = _search_duckduckgo(f"{topic} academic paper scholarly source")
    if not result:
        return []
    return [
        {
            "title": result.get("title", "Başlık belirtilmemiş"),
            "authors": "Belirtilmemiş",
            "year": "Belirtilmemiş",
            "source": "Web akademik arama",
            "url": result.get("url", ""),
            "short_note": _shorten(result.get("snippet", ""), 220) or "Akademik kaynak araması için web sonucunda listelendi.",
        }
    ]


def _academic_query(topic: str) -> str:
    normalized = topic.casefold()
    mappings = {
        "yapay zeka": "artificial intelligence",
        "siber güvenlik": "cybersecurity",
        "siber guvenlik": "cybersecurity",
        "makine öğrenmesi": "machine learning",
        "makine ogrenmesi": "machine learning",
        "derin öğrenme": "deep learning",
        "derin ogrenme": "deep learning",
        "büyük dil modeli": "large language models",
        "buyuk dil modeli": "large language models",
    }
    for key, value in mappings.items():
        if key in normalized:
            return value
    return topic


def _format_crossref_authors(authors: list[dict[str, Any]]) -> str:
    names = []
    for author in authors[:4]:
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        name = " ".join(part for part in (given, family) if part)
        if name:
            names.append(name)
    if len(authors) > 4:
        names.append("vd.")
    return ", ".join(names)


def _crossref_year(item: dict[str, Any]) -> str:
    for key in ("published-print", "published-online", "created", "issued"):
        parts = item.get(key, {}).get("date-parts") or []
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def _academic_summary(topic: str, items: list[dict[str, str]], summary_level: str) -> str:
    focus_terms = []
    for item in items[:5]:
        title = item.get("title", "")
        words = [word for word in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]{5,}", title) if word.casefold() not in topic.casefold()]
        focus_terms.extend(words[:2])
    focus = ", ".join(dict.fromkeys(focus_terms[:6]))
    if focus:
        return f"{topic} konusunda bulunan akademik kaynaklar özellikle {focus} gibi alt başlıklar etrafında yoğunlaşıyor."
    return f"{topic} konusunda bulunan akademik kaynaklar aşağıda kaynak ve kısa notlarıyla listelenmiştir."


def _format_academic_screen(topic: str, summary: str, items: list[dict[str, str]]) -> str:
    lines = [
        "Akademik kaynaklar bulundu.",
        "",
        f"Konu: {topic}",
        "",
        "Kısa özet:",
        summary,
        "",
        "Öne çıkan kaynaklar:",
    ]
    for index, item in enumerate(items[:5], start=1):
        lines.extend(
            [
                f"{index}. {item.get('title', 'Başlık belirtilmemiş')}",
                f"   Yazar/Yıl: {item.get('authors', 'Belirtilmemiş')} / {item.get('year', 'Belirtilmemiş')}",
                f"   Kaynak: {item.get('source', 'Belirtilmemiş')}",
                f"   Kısa not: {item.get('short_note', '')}",
                "",
            ]
        )
    links = [item.get("url", "") for item in items[:5] if item.get("url")]
    if links:
        lines.append("Kaynak bağlantıları:")
        for index, url in enumerate(links, start=1):
            lines.append(f"{index}. {url}")
    return "\n".join(lines).strip()


def _save_academic_report(topic: str, summary: str, items: list[dict[str, str]]) -> Path:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    path = (RESEARCH_DIR / f"{_safe_file_stem(topic)}_akademik_kaynaklar.md").resolve()
    if RESEARCH_DIR.resolve() not in path.parents and path != RESEARCH_DIR.resolve():
        raise ValueError("Akademik rapor güvenli klasör dışına yazılamaz.")

    lines = [
        "# Akademik Kaynak Araştırması",
        "",
        "## Konu",
        topic,
        "",
        "## Kısa Değerlendirme",
        summary,
        "",
        "## Kaynaklar",
        "",
    ]
    for index, item in enumerate(items[:5], start=1):
        lines.extend(
            [
                f"### {index}. {item.get('title', 'Başlık belirtilmemiş')}",
                f"- Yazar/Yıl: {item.get('authors', 'Belirtilmemiş')} / {item.get('year', 'Belirtilmemiş')}",
                f"- Kaynak: {item.get('source', 'Belirtilmemiş')}",
                f"- Bağlantı: {item.get('url', '')}",
                f"- Kısa not: {item.get('short_note', '')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Oluşturulma Tarihi",
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            "",
            "NOVA tarafından açık akademik kaynaklardan derlenmiştir.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return " ".join(text.split())


def _clean_topic(topic: str) -> str:
    return _html_to_text(str(topic or "")).strip()


def _shorten(value: str, limit: int) -> str:
    clean = _html_to_text(value)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _safe_file_name(value: str) -> str:
    stem = Path(value).stem
    stem = re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü0-9_-]+", "_", stem).strip("_") or "nova_rapor"
    return stem + ".txt"


def _safe_file_stem(value: str) -> str:
    normalized = _clean_topic(value).casefold().replace("ı", "i")
    replacements = str.maketrans("çğıöşü", "cgiosu")
    normalized = normalized.translate(replacements)
    return re.sub(r"[^a-z0-9_-]+", "_", normalized).strip("_") or "akademik_kaynaklar"


def _message_result(screen_message: str, spoken_message: str, **extra: Any) -> dict[str, Any]:
    return {
        "screen_message": screen_message,
        "spoken_message": spoken_message,
        **extra,
    }
