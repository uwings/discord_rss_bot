# AI 上班族简报 Bot（rssbot 3.0）

接在 **AGI Force 新闻管线**与 **KC 共脑知识库**之后的**深度编辑层**，住在 Discord：

- 📰 **每日 20:15 一份选题编辑简报**：消费 AGI Force 当天已筛选的发布归档，用固定的编辑品味（拆解者非惊叹者、上班族视角、反常识选题）二次编辑成「值得关注 + 写作灵感 + 观察线」三张卡片。
- ❓ **`/ask` 共脑问答**：随时问 KC 知识库（经内网 Bridge 语义检索），回答只基于已沉淀词条、带日期来源，不编造。
- 旧版 2.0 的 14 源 RSS 实时推送保留为 `rss` 子命令（与 AGI Force 重复，默认关闭）。

## 数据流

```
AGI Force 采集（11源）→ GLM 7分筛选 → TG/飞书
                         ↓ publish_YYYYMMDD_*.json（NAS 归档）
              rssbot digest：合并早晚两班 → KC 历史召回 → DeepSeek 二次编辑
                         ↓
              Discord：值得关注 / 写作灵感 / 观察线
Discord /ask → Bridge(192.168.5.33:9100) → Qdrant 共脑库 → DeepSeek 归纳回答
```

零新增采集：事实层全部来自 AGI Force 归档（已是中文精编），LLM 只做视角转换。

## 命令

```bash
python -m rssbot                     # serve：Bot 问答 + 定时简报（无 Bot Token 时退化为纯定时简报）
python -m rssbot ask "DeepSeek 在推理优化上做过什么"
python -m rssbot digest              # 立即生成今日简报
python -m rssbot digest --date 2026-10-20 --dry-run
python -m rssbot digest --force      # 重发（默认当天已发会跳过）
python -m rssbot doctor              # 体检：Bridge / 归档 / LLM / Discord
python -m rssbot rss --once          # 旧 2.0 RSS 管线
```

## 配置

`config.toml`：简报时间与条数、Bridge 地址、NAS 归档路径（默认 `Z:/jovi工作目录/briefing-archive`）、LLM 端点（默认 DeepSeek）。

`.env`：密钥。本机已装 Hermes 时，`LLM_API_KEY`（读 hermes 的 `DEEPSEEK_API_KEY`）和 `BRIDGE_TOKEN`（读 local-data-bridge 配置）都会自动兜底，只需配 Webhook。启用问答再配 Bot Token，见 `.env.example`。

## 启用 Discord 问答 Bot（可选）

1. [Developer Portal](https://discord.com/developers/applications) → New Application → **Bot** → Reset Token，填入 `.env` 的 `DISCORD_BOT_TOKEN`
2. 频道右键复制频道 ID，填入 `DISCORD_CHANNEL_ID`
3. 用浏览器打开邀请链接（替换 `CLIENT_ID`，勾选 `bot` 与 `applications.commands` 两个 scope）：
   `https://discord.com/developers/applications/CLIENT_ID/oauth2/url-generator`
4. `python -m rssbot` 启动；把 `DISCORD_GUILD_ID` 填上可让 slash 命令即时同步

启动后频道里出现 `/ask`、`/briefing` 两个命令。

## 部署（Windows 任务计划程序）

触发器「登录时」启动程序：`.venv\Scripts\python.exe`，参数 `-m rssbot`，起始位置项目根目录。
纯定时简报也可用每 5 分钟跑 `python -m rssbot` 的方式（已发当天会自动跳过），但推荐常驻。

## 编辑品味（写在 editor.py 的 system prompt）

拆解者非惊叹者；回答真实方向/利益格局/产品问题/市场变化；Agent 的记忆、上下文、可控性优先；
反常识与静默翻车优先于发布会通稿；机器人/具身/自动驾驶/车企稿不选；事实只许来自当天归档，禁止标题嫁接。
