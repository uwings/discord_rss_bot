# Discord RSS Bot

一个用于获取AI相关新闻并推送到Discord频道的RSS机器人。

## 功能特点

- 支持多个RSS源
- 自动翻译英文内容为中文
- 去重功能，避免重复推送
- 支持文章时效性检查（仅推送72小时内的文章）
- 定期自动获取更新（每30分钟）

## RSS源列表

- OpenAI Blog
- Google AI Blog
- NVIDIA AI Blog
- NVIDIA Developer Blog
- MIT AI News
- DeepMind Blog
- Stability AI Blog
- Hugging Face Blog
- TechCrunch AI
- GeekPark
- 量子位

## 环境要求

- Python 3.6+
- Discord Bot Token
- HTTP代理

## 安装

1. 克隆仓库：
```bash
git clone https://github.com/uwings/discord_rss_bot.git
cd discord_rss_bot
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 创建.env文件并配置：
```bash
# Discord配置
DISCORD_CHANNEL_ID=你的频道ID
DISCORD_TOKEN=你的Bot Token
```

## 配置说明

1. Discord Bot Token获取：
   - 访问 [Discord Developer Portal](https://discord.com/developers/applications)
   - 创建新应用或选择现有应用
   - 在Bot设置页面获取Token

2. Discord Channel ID获取：
   - 在Discord中开启开发者模式
   - 右键点击目标频道
   - 选择"复制ID"

3. 代理设置：
   - 研发环境：127.0.0.1:7890
   - 线上环境：192.168.5.107:7890
   - 通过命令行参数 `--env` 自动切换环境

## 使用方法

1. 运行机器人：

研发环境（默认）：
```bash
python run.py
# 或
python run.py --env dev
```

生产环境：
```bash
python run.py --env prod
```

2. 机器人会自动：
   - 连接到Discord
   - 获取RSS源的最新文章
   - 翻译内容（如果是英文）
   - 推送到指定的Discord频道

## 注意事项

- 请确保Discord Bot Token的安全性，不要将其提交到代码仓库
- 使用命令行参数 `--env` 来切换环境，无需手动修改配置
- 建议使用虚拟环境运行项目 