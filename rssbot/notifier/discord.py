"""Discord Webhook 通知器：发送 Embed 卡片，处理 429 限流与长度上限。"""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..models import Article, has_chinese, truncate

logger = logging.getLogger(__name__)

# Discord Embed 限制
LIMIT_TITLE = 256
LIMIT_DESCRIPTION = 4096
LIMIT_FIELD_NAME = 256
LIMIT_FIELD_VALUE = 1024
LIMIT_AUTHOR = 256

EMBED_COLOR = 0x5865F2  # Discord blurple


class DiscordWebhookNotifier:
    def __init__(self, webhook_url: str, client: httpx.AsyncClient):
        self.webhook_url = webhook_url
        self.client = client

    def _build_payload(self, article: Article) -> dict:
        embed: dict = {
            "author": {"name": truncate(article.source, LIMIT_AUTHOR)},
            "title": truncate(article.display_title, LIMIT_TITLE),
            "url": article.link,
            "color": EMBED_COLOR,
            # 中文摘要为主，保守取 1500 字保证整卡片远低于 6000 总量
            "description": truncate(article.display_summary, 1500) or "（无摘要）",
        }
        if article.published:
            embed["timestamp"] = article.published.isoformat()

        # 译文与原文不同语言时，附英文原文便于核对
        original_parts = [article.title]
        if article.raw_summary and not has_chinese(article.raw_summary):
            original_parts.append(truncate(article.raw_summary, 300))
        original_value = truncate("\n".join(original_parts), LIMIT_FIELD_VALUE)
        if article.translated and not has_chinese(article.title):
            embed["fields"] = [
                {"name": truncate("Original", LIMIT_FIELD_NAME), "value": original_value, "inline": False}
            ]

        return {"embeds": [embed]}

    async def send(self, article: Article) -> None:
        payload = self._build_payload(article)
        # 429 限流最多重试 3 次
        for attempt in range(4):
            resp = await self.client.post(self.webhook_url, params={"wait": "true"}, json=payload)
            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 2) if resp.content else 2
                logger.warning("Discord 限流，%.1f 秒后重试（%s）", retry_after, article.source)
                await asyncio.sleep(float(retry_after) + 0.5)
                continue
            if resp.status_code in (200, 204):
                return
            if 500 <= resp.status_code < 600 and attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            body = resp.text[:300]
            raise RuntimeError(f"Discord webhook 返回 {resp.status_code}: {body}")
        raise RuntimeError("Discord webhook 多次限流后仍发送失败")

    async def send_embeds(self, embeds: list[dict]) -> None:
        """发送通用 embed（3.0 简报/问答用），处理限流与重试。"""
        payload = {"embeds": embeds[:10]}  # Webhook 每条消息最多 10 个 embed
        for attempt in range(4):
            resp = await self.client.post(self.webhook_url, params={"wait": "true"}, json=payload)
            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 2) if resp.content else 2
                logger.warning("Discord 限流，%.1f 秒后重试", retry_after)
                await asyncio.sleep(float(retry_after) + 0.5)
                continue
            if resp.status_code in (200, 204):
                return
            if 500 <= resp.status_code < 600 and attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Discord webhook 返回 {resp.status_code}: {resp.text[:300]}")
        raise RuntimeError("Discord webhook 多次限流后仍发送失败")

    async def close(self) -> None:  # 客户端由外部统一管理，这里无需处理
        return None
