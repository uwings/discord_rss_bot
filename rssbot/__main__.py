"""命令行入口。

  python -m rssbot                      serve：Discord 问答 Bot + 定时简报
  python -m rssbot ask "问题"           直接问共脑知识库（CLI）
  python -m rssbot digest               生成今日简报（--date YYYY-MM-DD / --dry-run / --force）
  python -m rssbot doctor               体检：Bridge / 归档 / LLM / Discord
  python -m rssbot rss [--once...]      旧 2.0 的 RSS 实时推送管线（默认已停用）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
from logging.handlers import RotatingFileHandler

from . import __version__
from .archive import SOURCE_LABELS, load_publish_archive
from .bot import run_bot
from .bridge import KnowledgeBase
from .briefing import build_briefing, deliver, render_embeds
from .config import load_config
from .editor import Editor
from .pipeline import run_once

logger = logging.getLogger(__name__)


def setup_logging(log_path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)


# ---------- doctor ----------

async def run_doctor(cfg) -> int:
    failures = 0

    # 1) Bridge
    kb = KnowledgeBase(cfg.bridge, cfg.bridge_token)
    ok = await kb.health() if cfg.bridge_token else False
    print(f"  {'✅' if ok else '❌'} Bridge 共脑  {cfg.bridge.base_url} ({'有 token' if cfg.bridge_token else '无 token'})")
    failures += not ok
    if ok:
        hits = await kb.query("AI", top_k=1)
        print(f"     向量检索：召回 {len(hits)} 条（样例日期 {hits[0].date or '未知'}）")

    # 2) 发布归档
    try:
        items = load_publish_archive(cfg.archive, date.today())
        print(f"  ✅ 发布归档：今日 {len(items)} 条去重条目")
    except FileNotFoundError as exc:
        print(f"  ⚠️  发布归档：{exc}")

    # 3) LLM
    if cfg.llm_ready:
        editor = Editor(cfg.llm, cfg.llm_api_key)
        reply = await editor._chat("你是测试助手", "只回复 OK", max_tokens=10)
        ok = bool(reply)
        print(f"  {'✅' if ok else '❌'} LLM  {cfg.llm.base_url} / {cfg.llm.model}")
        failures += not ok
    else:
        print("  ⚠️  LLM：未配置 LLM_API_KEY（简报将降级为原始精选）")

    # 4) Discord
    print(f"  {'✅' if cfg.webhook_url else '❌'} Discord Webhook  {'已配置' if cfg.webhook_url else '未配置'}")
    print(f"  {'✅' if cfg.bot_token else '⬜'} Discord Bot Token  {'已配置（slash 问答可用）' if cfg.bot_token else '未配置（仅有定时简报）'}")
    print(f"  {'✅' if cfg.bot.channel_id else '⚠️ '} 响应频道限制  {cfg.bot.channel_id or '未限制'}")

    # 5) 旧 RSS
    print(f"  ℹ️  旧 RSS 管线：{'启用' if cfg.legacy_rss.enabled else '停用（与 AGI Force 重复，用 rss 子命令手动运行）'}")
    print(f"\n结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


# ---------- ask ----------

async def run_ask(cfg, question: str) -> int:
    if not cfg.bridge_token:
        print("未配置 Bridge token，无法查询共脑库")
        return 2
    kb = KnowledgeBase(cfg.bridge, cfg.bridge_token)
    hits = await kb.query(question, top_k=cfg.bridge.top_k)
    if not await kb.health() and not hits:
        print(f"Bridge 不可达（{cfg.bridge.base_url}）")
        return 1
    print(f"（召回 {len(hits)} 条词条）\n")
    if not cfg.llm_ready:
        for i, h in enumerate(hits, 1):
            print(f"--- {i}. {h.date or '日期未知'} ({h.score:.2f}) ---")
            print(h.snippet[:600])
        return 0
    editor = Editor(cfg.llm, cfg.llm_api_key)
    print(await editor.answer(question, hits))
    return 0


# ---------- digest ----------

async def run_digest(cfg, day: date, dry_run: bool, force: bool) -> int:
    briefing = await build_briefing(cfg, day)
    print(f"📰 {briefing.day} 简报：值得关注 {len(briefing.watch)} 条 | 写作灵感 {len(briefing.inspirations)} 条 | "
          f"观察线 {'有' if briefing.thread else '无'}{' | 降级模式' if briefing.degraded else ''}")
    for i, e in enumerate(briefing.watch, 1):
        print(f"  {i}. [{e.item.source_label(SOURCE_LABELS)}] {e.item.title[:50]}")
        if e.angle:
            print(f"     → {e.angle}")
    for ins in briefing.inspirations:
        print(f"  ✍️ 《{ins.title}》 {ins.angle[:60]}")
    if briefing.thread:
        print(f"  💡 {briefing.thread[:150]}")

    if dry_run:
        print("\n[dry-run] 未发送")
        return 0

    sent = await deliver(cfg, briefing, force=force)
    print("已推送到 Discord" if sent else "已发送过，跳过（--force 可重发）")
    return 0


# ---------- serve ----------

async def amain(args, cfg) -> int:
    if args.command == "doctor":
        return await run_doctor(cfg)
    if args.command == "ask":
        return await run_ask(cfg, " ".join(args.question))
    if args.command == "digest":
        day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
        return await run_digest(cfg, day, args.dry_run, args.force)
    if args.command == "rss":
        if args.once:
            await run_once(cfg, dry_run=args.dry_run, catch_up=args.catch_up)
            return 0
        return await _legacy_loop(cfg, args.dry_run, args.catch_up)

    # 默认：serve
    await run_bot(cfg)
    return 0


async def _legacy_loop(cfg, dry_run: bool, catch_up: bool) -> None:
    import random

    while True:
        try:
            await run_once(cfg, dry_run=dry_run, catch_up=catch_up)
        except Exception as exc:  # noqa: BLE001
            logger.exception("RSS 轮次异常: %s", exc)
        delay = cfg.poll.interval_minutes * 60
        await asyncio.sleep(delay + random.uniform(-0.1 * delay, 0.1 * delay))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="rssbot 3.0：共脑问答 + 每日选题编辑简报")
    parser.add_argument("--config", default=None, help="指定 config.toml 路径（.env/config.local.toml 跟随同目录）")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="启动 Discord 问答 Bot + 定时简报（默认命令）")

    p_ask = sub.add_parser("ask", help="直接问共脑知识库")
    p_ask.add_argument("question", nargs="+")

    p_dig = sub.add_parser("digest", help="生成并推送每日简报")
    p_dig.add_argument("--date", help="指定日期 YYYY-MM-DD（默认今天）")
    p_dig.add_argument("--dry-run", action="store_true")
    p_dig.add_argument("--force", action="store_true", help="即使今天已发过也重发")

    sub.add_parser("doctor", help="体检")

    p_rss = sub.add_parser("rss", help="旧 2.0 RSS 实时推送管线")
    p_rss.add_argument("--once", action="store_true")
    p_rss.add_argument("--dry-run", action="store_true")
    p_rss.add_argument("--catch-up", action="store_true")

    parser.add_argument("--version", action="version", version=f"rssbot {__version__}")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    setup_logging(cfg.log_path)
    logger.info("rssbot %s 启动（命令: %s）", __version__, args.command or "serve")

    try:
        return asyncio.run(amain(args, cfg))
    except KeyboardInterrupt:
        logger.info("收到中断，退出")
        return 0


if __name__ == "__main__":
    sys.exit(main())
