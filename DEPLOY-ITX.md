# ITX（Ubuntu + 宝塔）部署指南

环境已核实：ITX = 192.168.5.33，Ubuntu 22.04，Python 3.10.12，时区 Asia/Shanghai；
NAS 挂载于 `/mnt/nas`；Bridge 同机 `127.0.0.1:9100`；DeepSeek API 直连可达；
Discord 需走 PC 代理 `http://192.168.5.107:7890`（PC 需开机并允许局域网代理）。

## 1. 拉代码

```bash
mkdir -p /www/wwwroot && cd /www/wwwroot
git -c http.proxy=http://192.168.5.107:7890 clone \
  https://github.com/uwings/discord_rss_bot.git rssbot
cd rssbot
```

> 这台机器上 E 盘项目也挂在 `/mnt/pc/rssbot`，密钥包已生成在 `data/itx-deploy/.env`（不进 git）。

## 2. 虚拟环境与依赖

宝塔软件商店安装「Python 项目管理器」（或直接用系统 Python 3.10，依赖里已带 `tomli` 回退）：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. 放配置与密钥

```bash
cp config.itx.example.toml config.local.toml   # ITX 路径/代理覆盖（已 gitignore）
cp /mnt/pc/rssbot/data/itx-deploy/.env .env    # Webhook/Bot Token/DeepSeek key/Bridge token
```

`config.local.toml` 只覆盖 Linux 下不同的部分：代理、Bridge 本地地址、NAS 归档路径、频道 ID。
检查 `.env`：`DISCORD_WEBHOOK_URL`、`DISCORD_BOT_TOKEN`、`LLM_API_KEY`、`BRIDGE_TOKEN`、`DISCORD_CHANNEL_ID`。

## 4. 验证（先别起常驻）

```bash
.venv/bin/python -m rssbot doctor
.venv/bin/python -m rssbot ask "DeepSeek 在推理优化上做过什么"
.venv/bin/python -m rssbot digest --date 2026-10-20 --dry-run
```

全绿后可手动发一份验证排版（当天未发过时）：

```bash
.venv/bin/python -m rssbot digest
```

## 5. 邀请 Bot 进频道（启用 /ask 必需）

浏览器打开（client_id 即旧应用）：

```
https://discord.com/oauth2/authorize?client_id=1330172305304715338&scope=bot+applications.commands
```

选择服务器授权。启动后全局 slash 命令同步最长约 1 小时；想立刻生效，在 `.env` 加
`DISCORD_GUILD_ID=<服务器ID>`。

> ⚠️ 这个 Bot Token 2025 年曾进过公开 git 历史，建议找时间在 Developer Portal Reset 一次并同步更新 `.env`。

## 6. 常驻守护（二选一）

### 方案 A：宝塔「Supervisor 管理器」插件（推荐，图形化）

软件商店装「Supervisor管理器」→ 添加守护进程：

- 名称：`rssbot`
- 运行目录：`/www/wwwroot/rssbot`
- 启动命令：`/www/wwwroot/rssbot/.venv/bin/python -m rssbot`

启动后每天 20:15 自动发简报，频道内可用 `/ask`、`/briefing`。

### 方案 B：systemd

`/etc/systemd/system/rssbot.service`：

```ini
[Unit]
Description=rssbot 3.0 (KC QA + daily briefing)
After=network-online.target

[Service]
WorkingDirectory=/www/wwwroot/rssbot
ExecStart=/www/wwwroot/rssbot/.venv/bin/python -m rssbot
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now rssbot
journalctl -u rssbot -f          # 看日志；应用内日志在 data/bot.log
```

## 运维速查

| 操作 | 命令 |
|---|---|
| 体检 | `.venv/bin/python -m rssbot doctor` |
| 手动问共脑 | `.venv/bin/python -m rssbot ask "问题"` |
| 补某天简报 | `.venv/bin/python -m rssbot digest --date 2026-10-20 --force` |
| 只看不发 | 加 `--dry-run` |
| 更新代码 | `git pull && .venv/bin/pip install -r requirements.txt && systemctl restart rssbot` |

注意：Discord 出口依赖 PC 代理；PC 不在线时 `/ask` 和推送会失败（Bridge/DeepSeek/归档不受影响，到点恢复后可用 `digest --force` 补发）。
