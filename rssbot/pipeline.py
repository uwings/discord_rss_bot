"""主编排：拉取 → 时间窗过滤 → 去重 → 翻译 → 推送 → 记录。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .config import AppConfig
from .enrich import enrich_summary
from .feeds import build_client, fetch_all
from .history import History
from .models import Article, has_chinese, utc_now
from .notifier.discord import DiscordWebhookNotifier
from .translate import Translator, build_translator

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    sent: int = 0
    skipped_history: int = 0
    skipped_old: int = 0
    skipped_no_date: int = 0
    errors: dict[str, str] | None = None

    def summary(self) -> str:
        return (
            f"抓取 {self.fetched} 篇 | 推送 {self.sent} | 去重跳过 {self.skipped_history} | "
            f"超窗跳过 {self.skipped_old} | 无日期 {self.skipped_no_date} | "
            f"失败源 {len(self.errors or {})} 个"
        )


def _needs_translation(article: Article) -> bool:
    if article.lang.lower().startswith("zh"):
        return False
    return not has_chinese(article.title)


async def _translate_article(article: Article, translator: Translator) -> None:
    try:
        title_zh = await translator.translate_title(article.title)
        if title_zh and title_zh != article.title:
            article.title_zh = title_zh
        if article.raw_summary:
            summary_zh = await translator.translate_summary(article.raw_summary)
            if summary_zh:
                article.summary_zh = summary_zh
        article.translated = bool(article.title_zh or article.summary_zh)
    except Exception as exc:  # noqa: BLE001
        logger.warning("翻译失败，使用原文 [%s]: %s", article.title[:60], exc)
        article.translated = False


async def run_once(
    cfg: AppConfig,
    *,
    dry_run: bool = False,
    catch_up: bool = False,
) -> RunStats:
    stats = RunStats(errors={})
    history = History(cfg.history_path).load()

    translator = build_translator(cfg.effective_provider, cfg.llm, cfg.llm_api_key, cfg.proxy)
    if cfg.effective_provider != "none":
        logger.info("翻译引擎: %s", cfg.effective_provider)

    notifier = None
    if not dry_run:
        if not cfg.webhook_url:
            raise RuntimeError("未配置 DISCORD_WEBHOOK_URL（或使用 --dry-run 试运行）")
        client = build_client(cfg.poll.request_timeout_seconds, cfg.proxy)
        notifier = DiscordWebhookNotifier(cfg.webhook_url, client)
    else:
        client = build_client(cfg.poll.request_timeout_seconds, cfg.proxy)

    try:
        articles, stats.errors = await fetch_all(client, cfg.feeds)
        stats.fetched = len(articles)

        # 按发布时间升序（无日期的排最后），保证频道里时间线正常
        articles.sort(key=lambda a: a.published or utc_now().replace(year=9999))

        # 首次启动：历史为空时默认只建档不推送，防止频道被历史文章刷屏
        bootstrap = len(history) == 0 and cfg.poll.bootstrap == "mark" and not catch_up

        if bootstrap:
            logger.warning("历史为空且未指定 --catch-up：本轮只建档不推送（共 %d 篇）", len(articles))

        cutoff = utc_now().timestamp() - cfg.poll.max_age_hours * 3600
        for article in articles:
            if article.key in history:
                stats.skipped_history += 1
                continue

            if article.published is None:
                stats.skipped_no_date += 1
                logger.debug("无发布日期，跳过: %s", article.title[:60])
                continue
            if article.published.timestamp() < cutoff:
                stats.skipped_old += 1
                continue

            if bootstrap:
                history.mark(article.key, title=article.title, link=article.link, source=article.source)
                continue

            # feed 中没有摘要时（如 Hugging Face），回源文章页提取导语
            if cfg.poll.enrich_summaries and not article.raw_summary:
                await enrich_summary(client, article)

            if cfg.effective_provider != "none" and _needs_translation(article):
                await _translate_article(article, translator)

            if dry_run:
                print("-" * 70)
                print(f"[{article.source}] {article.published:%Y-%m-%d %H:%M UTC}")
                print(f"标题: {article.title}")
                if article.title_zh:
                    print(f"译文: {article.title_zh}")
                if article.summary_zh:
                    print(f"摘要: {article.summary_zh[:200]}")
                print(f"链接: {article.link}")
                stats.sent += 1
                history.mark(article.key, title=article.title, link=article.link, source=article.source)
                continue

            try:
                await notifier.send(article)
                logger.info("已推送 [%s] %s", article.source, article.display_title[:60])
                stats.sent += 1
                history.mark(article.key, title=article.title, link=article.link, source=article.source)
                history.save()  # 每发一篇即落盘，崩溃后不重复推送
                await asyncio.sleep(1)  # 礼貌限速，避开 webhook 频控
            except Exception as exc:  # noqa: BLE001
                logger.error("推送失败 [%s]: %s", article.title[:60], exc)

        history.prune(cfg.poll.retention_days)
        history.save()
    finally:
        await client.aclose()

    logger.info("本轮结束：%s", stats.summary())
    return stats
