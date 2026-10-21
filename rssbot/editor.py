"""LLM 编辑层（DeepSeek / 任意 OpenAI 兼容端点）。

两件事：
1. compose_briefing：把 AGI Force 当天已筛选条目二次编辑成「上班族视角简报」
2. answer：只依据 KC 召回词条回答问题（事实溯源，不编造）

品味标准改编自己停用的 ai-morning-briefing skill 与 jovi 在共脑中沉淀的偏好。
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from .archive import NewsItem
from .bridge import KnowledgeHit
from .config import LLMConfig

logger = logging.getLogger(__name__)

EDITOR_SYSTEM = """你是 jovi 的 AI 新闻编辑，读者是中文区 AI 实践者：开发者、产品/运营从业者、创业者、重度 AI 工具用户。

你的编辑品味（必须遵守）：
1. 做拆解者，不做惊叹者。不要"震撼发布""太强了"这类惊叹体，要回答：真实方向、真实利益格局、真实产品问题、真实市场变化。
2. 上班族视角：这条新闻对知识工作者意味着什么？产品现在能不能用、普通人离用上差几步、工作流会怎么变。Agent 的记忆/多轮上下文/可控性/稳定性等真实瓶颈优先。
3. 反常识优先：认知盲区、静默翻车、被宣传掩盖的问题，比发布会通稿有价值。
4. 事实溯源：只能使用给定条目的内容，不允许把 A 条目的事实嫁接到 B 条目，不允许编造条目里没有的数字和事实。
5. 机器人/具身智能/自动驾驶/车企合作/纯融资无产品信息的条目不选。"""

BRIEFING_HUMAN_TMPL = """今天是 {date}，以下是已通过初筛的 AI 新闻条目（标题+摘要已经过编辑）。

{items_block}

以下是共脑知识库中按主题召回的历史背景词条（带日期，仅供串联叙事线，不要当成今天的新闻）：
{history_block}

请输出严格 JSON（不要输出任何其他内容）：
{{
  "watch": [
    {{"index": 条目编号, "angle": "上班族视角一句话，≤60字：真实问题/能不能用上/离普通用户差几步，不要复述摘要"}}
  ],
  "inspirations": [
    {{"index": 条目编号, "title": "反常识的文章标题方向", "angle": "切入角度，≤80字：认知盲区是什么、打算怎么拆解"}}
  ],
  "thread": "一段≤120字的观察线：把今天的事件和历史背景词条串成趋势判断；没有把握就输出空字符串"
}}

要求：watch 选 {watch_n} 条（宁少勿滥，不足可少选）；inspirations 选 {inspiration_n} 条，必须有反常识或可拆解的点；thread 引用历史时要带时间。"""

ANSWER_SYSTEM = """你是 jovi 的「共脑」问答助手。只根据用户提供的知识库词条回答问题：
- 中文回答，分点组织，每个关键事实后用括号标注事件日期。
- 词条里没有的信息，直接说"共脑库里没有相关记录"，绝对不允许用模型自己的知识补全、不允许猜测。
- 多个词条说法不一致时，并列呈现并注明各自日期。
- 回答末尾附一句「来源：共脑知识库 KC」。"""


class Editor:
    def __init__(self, cfg: LLMConfig, api_key: str):
        self.cfg = cfg
        self.api_key = api_key

    async def _chat(self, system: str, user: str, json_mode: bool = False, max_tokens: int = 4000) -> str | None:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        payload: dict = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 调用失败: %s", exc)
            return None

    async def compose_briefing(
        self,
        date_str: str,
        items: list[NewsItem],
        history_hits: list[KnowledgeHit],
        watch_n: int,
        inspiration_n: int,
    ) -> dict | None:
        lines = []
        for i, it in enumerate(items):
            src = "/".join(it.source_ids) if it.source_ids else "S?"
            lines.append(f"[{i}] ({src}) {it.title}\n摘要：{it.summary[:220]}\nURL：{it.url}")
        history_block = "\n".join(
            f"- ({h.date or '日期未知'}) {h.snippet[:220]}" for h in history_hits
        ) or "（无历史召回）"

        user = BRIEFING_HUMAN_TMPL.format(
            date=date_str,
            items_block="\n\n".join(lines),
            history_block=history_block,
            watch_n=watch_n,
            inspiration_n=inspiration_n,
        )
        raw = await self._chat(EDITOR_SYSTEM, user, json_mode=True)
        if not raw:
            return None
        return _parse_json(raw)

    async def answer(self, question: str, hits: list[KnowledgeHit]) -> str:
        if not hits:
            return "共脑库没有召回到相关记录（可能 Bridge 不在线，或该主题尚未入库）。"
        context = "\n\n".join(
            f"词条{i+1}（{h.date or '日期未知'}, 相关度 {h.score:.2f}）：\n{h.snippet[:900]}"
            for i, h in enumerate(hits)
        )
        user = f"问题：{question}\n\n知识库词条：\n{context}"
        reply = await self._chat(ANSWER_SYSTEM, user, max_tokens=1500)
        return reply or "LLM 暂时不可用，无法组织回答（共脑召回本身是成功的）。"


def _parse_json(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 容错：抠第一个 {...} 块
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
