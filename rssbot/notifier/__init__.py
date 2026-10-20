"""通知层：Notifier 协议。未来新增飞书/Telegram 等渠道只需实现该协议。"""

from __future__ import annotations

from typing import Protocol

from ..models import Article


class Notifier(Protocol):
    async def send(self, article: Article) -> None:
        """推送一篇文章；失败应抛出异常由调用方决定重试/记录。"""
        ...

    async def close(self) -> None: ...
