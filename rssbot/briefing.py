"""每日选题编辑简报编排：归档 → KC 历史召回 → LLM 二次编辑 → Embed → 投递。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .archive import NewsItem, SOURCE_LABELS, load_publish_archive
from .bridge import KnowledgeBase
from .config import AppConfig
from .editor import Editor
from .feeds import build_client
from .models import truncate
from .notifier.discord import EMBED_COLOR, DiscordWebhookNotifier

logger = logging.getLogger(__name__)


@dataclass
class WatchEntry:
    item: NewsItem
    angle: str = ""


@dataclass
class Inspiration:
    title: str
    angle: str
    item: NewsItem | None = None


@dataclass
class Briefing:
    day: str
    watch: list[WatchEntry] = field(default_factory=list)
    inspirations: list[Inspiration] = field(default_factory=list)
    thread: str = ""
    degraded: bool = False  # LLM 不可用时的原样降级


def _load_digest_history(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_digest_history(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


async def _history_recall(kb: KnowledgeBase, items: list[NewsItem]) -> list:
    """从当天条目中取代表性标题 + 通用主题，向 KC 召回历史叙事。"""
    queries = ["2026 AI 办公 Agent 大模型 趋势 上班族"]
    # 优先用 KOL/官方/创投源的条目标题做精确主题召回
    priority = [it for it in items if any(s in it.source_ids for s in ("S10", "S11", "S1"))]
    for it in (priority + items)[:6]:
        if len(queries) >= 3:
            break
        queries.append(it.title[:30])

    seen: set[str] = set()
    hits = []
    for q in queries:
        for h in await kb.query(q, top_k=4):
            key = h.canonical_id or h.snippet[:60]
            if key not in seen:
                seen.add(key)
                hits.append(h)
    return hits[:8]


def _fallback_briefing(day: str, items: list[NewsItem], n: int) -> Briefing:
    return Briefing(
        day=day,
        watch=[WatchEntry(item=it) for it in items[:n]],
        degraded=True,
    )


async def build_briefing(cfg: AppConfig, day: date) -> Briefing:
    day_str = f"{day:%Y-%m-%d}"
    items = load_publish_archive(cfg.archive, day)

    history_hits = []
    if cfg.bridge_token:
        kb = KnowledgeBase(cfg.bridge, cfg.bridge_token)
        history_hits = await _history_recall(kb, items)
        logger.info("KC 历史召回 %d 条词条", len(history_hits))

    if not cfg.llm_ready:
        logger.warning("未配置 LLM_API_KEY，简报降级为原始条目 Top %d", cfg.briefing.watch_n)
        return _fallback_briefing(day_str, items, cfg.briefing.watch_n)

    editor = Editor(cfg.llm, cfg.llm_api_key)
    result = await editor.compose_briefing(
        day_str, items, history_hits, cfg.briefing.watch_n, cfg.briefing.inspiration_n
    )
    if not result:
        logger.warning("LLM 编辑失败，简报降级")
        return _fallback_briefing(day_str, items, cfg.briefing.watch_n)

    briefing = Briefing(day=day_str, thread=(result.get("thread") or "").strip())

    for row in (result.get("watch") or [])[: cfg.briefing.watch_n]:
        idx = row.get("index")
        if isinstance(idx, int) and 0 <= idx < len(items):
            briefing.watch.append(WatchEntry(item=items[idx], angle=(row.get("angle") or "").strip()))

    for row in (result.get("inspirations") or [])[: cfg.briefing.inspiration_n]:
        idx = row.get("index")
        item = items[idx] if isinstance(idx, int) and 0 <= idx < len(items) else None
        briefing.inspirations.append(
            Inspiration(
                title=(row.get("title") or "").strip() or (item.title if item else "无题"),
                angle=(row.get("angle") or "").strip(),
                item=item,
            )
        )

    # LLM 抽风一条没选出来时也降级，宁可不发空壳
    if not briefing.watch:
        logger.warning("LLM 返回无可选条目，简报降级")
        return _fallback_briefing(day_str, items, cfg.briefing.watch_n)
    return briefing


def render_embeds(briefing: Briefing) -> list[dict]:
    lines = []
    for i, e in enumerate(briefing.watch, 1):
        src = e.item.source_label(SOURCE_LABELS)
        title = truncate(e.item.title, 120)
        if e.angle:
            lines.append(f"**{i}. [{src}] [{title}]({e.item.url})**\n{truncate(e.angle, 160)}")
        else:
            # 降级模式：标题+原摘要
            lines.append(
                f"**{i}. [{src}] [{title}]({e.item.url})**\n{truncate(e.item.summary, 160)}"
            )

    note = "\n\n_⚠️ LLM 暂不可用，本期为原始精选直送（无上班族点评）_" if briefing.degraded else ""
    embeds = [
        {
            "author": {"name": "AGI Force × 共脑编辑"},
            "title": f"📰 AI 上班族简报 · {briefing.day}",
            "description": truncate("\n\n".join(lines), 3800) + note,
            "color": EMBED_COLOR,
        }
    ]

    if briefing.inspirations:
        fields = []
        for ins in briefing.inspirations:
            value = truncate(ins.angle, 900)
            if ins.item:
                value += f"\n[原始新闻]({ins.item.url})"
            fields.append({"name": f"✍️ {truncate(ins.title, 200)}", "value": value, "inline": False})
        embeds.append({"title": "✍️ 写作灵感（喂选题中心）", "fields": fields[:5], "color": EMBED_COLOR})

    if briefing.thread:
        embeds.append(
            {
                "title": "💡 观察线（KC 历史叙事）",
                "description": truncate(briefing.thread, 1800),
                "color": EMBED_COLOR,
            }
        )
    return embeds


async def deliver(cfg: AppConfig, briefing: Briefing, *, force: bool = False) -> bool:
    """投递简报（Webhook）并记录历史。返回是否实际发送。"""
    hist_path = cfg.digest_history_path
    history = _load_digest_history(hist_path)
    if briefing.day in history.get("sent_dates", []) and not force:
        logger.info("简报 %s 已发送过，跳过（--force 可重发）", briefing.day)
        return False
    if not cfg.webhook_url:
        raise RuntimeError("未配置 DISCORD_WEBHOOK_URL")

    client = build_client(cfg.poll.request_timeout_seconds, cfg.proxy)
    try:
        notifier = DiscordWebhookNotifier(cfg.webhook_url, client)
        await notifier.send_embeds(render_embeds(briefing))
    finally:
        await client.aclose()

    sent = set(history.get("sent_dates", []))
    sent.add(briefing.day)
    history["sent_dates"] = sorted(sent)
    history.setdefault("items", {})[briefing.day] = [e.item.url for e in briefing.watch]
    _save_digest_history(hist_path, history)
    return True
