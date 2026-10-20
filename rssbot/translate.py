"""可插拔翻译层：Google 免费 gtx 接口（默认）/ OpenAI 兼容 LLM / 不翻译。"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx

from .config import LLMConfig

logger = logging.getLogger(__name__)

# 单请求保守切块（gtx 接口支持较长文本，保守取 3000）
CHUNK_SIZE = 3000
GTX_ENDPOINT = "https://translate.googleapis.com/translate_a/single"


class Translator(Protocol):
    async def translate_title(self, title: str) -> str: ...

    async def translate_summary(self, summary: str) -> str: ...


class NoneTranslator:
    async def translate_title(self, title: str) -> str:
        return ""

    async def translate_summary(self, summary: str) -> str:
        return ""


class GoogleTranslateService:
    """Google 翻译免费 gtx 接口（无需 key），用 httpx 直接调用，支持代理与重试。

    不使用 deep-translator：它抓取 /m 网页端点，在共享出口 IP 上极易被限流。
    """

    def __init__(self, proxy: str = "") -> None:
        self.proxy = proxy or None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30, proxy=self.proxy)

    async def translate_title(self, title: str) -> str:
        return await self._translate(title)

    async def translate_summary(self, summary: str) -> str:
        # 免费接口不做摘要，先截断英文原文再翻译
        return await self._translate(summary[:1200])

    async def _translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        chunks = [text[i : i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
        translated: list[str] = []
        async with self._client() as client:
            for index, chunk in enumerate(chunks):
                result = await self._translate_chunk(client, chunk, index)
                if result is None:
                    return ""  # 失败整体降级为原文，避免中英混杂
                translated.append(result)
                if index < len(chunks) - 1:
                    await asyncio.sleep(0.3)
        return "".join(translated).strip()

    async def _translate_chunk(self, client: httpx.AsyncClient, chunk: str, index: int) -> str | None:
        params = {"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": chunk}
        for attempt in range(3):
            try:
                resp = await client.get(GTX_ENDPOINT, params=params)
                resp.raise_for_status()
                data = resp.json()
                return "".join(seg[0] for seg in data[0] if seg and seg[0])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Google 翻译失败（第 %d 块，第 %d 次）: %s", index + 1, attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
        return None


class LLMTranslateService:
    """OpenAI 兼容接口：一个请求完成"翻译 + 摘要压缩"；失败自动降级 Google。"""

    def __init__(self, cfg: LLMConfig, api_key: str, proxy: str = "") -> None:
        self.cfg = cfg
        self.api_key = api_key
        self._fallback = GoogleTranslateService(proxy)
        self._proxy = proxy or None

    async def translate_title(self, title: str) -> str:
        try:
            return await self._chat(
                "把下面的英文新闻标题翻译成简体中文，只输出译文，不要解释、不要保留原文：\n\n" + title
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 翻译标题失败，降级 Google: %s", exc)
            return await self._fallback.translate_title(title)

    async def translate_summary(self, summary: str) -> str:
        try:
            prompt = (
                "把下面的英文新闻摘要翻译成简体中文，并压缩为不超过 400 字的一段流畅中文，"
                "保留关键事实，不要分点、不要解释、不要保留原文：\n\n" + summary[:4000]
            )
            return await self._chat(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 翻译摘要失败，降级 Google: %s", exc)
            return await self._fallback.translate_summary(summary)

    async def _chat(self, prompt: str) -> str:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=60, proxy=self._proxy) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def build_translator(provider: str, llm_cfg: LLMConfig, api_key: str, proxy: str = "") -> Translator:
    if provider == "none":
        return NoneTranslator()
    if provider == "llm":
        if not llm_cfg.enabled or not api_key:
            logger.warning("请求使用 LLM 翻译但未启用或缺少 LLM_API_KEY，降级 Google")
            return GoogleTranslateService(proxy)
        return LLMTranslateService(llm_cfg, api_key, proxy)
    # google / auto 兜底
    return GoogleTranslateService(proxy)
