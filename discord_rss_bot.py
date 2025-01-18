import discord
import feedparser
import asyncio
import os
import ssl
import html
import re
import json
import time
import argparse
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from translate import Translator
from dotenv import load_dotenv
import hashlib
import sys

def parse_args():
    parser = argparse.ArgumentParser(description='Discord RSS Bot')
    parser.add_argument('--env', type=str, choices=['dev', 'prod'], default='dev',
                      help='运行环境: dev (开发) 或 prod (生产)')
    return parser.parse_args()

# 解析命令行参数
args = parse_args()

# 加载环境变量
load_dotenv()

# 禁用SSL验证
ssl._create_default_https_context = ssl._create_unverified_context

# 根据环境设置代理
PROXY_HOSTS = {
    'dev': '127.0.0.1',
    'prod': '192.168.5.107'
}

proxy_host = PROXY_HOSTS[args.env]
proxy_url = f'http://{proxy_host}:7890'
os.environ['HTTP_PROXY'] = proxy_url
os.environ['HTTPS_PROXY'] = proxy_url

print(f"当前环境: {args.env}")
print(f"使用代理: {proxy_url}")

# 创建翻译器
translator = Translator(to_lang='zh', from_lang='en', provider='mymemory')

# 设置 Discord 机器人
intents = discord.Intents.default()
client = discord.Client(intents=intents, proxy=proxy_url, proxy_auth=None)

# 配置：RSS源列表和目标Discord频道ID
rss_feeds = [
    'https://openai.com/news/rss.xml',  # OpenAI Blog
    'https://blog.google/technology/ai/rss/',  # Google AI Blog
    'https://blogs.nvidia.cn/feed/',  # NVIDIA AI Blog
    'https://developer.nvidia.cn/zh-cn/blog/feed',
    'http://news.mit.edu/rss/topic/artificial-intelligence2', #MIT news
    'https://deepmind.com/blog/feed/basic/', # deepmind
    'https://stability.ai/news?format=rss',  # Stability AI Blog
    'https://jamesg.blog/hf-papers.xml',  # Hugging Face Blog
    'https://deepmind.com/blog/rss',  # DeepMind Blog
    'https://techcrunch.com/tag/ai/feed',  # TechCrunch AI Blog
    'https://www.geekpark.net/rss',  # GeekPark Blog
    'https://www.qbitai.com/category/%E8%B5%84%E8%AE%AF/feed', # 量子位
]

# Discord 频道ID
channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))

# 文章历史记录文件
HISTORY_FILE = 'sent_articles.json'

