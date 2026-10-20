"""摘要补全：某些 feed（如 Hugging Face）条目中没有摘要，回源抓取文章页提取导语。"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

from .models import Article, html_to_text

logger = logging.getLogger(__name__)

# 目录段特征：一段里出现 4 个以上 "1." / "2.1" 之类的章节编号
_TOC_RE = re.compile(r"\d+(?:\.\d+)*\.?\s+\S")
_TOC_THRESHOLD = 4

# 明显是站点占位描述的特征（如 HF 的 "A Blog post by X on Hugging Face"）
_PLACEHOLDER_PATTERNS = (
    "blog post by",
    "article by",
    "we’re on a journey",
    "we're on a journey",
    "open source and open science",
)


def _extract_lead(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    # 1) 优先 meta description（长度足够且不是站点占位文案）
    for attr, key in (
        ("property", "og:description"),
        ("name", "twitter:description"),
        ("name", "description"),
    ):
        tag = soup.find("meta", attrs={attr: key})
        content = (tag.get("content") or "").strip() if tag else ""
        low = content.lower()
        if len(content) >= 60 and not any(p in low for p in _PLACEHOLDER_PATTERNS):
            return content

    # 2) 回退：正文容器中的首批实质性段落（剔除目录、导航、页眉）
    container = soup.select_one("article, main, div.prose, .post-content, .entry-content")
    if not container:
        return ""
    for tag in container.select("nav, header, footer, [id*=toc i], [class*=toc i], [class*=table-of-contents]"):
        tag.decompose()

    paragraphs: list[str] = []
    total = 0
    for p in container.find_all("p"):
        text = html_to_text(str(p))
        # 图注等短段跳过
        if len(text) < 80:
            continue
        # 整段目录（多个章节编号挤在一个 <p> 里）跳过
        if len(_TOC_RE.findall(text)) >= _TOC_THRESHOLD:
            continue
        paragraphs.append(text)
        total += len(text)
        if len(paragraphs) >= 2 or total >= 600:
            break
    return " ".join(paragraphs)


async def enrich_summary(client: httpx.AsyncClient, article: Article, max_chars: int = 600) -> bool:
    """原地为缺少摘要的文章抓取并填充导语。成功返回 True。"""
    if article.raw_summary:
        return False
    try:
        resp = await client.get(article.link)
        resp.raise_for_status()
        lead = await asyncio.to_thread(_extract_lead, resp.text)
        if lead:
            article.raw_summary = lead[:max_chars].strip()
            return True
        logger.info("文章页未提取到导语 [%s]", article.source)
    except Exception as exc:  # noqa: BLE001 - 导语补全失败不影响推送
        logger.info("摘要补全失败 [%s]: %s", article.source, exc)
    return False
