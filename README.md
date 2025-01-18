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
- HTTP代理（可选）

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
```
DISCORD_CHANNEL_ID=你的频道ID
```

## 使用方法

1. 运行机器人：
```bash
python discord_rss_bot.py
```

2. 机器人会自动：
   - 连接到Discord
   - 获取RSS源的最新文章
   - 翻译内容（如果是英文）
   - 推送到指定的Discord频道

## 注意事项

- 请确保Discord Bot Token的安全性
- 如果需要使用代理，请在代码中配置代理地址
- 建议使用虚拟环境运行项目 