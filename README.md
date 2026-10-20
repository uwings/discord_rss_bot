# AI 新闻 RSS Bot

定时聚合多家 AI 媒体的 RSS 源，将英文内容翻译成中文，以 Embed 卡片推送到 Discord 频道。

## 功能

- **14 个信息源**：OpenAI、Google AI、Google DeepMind、Hugging Face、MIT、TechCrunch、NVIDIA 中文、量子位、极客公园等（全部可在 `config.toml` 中增删，2026-10 实测可用）
- **自动翻译**：默认使用免费 Google 翻译；配置任意 OpenAI 兼容 LLM 后自动升级为大模型翻译 + 摘要
- **去重**：历史记录原子写入，重启不重复推送；链接自动去除 utm 参数
- **时效性**：只推送 72 小时内的文章；首次启动默认只建档不刷屏
- **Discord Webhook**：无需创建 Bot、无需长连接，一条 HTTP 请求即可推送
- **`doctor` 自检**：一键检查所有订阅源的可访问性与解析情况

## 快速开始

### 1. 安装

需要 Python 3.11+。

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置密钥

复制 `.env.example` 为 `.env`，填入 Discord Webhook URL：

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
LLM_API_KEY=
```

**获取 Webhook URL**：Discord 频道 → ⚙️ 编辑频道 → 整合 → Webhook → 新建 Webhook → 复制 URL。

> 网络需要访问 Discord 与 Google 翻译。如需代理，在 `config.toml` 的 `[http] proxy` 填写（如 `http://127.0.0.1:7890`），或设置 `HTTPS_PROXY` 环境变量。

### 3. 自检与试跑

```bash
python -m rssbot doctor            # 检查全部订阅源
python -m rssbot --dry-run --catch-up   # 试跑：抓取+翻译，但不推送
```

### 4. 正式运行

```bash
python -m rssbot --once --catch-up  # 跑一轮（首次会把 72h 内文章都推过去）
python -m rssbot --once            # 之后：只推新文章
python -m rssbot                   # 常驻：每 30 分钟自动一轮
```

再跑一次 `--once` 不会重复推送（去重生效）。

## 部署：Windows 任务计划程序（推荐）

用 `--once` 模式挂系统计划任务，每 30 分钟执行一次，进程崩溃也能在下个周期自愈：

1. 打开「任务计划程序」→ 创建任务
2. 触发器：按计划，每 30 分钟
3. 操作：启动程序
   - 程序：`E:\--gitrepro--\rssbot\.venv\Scripts\python.exe`
   - 参数：`-m rssbot --once`
   - 起始位置：`E:\--gitrepro--\rssbot`

Linux/macOS 用 cron 同理：`*/30 * * * * cd /path/rssbot && .venv/bin/python -m rssbot --once`

## 配置说明（config.toml）

| 配置 | 说明 |
|---|---|
| `poll.interval_minutes` | 常驻模式轮询间隔 |
| `poll.max_age_hours` | 文章时效窗口（默认 72 小时） |
| `poll.bootstrap` | `mark`=首次只建档不推送（默认）；`catch_up`=首次照推 |
| `poll.retention_days` | 去重历史保留天数（默认 14 天） |
| `translation.provider` | `auto` / `google` / `llm` / `none` |
| `llm.*` | OpenAI 兼容端点地址与模型名，key 放 `.env` |
| `[[feeds]]` | 订阅源；`lang = "zh"` 的源跳过翻译 |

运行数据在 `data/`（历史记录与轮转日志），已被 git 忽略。

## 扩展新推送渠道

`rssbot/notifier/` 定义了 `Notifier` 协议（仅一个 `async send(article)` 方法）。
新增飞书 / 企业微信 / Telegram 时，照 `discord.py` 实现一个文件并在 `pipeline.py` 中选择即可。

## 安全说明

- `.env` 包含 Webhook URL，切勿提交（已在 `.gitignore`）。
- Webhook URL 本身即凭证：任何持有者都能向频道发消息，泄露后在 Discord「整合」中删除重建即可。
