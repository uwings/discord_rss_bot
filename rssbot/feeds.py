"""RSS 源拉取与解析：httpx 异步抓取（支持代理/重试），feedparser 在线程中解析。"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import logging
from datetime import datetime, timezone

import feedparser
import httpx

from .config import FeedConfig
from .models import Article, canonical_url, html_to_text

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def build_client(timeout: int, proxy: str = "") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=timeout),
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
        follow_redirects=True,
        proxy=proxy or None,
    )


async def _fetch_bytes(client: httpx.AsyncClient, url: str, retries: int = 2) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001 - 单源失败由调用方隔离
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _parse(raw: bytes, feed: FeedConfig) -> list[Article]:
    parsed = feedparser.parse(raw)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"RSS 解析失败: {parsed.bozo_exception!r}")

    articles: list[Article] = []
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = html_to_text(entry.get("title"))
        if not link or not title:
            continue

        guid = (entry.get("id") or entry.get("guid") or link).strip()
        key_source = guid if guid else canonical_url(link)
        key = hashlib.md5(key_source.encode("utf-8")).hexdigest()

        # 摘要优先级：content[0] > summary > description
        raw_summary = ""
        content = entry.get("content")
        if content and isinstance(content, list):
            raw_summary = content[0].get("value", "")
        if not raw_summary:
            raw_summary = entry.get("summary") or entry.get("description") or ""

        published = _entry_time(entry)

        articles.append(
            Article(
                source=feed.name,
                title=title,
                link=canonical_url(link),
                key=key,
                published=published,
                raw_summary=html_to_text(raw_summary),
                lang=feed.lang,
            )
        )
    return articles


def _entry_time(entry) -> datetime | None:
    """feedparser 的 *_parsed 是 UTC struct_time，必须用 calendar.timegm（旧代码误用 time.mktime）。"""
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)


async def fetch_feed(client: httpx.AsyncClient, feed: FeedConfig) -> list[Article]:
    raw = await _fetch_bytes(client, feed.url)
    return await asyncio.to_thread(_parse, raw, feed)


async def fetch_all(client: httpx.AsyncClient, feeds: list[FeedConfig]) -> tuple[list[Article], dict[str, str]]:
    """并发拉取全部源。返回 (文章列表, {源名: 错误信息})。"""
    results = await asyncio.gather(
        *(fetch_feed(client, feed) for feed in feeds), return_exceptions=True
    )

    articles: list[Article] = []
    errors: dict[str, str] = {}
    for feed, result in zip(feeds, results):
        if isinstance(result, Exception):
            errors[feed.name] = f"{type(result).__name__}: {result}"
            logger.warning("源拉取失败 [%s]: %s", feed.name, result)
        else:
            logger.info("源 [%s] 获取 %d 篇", feed.name, len(result))
            articles.extend(result)
    return articles, errors
