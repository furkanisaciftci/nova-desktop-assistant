from __future__ import annotations

from email.utils import parsedate_to_datetime
from html import unescape
import re
from urllib.parse import quote_plus

import feedparser
import requests

from app.config import DEFAULT_NEWS_TOPIC, OPENAI_API_KEY, OPENAI_MODEL


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=tr&gl=TR&ceid=TR:tr"


def fetch_latest_ai_news(topic: str = DEFAULT_NEWS_TOPIC) -> dict[str, str]:
    query = quote_plus(topic or DEFAULT_NEWS_TOPIC)
    url = GOOGLE_NEWS_RSS.format(query=query)
    response = requests.get(url, timeout=12, headers={"User-Agent": "NOVA-Assistant-MVP/1.0"})
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    if not feed.entries:
        raise RuntimeError("Google News RSS içinde haber bulunamadı.")

    entry = feed.entries[0]
    published = _format_date(entry.get("published", ""))
    return {
        "title": _clean_text(entry.get("title", "Başlık yok")),
        "link": entry.get("link", ""),
        "published": published,
        "source": _clean_text(entry.get("source", {}).get("title", "")) if entry.get("source") else "",
        "summary": _clean_text(entry.get("summary", "")),
    }


def summarize_news(news_item: dict[str, str]) -> str:
    if OPENAI_API_KEY:
        try:
            return _summarize_with_openai(news_item)
        except Exception:
            pass
    return _fallback_summary(news_item)


def build_news_document(news_item: dict[str, str], summary: str) -> str:
    lines = [
        "Son Yapay Zeka Haberi",
        "",
        f"Başlık: {news_item.get('title', '')}",
        f"Kaynak: {news_item.get('source', '') or 'Bilinmiyor'}",
        f"Tarih: {news_item.get('published', '') or 'Bilinmiyor'}",
        f"Bağlantı: {news_item.get('link', '')}",
        "",
        "Kısa Özet:",
        summary.strip(),
        "",
    ]
    return "\n".join(lines)


def _summarize_with_openai(news_item: dict[str, str]) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": "Türkçe, kısa ve tarafsız haber özeti yaz. 3-4 cümleyi geçme.",
            },
            {
                "role": "user",
                "content": (
                    f"Başlık: {news_item.get('title', '')}\n"
                    f"Kaynak: {news_item.get('source', '')}\n"
                    f"Tarih: {news_item.get('published', '')}\n"
                    f"Özet/içerik: {news_item.get('summary', '')}\n"
                    f"Link: {news_item.get('link', '')}"
                ),
            },
        ],
    )
    return response.output_text.strip()


def _fallback_summary(news_item: dict[str, str]) -> str:
    title = news_item.get("title", "").strip()
    source = news_item.get("source", "").strip() or "haber kaynağı"
    summary = news_item.get("summary", "").strip()
    if summary:
        return f"{source} kaynağına göre: {_shorten(summary, 450)}"
    return f"{source} kaynağı, şu yapay zeka haberini öne çıkarıyor: {title}"


def _format_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return value


def _clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value))
    decoded = unescape(without_tags)
    return " ".join(decoded.replace("\n", " ").split())


def _shorten(value: str, limit: int) -> str:
    cleaned = _clean_text(value)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."