def load_sent_articles():
    """加载已发送文章的历史记录"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"加载历史记录出错: {str(e)}")
        return {}

def save_sent_articles(sent_articles):
    """保存已发送文章的历史记录"""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(sent_articles, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存历史记录出错: {str(e)}")

async def is_within_time_window(entry):
    try:
        if hasattr(entry, 'published_parsed'):
            pub_time = time.mktime(entry.published_parsed)
        elif hasattr(entry, 'updated_parsed'):
            pub_time = time.mktime(entry.updated_parsed)
        else:
            print(f"无法获取文章发布时间，将默认发送")
            return True
            
        current_time = time.time()
        time_diff = current_time - pub_time
        
        # 72小时内的文章
        return time_diff <= 72 * 3600
    except Exception as e:
        print(f"检查文章时间出错: {str(e)}")
        return True

def clean_html(raw_html):
    """清理HTML标签并处理特殊字符"""
    # 使用BeautifulSoup清理HTML标签
    soup = BeautifulSoup(raw_html, 'html.parser')
    text = soup.get_text()
    # 解码HTML实体
    text = html.unescape(text)
    # 清理多余的空白字符
    text = re.sub(r'\s+', ' ', text).strip()
    return text

async def translate_text(text):
    if not text:
        return text
        
    try:
        # 分块翻译，每块最多1000字符
        chunks = [text[i:i+1000] for i in range(0, len(text), 1000)]
        translated_chunks = []
        
        for chunk in chunks:
            try:
                translation = translator.translate(chunk)
                if translation:
                    translated_chunks.append(translation)
                await asyncio.sleep(1)  # 添加延迟避免请求过快
            except Exception as e:
                print(f"翻译出错: {str(e)}")
                translated_chunks.append(chunk)  # 如果翻译失败，使用原文
                
        return ' '.join(translated_chunks)
    except Exception as e:
        print(f"翻译出错: {str(e)}")
        return text  # 如果翻译失败，返回原文

def has_chinese(text):
    """检查文本是否包含中文字符"""
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False

# 发送信息到Discord频道
async def send_to_discord(title, link, summary):
    try:
        channel = client.get_channel(channel_id)
        if channel:
            # 限制消息长度，Discord消息上限为2000字符
            if len(summary) > 1000:
                summary = summary[:1000] + "..."
            
            # 构建消息
            message_parts = []
            
            # 添加标题（原文和翻译）
            if "\n🔄" in title:
                title_parts = title.split("\n🔄")
                message_parts.append(f"📰 **{title_parts[0].strip()}**")
                message_parts.append(f"🔄 {title_parts[1].strip()}")
            else:
                message_parts.append(f"📰 **{title}**")
            
            # 添加摘要（原文和翻译）
            if "\n\n🔄" in summary:
                summary_parts = summary.split("\n\n🔄")
                message_parts.append(f"\n📝 {summary_parts[0].strip()}")
                message_parts.append(f"\n🔄 {summary_parts[1].strip()}")
            else:
                message_parts.append(f"\n📝 {summary}")
            
            # 添加链接
            message_parts.append(f"\n\n🔗 [阅读原文]({link})")
            
            # 组合消息
            message = "\n".join(message_parts)
            
            await channel.send(message)
            title_original = title.split('\n')[0]  # 先分割，再使用变量
            print(f"已发送文章：{title_original}")  # 只打印原标题
        else:
            print(f"Cannot find channel with ID: {channel_id}")
    except Exception as e:
        print(f"Error sending message to Discord: {str(e)}")

# 获取RSS内容
async def fetch_rss():
    try:
        # 加载历史记录
        sent_articles = load_sent_articles()
        current_time = time.time()
        
        for feed_url in rss_feeds:
            try:
                print(f"正在获取 {feed_url} 的内容...")
                feed = feedparser.parse(feed_url)
                if feed.bozo:  # 检查RSS解析是否有错误
                    print(f"解析 {feed_url} 时出错: {feed.bozo_exception}")
                    continue
                    
                for entry in feed.entries:
                    try:
                        # 获取文章信息
                        title = entry.get('title', 'No title')
                        link = entry.get('link', '#')
                        
                        # 创建文章的唯一标识（使用标题和链接的组合）
                        article_id = hashlib.md5(f"{link}{title}".encode()).hexdigest()
                        
                        # 检查是否已发送过这篇文章
                        if article_id in sent_articles:
                            print(f"跳过已发送文章：{title}")
                            continue
                            
                        # 检查文章时间
                        if not await is_within_time_window(entry):
                            print(f"跳过过期文章：{title}")
                            continue
                            
                        # 获取摘要
                        summary = None
                        if hasattr(entry, 'content') and entry.content:
                            summary = entry.content[0].value
                        elif hasattr(entry, 'description'):
                            summary = entry.description
                        elif hasattr(entry, 'summary'):
                            summary = entry.summary
                        else:
                            summary = 'No summary available'
                            
                        # 清理HTML标签
                        title = clean_html(title)
                        summary = clean_html(summary)
                        
                        # 翻译标题和摘要
                        if not has_chinese(title):
                            print(f"翻译标题: {title}")
                            title_zh = await translate_text(title)
                            if title_zh and title_zh != title:
                                title = f"{title}\n{title_zh}"
                                
                        if not has_chinese(summary):
                            print(f"翻译摘要: {summary[:100]}...")
                            summary_zh = await translate_text(summary)
                            if summary_zh and summary_zh != summary:
                                summary = f"{summary}\n\n{summary_zh}"
                                
                        # 发送消息
                        channel = client.get_channel(channel_id)
                        if channel:
                            message = f"**{title}**\n\n{summary}\n\n🔗 {link}"
                            await channel.send(message)
                            print(f"已发送文章：{title}")
                            
                            # 记录已发送的文章
                            sent_articles[article_id] = {
                                'title': title,
                                'link': link,
                                'timestamp': current_time
                            }
                            
                            # 每发送一篇文章就保存一次历史记录
                            save_sent_articles(sent_articles)
                            
                            # 添加延迟避免发送过快
                            await asyncio.sleep(1)
                            
                    except Exception as e:
                        print(f"处理文章时出错: {str(e)}")
                        continue
                        
            except Exception as e:
                print(f"获取 {feed_url} 内容时出错: {str(e)}")
                continue
                
        # 清理旧记录（保留7天内的记录）
        cutoff_time = current_time - (7 * 24 * 3600)  # 7天前的时间戳
        old_count = len(sent_articles)
        sent_articles = {k: v for k, v in sent_articles.items() 
                        if v.get('timestamp', 0) > cutoff_time}
        new_count = len(sent_articles)
        if old_count != new_count:
            print(f"清理了 {old_count - new_count} 条过期记录")
            save_sent_articles(sent_articles)
            
    except Exception as e:
        print(f"获取RSS内容时出错: {str(e)}")

async def periodic_fetch():
    while True:
        try:
            print("开始定期获取RSS内容...")
            await fetch_rss()
        except Exception as e:
            print(f"Error in periodic fetch: {str(e)}")
        print("等待30分钟后进行下一次获取...")
        await asyncio.sleep(1800)  # 每30分钟运行一次

@client.event
async def on_ready():
    print(f'Bot已登录为：{client.user}')
    print(f'正在监听频道ID：{channel_id}')
    await asyncio.gather(
        fetch_rss(),
        periodic_fetch()
    )

# 启动bot
if __name__ == "__main__":
    # 从环境变量获取Token
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("错误：未设置DISCORD_TOKEN环境变量")
        sys.exit(1)
        
    try:
        print("正在连接到Discord...")
        print(f"当前环境: {args.env}")
        print(f"使用代理: {proxy_url}")
        client.run(token)
    except Exception as e:
        print(f"运行Bot时出错: {str(e)}")
        print("请检查：")
        print(f"1. 代理是否正常工作（{proxy_url}）")
        print("2. Discord Token是否正确")
        print("3. Bot是否已添加到服务器")
        print("4. Bot是否有正确的权限")
