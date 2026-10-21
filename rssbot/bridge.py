"""KC 共脑知识库客户端：经 local-data-bridge 的向量检索。

只做语义查询（只读）。Bridge 负责服务端 embedding，消费方零成本。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from .config import BridgeConfig

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


@dataclass
class KnowledgeHit:
    score: float
    snippet: str
    date: str = ""
    canonical_id: str = ""

    def reference(self) -> str:
        return self.date or "未标日期"


class KnowledgeBase:
    def __init__(self, cfg: BridgeConfig, token: str):
        self.cfg = cfg
        self.token = token

    async def health(self) -> bool:
        try:
            async with self._client(10) as client:
                r = await client.get("/health")
                r.raise_for_status()
                return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bridge 健康检查失败: %s", exc)
            return False

    def _client(self, timeout: int | None = None) -> httpx.AsyncClient:
        # Bridge 是内网地址，强制直连，不走外网代理
        return httpx.AsyncClient(
            base_url=self.cfg.base_url,
            timeout=timeout or self.cfg.timeout_seconds,
            headers={"Authorization": f"Bearer {self.token}"},
            trust_env=False,
        )

    async def query(self, question: str, top_k: int | None = None) -> list[KnowledgeHit]:
        """语义检索，失败返回空列表（由调用方决定降级方式）。"""
        body = {"query": question, "top_k": top_k or self.cfg.top_k}
        try:
            async with self._client() as client:
                resp = await client.post(f"/vector/{self.cfg.collection}/query", json=body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("KC 向量查询失败: %s", exc)
            return []

        raw = data.get("data", {}).get("results") or data.get("results") or []
        hits: list[KnowledgeHit] = []
        for h in raw:
            payload = h.get("payload") or {}
            snippet = payload.get("body_snippet") or payload.get("text") or ""
            date_m = _DATE_RE.search(snippet)
            hits.append(
                KnowledgeHit(
                    score=float(h.get("score") or 0),
                    snippet=snippet,
                    date=date_m.group(1) if date_m else "",
                    canonical_id=str(payload.get("canonical_id") or ""),
                )
            )
        return hits
