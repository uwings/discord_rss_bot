"""数据模型与文本工具。"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


@dataclass
class Article:
    source: str
    title: str
    link: str
    key: str  # 去重键
    published: datetime | None = None
    raw_summary: str = ""
    lang: str = ""  # 源配置的语言提示；空表示自动检测
    # 流水线中填充
    title_zh: str = ""
    summary_zh: str = ""
    translated: bool = False

    @property
    def display_title(self) -> str:
        return self.title_zh or self.title

    @property
    def display_summary(self) -> str:
        return self.summary_zh or self.raw_summary


def html_to_text(value: str | None) -> str:
    """HTML → 纯文本：去标签、解码实体、折叠空白。"""
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(separator=" ")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def has_chinese(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in (text or ""))


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}


def canonical_url(url: str) -> str:
    """去除 utm_* 跟踪参数，用于更稳定的去重。"""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _TRACKING_PARAMS]
    return urlunsplit(parts._replace(query=urlencode(query)))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
