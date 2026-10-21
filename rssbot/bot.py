"""Discord 问答 Bot：/ask 共脑问答、/briefing 手动简报，外加每日定时简报。

只使用 slash commands（app_commands），不需要 MESSAGE CONTENT INTENT。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, time as dtime

import discord
from discord import app_commands
from discord.ext import tasks

from .bridge import KnowledgeBase
from .briefing import build_briefing, deliver, render_embeds
from .editor import Editor
from .models import truncate

logger = logging.getLogger(__name__)

MAX_REPLY = 1900


def _chunk(text: str, limit: int = MAX_REPLY) -> list[str]:
    """按 2000 字符限制切分长回复，尽量在换行处断开。"""
    parts = []
    rest = text.strip()
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind("。", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


async def run_digest_loop(cfg) -> None:
    """无 Bot Token 时的纯定时简报模式：每分钟检查，到点经 Webhook 发当日简报。"""
    if not cfg.webhook_url:
        raise RuntimeError("纯简报模式需要 DISCORD_WEBHOOK_URL；否则请配置 DISCORD_BOT_TOKEN")
    hh, mm = (int(x) for x in cfg.briefing.time.split(":"))
    logger.info("纯定时简报模式启动：每天 %02d:%02d（Webhook）", hh, mm)
    while True:
        now = datetime.now()
        if now.hour == hh and now.minute == mm:
            day = now.date()
            if day.strftime("%Y-%m-%d") not in _sent_dates(cfg):
                try:
                    briefing = await build_briefing(cfg, day)
                    if await deliver(cfg, briefing):
                        logger.info("定时简报已发送（%d 条）", len(briefing.watch))
                except FileNotFoundError:
                    logger.info("今天无发布归档，跳过")
                except Exception:  # noqa: BLE001
                    logger.exception("定时简报失败")
        await asyncio.sleep(60)


async def run_bot(cfg) -> None:
    if not cfg.bot_token:
        logger.warning("未配置 DISCORD_BOT_TOKEN，/ask 问答不可用；仅运行定时简报")
        await run_digest_loop(cfg)
        return

    kb = KnowledgeBase(cfg.bridge, cfg.bridge_token)
    editor = Editor(cfg.llm, cfg.llm_api_key) if cfg.llm_ready else None
    guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    guild = discord.Object(id=int(guild_id)) if guild_id.isdigit() else None

    intents = discord.Intents.default()
    client = discord.Client(intents=intents, proxy=cfg.proxy or None)
    tree = app_commands.CommandTree(client)

    allowed_ids = cfg.bot.allowed_channel_ids

    def allowed(interaction: discord.Interaction) -> bool:
        return not allowed_ids or interaction.channel_id in allowed_ids

    @tree.command(name="ask", description="问共脑知识库（KC）：基于已沉淀的新闻与观点回答")
    @app_commands.describe(question="你想问的问题")
    async def ask_cmd(interaction: discord.Interaction, question: str) -> None:
        if not allowed(interaction):
            await interaction.response.send_message("这个频道不能用我，请到指定频道提问。", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        hits = await kb.query(question, top_k=cfg.bridge.top_k)
        if not hits:
            await interaction.followup.send("共脑库没有召回到相关记录（Bridge 离线或主题未入库）。")
            return
        if editor:
            reply = await editor.answer(question, hits)
        else:
            reply = "（未配置 LLM，仅展示召回词条）\n\n" + "\n\n".join(
                f"**{h.date or '日期未知'}**（{h.score:.2f}）\n{truncate(h.snippet, 500)}" for h in hits[:4]
            )
        first = True
        for chunk in _chunk(reply):
            if first:
                await interaction.followup.send(chunk, suppress_embeds=True)
                first = False
            else:
                await interaction.channel.send(chunk, suppress_embeds=True)

    @tree.command(name="briefing", description="生成某一天的 AI 上班族简报（默认今天）")
    @app_commands.describe(day="日期 YYYY-MM-DD（默认今天）", force="今天发过也重发")
    async def briefing_cmd(
        interaction: discord.Interaction, day: str | None = None, force: bool = False
    ) -> None:
        if not allowed(interaction):
            await interaction.response.send_message("这个频道不能用我。", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            target = datetime.strptime(day, "%Y-%m-%d").date() if day else date.today()
        except ValueError:
            await interaction.followup.send("日期格式不对，应为 YYYY-MM-DD")
            return
        try:
            briefing = await build_briefing(cfg, target)
        except FileNotFoundError as exc:
            await interaction.followup.send(str(exc))
            return
        embeds = [discord.Embed.from_dict(e) for e in render_embeds(briefing)]
        if not force:
            sent_dates = _sent_dates(cfg)
            if briefing.day in sent_dates:
                await interaction.followup.send(f"{briefing.day} 的简报已经发过了，加 force=True 可重发。")
                return
        await interaction.followup.send(embeds=embeds[:10])
        _mark_sent(cfg, briefing)

    hh, mm = (int(x) for x in cfg.briefing.time.split(":"))

    @tasks.loop(time=dtime(hour=hh, minute=mm))
    async def daily_briefing() -> None:
        try:
            briefing = await build_briefing(cfg, date.today())
        except FileNotFoundError:
            logger.info("今天没有发布归档，跳过定时简报")
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("定时简报生成失败: %s", exc)
            return

        if briefing.day in _sent_dates(cfg):
            logger.info("今日简报已发送，跳过")
            return

        # 优先 Webhook（digest 通道，带历史记录）；没有 webhook 时用 Bot 直接发频道
        if cfg.webhook_url:
            try:
                if await deliver(cfg, briefing):
                    logger.info("定时简报已通过 Webhook 发送")
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Webhook 发送失败，改用 Bot 频道: %s", exc)

        channel_id = cfg.bot.channel_id or (next(iter(allowed_ids)) if allowed_ids else 0)
        channel = client.get_channel(channel_id)
        if channel is None:
            logger.error("找不到配置的频道 %s，定时简报未发送", channel_id)
            return
        embeds = [discord.Embed.from_dict(e) for e in render_embeds(briefing)]
        await channel.send(embeds=embeds[:10])
        _mark_sent(cfg, briefing)
        logger.info("定时简报已通过 Bot 发送")

    @daily_briefing.before_loop
    async def _before() -> None:
        await client.wait_until_ready()

    @client.event
    async def on_ready() -> None:
        logger.info("Bot 登录：%s", client.user)
        if guild:
            tree.copy_global_to(guild=guild)
            synced = await tree.sync(guild=guild)
        else:
            synced = await tree.sync()
        logger.info("已同步 %d 个 slash 命令（%s）", len(synced), "测试服务器即时同步" if guild else "全局，最多等 1 小时")
        if not daily_briefing.is_running():
            daily_briefing.start()
            logger.info("定时简报：每天 %s", cfg.briefing.time)

    async with client:
        await client.start(cfg.bot_token)


def _sent_dates(cfg) -> set[str]:
    import json

    try:
        with open(cfg.digest_history_path, encoding="utf-8") as f:
            return set(json.load(f).get("sent_dates", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _mark_sent(cfg, briefing) -> None:
    import json

    path = cfg.digest_history_path
    try:
        with open(path, encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        history = {}
    sent = set(history.get("sent_dates", []))
    sent.add(briefing.day)
    history["sent_dates"] = sorted(sent)
    history.setdefault("items", {})[briefing.day] = [e.item.url for e in briefing.watch]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
