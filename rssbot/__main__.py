"""命令行入口。

用法：
  python -m rssbot                常驻运行，每 N 分钟一轮
  python -m rssbot --once         跑一轮后退出（适合任务计划程序 / cron）
  python -m rssbot --dry-run      试跑：完整流程但不推送
  python -m rssbot --catch-up     首次运行也推送历史窗口内的文章
  python -m rssbot doctor         检查所有订阅源是否可访问、可解析
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from logging.handlers import RotatingFileHandler

from . import __version__
from .config import load_config
from .feeds import build_client, fetch_feed
from .pipeline import run_once


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI 新闻 RSS Bot")
    parser.add_argument("--once", action="store_true", help="只运行一轮后退出")
    parser.add_argument("--dry-run", action="store_true", help="试跑：抓取/翻译/去重照常，但不推送 Discord")
    parser.add_argument("--catch-up", action="store_true", help="首次运行（历史为空）也推送窗口内文章")
    parser.add_argument("--config", default=None, help="指定 config.toml 路径")
    parser.add_argument("command", nargs="?", choices=["doctor"], help="doctor: 检查所有订阅源健康状况")
    parser.add_argument("--version", action="version", version=f"rssbot {__version__}")
    return parser.parse_args()


async def run_loop(cfg, *, dry_run: bool, catch_up: bool) -> None:
    while True:
        try:
            await run_once(cfg, dry_run=dry_run, catch_up=catch_up)
        except Exception as exc:  # noqa: BLE001 - 常驻进程不能因单轮异常退出
            logging.getLogger(__name__).exception("本轮运行异常: %s", exc)

        # 间隔加 ±10% 抖动，避免整点打点
        base = cfg.poll.interval_minutes * 60
        delay = base + random.uniform(-0.1 * base, 0.1 * base)
        logging.getLogger(__name__).info("等待 %.0f 分钟后进入下一轮…", delay / 60)
        await asyncio.sleep(delay)


async def run_doctor(cfg) -> int:
    logger = logging.getLogger(__name__)
    client = build_client(cfg.poll.request_timeout_seconds, cfg.proxy)
    ok, failed = 0, 0
    try:
        for feed in cfg.feeds:
            try:
                articles = await fetch_feed(client, feed)
                newest = max((a.published for a in articles if a.published), default=None)
                newest_str = newest.strftime("%Y-%m-%d") if newest else "无日期"
                print(f"  ✅ {feed.name:<22} {len(articles):>3} 篇  最新: {newest_str}")
                ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  ❌ {feed.name:<22} {type(exc).__name__}: {str(exc)[:80]}")
                logger.debug("doctor 失败详情", exc_info=exc)
                failed += 1
    finally:
        await client.aclose()

    print(f"\n结果：{ok} 个正常，{failed} 个失败")
    print(f"翻译引擎: {cfg.effective_provider} | Webhook: {'已配置' if cfg.webhook_url else '未配置'} | 代理: {cfg.proxy or '无'}")
    return 0 if failed == 0 else 1


def main() -> int:
    # Windows 控制台默认 GBK，统一改为 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    setup_logging(cfg.log_path)
    logger = logging.getLogger(__name__)
    logger.info("rssbot %s 启动", __version__)

    try:
        if args.command == "doctor":
            return asyncio.run(run_doctor(cfg))
        if args.once or args.dry_run:
            asyncio.run(run_once(cfg, dry_run=args.dry_run, catch_up=args.catch_up))
            return 0
        asyncio.run(run_loop(cfg, dry_run=False, catch_up=args.catch_up))
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
