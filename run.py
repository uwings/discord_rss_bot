import os
import json
import asyncio
import discord
import logging
import importlib
import inspect
import aiohttp
import argparse
from pathlib import Path
from datetime import datetime
from translate import Translator
from dotenv import load_dotenv
from rss_sources.config import RSSConfig
from rss_sources.base import BaseRSSSource
from typing import List, Dict

# 解析命令行参数
parser = argparse.ArgumentParser(description='Discord RSS Bot')
parser.add_argument('--env', type=str, default='dev', choices=['dev', 'prod'], help='运行环境 (dev/prod)')
args = parser.parse_args()

# 根据环境设置代理
proxy_url = None
if args.env == 'dev':
    proxy_url = 'http://127.0.0.1:7890'
    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url
else:  # prod
    proxy_url = 'http://192.168.5.107:7890'
    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url

# 加载环境变量
load_dotenv()
token = os.getenv('DISCORD_TOKEN')

# 加载配置文件
def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载配置文件失败: {str(e)}")
        return None

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 创建Discord客户端
intents = discord.Intents.default()

# 创建自定义的aiohttp会话
connector = aiohttp.TCPConnector(
    ssl=False,  # 禁用SSL验证
    limit=10,   # 限制并发连接数
    ttl_dns_cache=300,  # DNS缓存时间
)

# 创建代理配置
proxy_auth = None  # 如果代理需要认证，在这里设置
timeout = aiohttp.ClientTimeout(
    total=30,     # 总超时时间
    connect=10,   # 连接超时
    sock_read=30  # 读取超时
)

# 创建自定义session
session = aiohttp.ClientSession(
    connector=connector,
    timeout=timeout,
    trust_env=True,  # 信任环境变量中的代理设置
    proxy=proxy_url
)

# 使用自定义session创建Discord客户端
client = discord.Client(
    intents=intents,
    proxy=proxy_url,
    proxy_auth=proxy_auth,
    http_session=session
)

# 创建翻译器
translator = Translator(to_lang="zh", from_lang="en", provider="mymemory")

def load_rss_sources():
    """动态加载所有RSS源类"""
    rss_classes = []
    rss_dir = Path(__file__).parent / 'rss_sources'
    
    # 加载配置
    config = load_config()
    if not config:
        return []
    
    # 遍历rss_sources目录中的所有.py文件
    for file_path in rss_dir.glob('*.py'):
        if file_path.stem in ['__init__', 'base', 'config']:
            continue
            
        try:
            # 检查源是否启用
            source_config = config['sources'].get(file_path.stem)
            if not source_config or not source_config.get('enabled', True):
                logger.info(f"跳过已禁用的RSS源: {file_path.stem}")
                continue
                
            # 构建模块名
            module_name = f"rss_sources.{file_path.stem}"
            
            # 导入模块
            module = importlib.import_module(module_name)
            
            # 查找继承自BaseRSSSource的类
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, BaseRSSSource) and 
                    obj != BaseRSSSource):
                    # 添加配置信息到类
                    obj._config = source_config
                    rss_classes.append(obj)
                    logger.info(f"已加载RSS源: {obj.__name__}")
        except Exception as e:
            logger.error(f"加载RSS源 {file_path.stem} 时出错: {str(e)}")
            
    return rss_classes

async def translate_with_timeout(text: str, timeout: int = 10) -> str:
    """带超时的翻译"""
    try:
        # 如果文本是中文，直接返回
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            return text
            
        # 创建一个事件循环
        loop = asyncio.get_event_loop()
        # 在线程池中运行同步翻译函数
        future = loop.run_in_executor(None, translator.translate, text)
        # 等待翻译完成，带超时
        result = await asyncio.wait_for(future, timeout=timeout)
        
        # 检查翻译结果是否包含错误信息
        if result and not result.upper().startswith('MYMEMORY WARNING'):
            return result
        return text  # 如果有错误，返回原文
    except asyncio.TimeoutError:
        logger.warning("翻译超时，使用原文")
        return text
    except Exception as e:
        logger.warning(f"翻译错误: {str(e)}，使用原文")
        return text

async def translate_text(text: str) -> str:
    """翻译文本"""
    try:
        if not text:
            return ""
            
        # 如果文本是中文，直接返回
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            return text
            
        # 分块翻译以避免过长
        max_length = 500
        chunks = [text[i:i + max_length] for i in range(0, len(text), max_length)]
        translated_chunks = []
        
        # 并发翻译所有块
        tasks = [translate_with_timeout(chunk) for chunk in chunks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"翻译错误: {str(result)}，使用原文")
                translated_chunks.append(chunks[i])  # 使用对应的原文
            else:
                translated_chunks.append(result if result else chunks[i])
                
        return ' '.join(translated_chunks)
    except Exception as e:
        logger.warning(f"翻译错误: {str(e)}，使用原文")
        return text

async def send_to_discord(channel_id: int, entry: dict):
    """发送消息到Discord"""
    try:
        channel = client.get_channel(channel_id)
        if channel:
            # 创建消息
            message = f"**{entry['title']}**\n"
            
            # 如果标题不是中文，尝试翻译
            if not any('\u4e00' <= char <= '\u9fff' for char in entry['title']):
                title_zh = await translate_text(entry['title'])
                if title_zh != entry['title']:
                    message += f"{title_zh}\n"
                    
            message += "\n"
            
            # 如果摘要不是中文，尝试翻译
            if entry.get('summary'):
                if not any('\u4e00' <= char <= '\u9fff' for char in entry['summary']):
                    summary_zh = await translate_text(entry['summary'])
                    if summary_zh != entry['summary']:
                        message += f"{summary_zh}\n\n"
                else:
                    message += f"{entry['summary']}\n\n"
                    
            if entry.get('link'):
                message += f"链接: {entry['link']}"
                
            await channel.send(message)
            logger.info(f"已发送文章：{entry['title']}")
    except Exception as e:
        logger.error(f"发送消息错误: {str(e)}")

async def setup_rss_sources() -> RSSConfig:
    """设置RSS源"""
    config = RSSConfig()
    
    # 动态加载所有RSS源
    rss_classes = load_rss_sources()
    
    # 实例化并添加所有RSS源
    for rss_class in rss_classes:
        try:
            # 使用配置中的channel_ids
            channel_ids = rss_class._config.get('channel_ids', [])
            source = rss_class(channel_ids)
            config.add_source(source)
            logger.info(f"已添加RSS源: {source.name} (频道: {channel_ids})")
        except Exception as e:
            logger.error(f"添加RSS源 {rss_class.__name__} 时出错: {str(e)}")
    
    return config

async def process_rss_feeds(config: RSSConfig):
    """处理所有RSS源"""
    round_count = 0
    while True:
        try:
            round_count += 1
            total_articles = 0
            processed_articles = 0
            expired_articles = 0
            duplicate_articles = 0
            
            logger.info(f"开始第 {round_count} 轮RSS处理...")
            
            for source in config.get_sources():
                try:
                    feed = await source.fetch_feed()
                    if feed and hasattr(feed, 'entries'):
                        total_articles += len(feed.entries)
                        for entry in feed.entries:
                            try:
                                # 获取标题
                                title = getattr(entry, 'title', 'No Title') if not isinstance(entry, dict) else entry.get('title', 'No Title')
                                logging.info(f"处理来自 {source.name} 的文章: {title}")
                                
                                # 检查是否过期
                                published_time = None
                                if isinstance(entry, dict):
                                    if entry.get('published_parsed'):
                                        published_time = entry['published_parsed']
                                    elif entry.get('updated_parsed'):
                                        published_time = entry['updated_parsed']
                                else:
                                    if hasattr(entry, 'published_parsed'):
                                        published_time = entry.published_parsed
                                    elif hasattr(entry, 'updated_parsed'):
                                        published_time = entry.updated_parsed
                                
                                if published_time:
                                    now = datetime.now()
                                    entry_time = datetime(*published_time[:6])
                                    time_diff = now - entry_time
                                    if time_diff.total_seconds() > 72 * 3600:
                                        logging.info(f"跳过过期文章：{title}")
                                        expired_articles += 1
                                        continue
                                
                                # 检查是否重复
                                entry_id = source.get_entry_id(entry)
                                if entry_id in source.history:
                                    logging.info(f"跳过重复文章 [{source.name}]: {title}")
                                    duplicate_articles += 1
                                    continue
                                
                                # 处理新文章
                                parsed_entry = await source.parse_entry(entry)
                                if parsed_entry:
                                    success = True
                                    for channel_id in source.channel_ids:
                                        try:
                                            await send_to_discord(int(channel_id), parsed_entry)
                                            logging.info(f"已发送文章到频道 {channel_id}: {title}")
                                        except Exception as e:
                                            success = False
                                            logging.error(f"发送文章到频道 {channel_id} 失败: {str(e)}")
                                    
                                    if success:
                                        await source.mark_as_sent(entry)
                                        processed_articles += 1
                                        
                            except Exception as e:
                                logging.error(f"处理文章错误 [{source.name}] {title}: {str(e)}")
                                continue
                except Exception as e:
                    logging.error(f"处理RSS源 {source.name} 时出错: {str(e)}")
                    continue
                    
            # 输出本轮处理的统计信息
            logger.info(f"第 {round_count} 轮RSS处理完成！统计信息：")
            logger.info(f"- 总文章数：{total_articles}")
            logger.info(f"- 新发送文章：{processed_articles}")
            logger.info(f"- 过期文章：{expired_articles}")
            logger.info(f"- 重复文章：{duplicate_articles}")
            logger.info("等待5分钟后开始下一轮处理...")
            
        except Exception as e:
            logging.error(f"RSS处理主循环错误: {str(e)}")
        
        # 等待一段时间再次获取
        await asyncio.sleep(300)  # 5分钟

@client.event
async def on_ready():
    """Bot就绪时的处理"""
    logger.info(f'Bot已登录为：{client.user}')
    
    # 设置RSS源
    config = await setup_rss_sources()
    
    # 启动RSS处理
    asyncio.create_task(process_rss_feeds(config))

async def send_message(channel_id: str, content: str):
    try:
        channel = client.get_channel(int(channel_id))
        if not channel:
            logging.error(f"找不到频道: {channel_id}")
            return
            
        # 如果消息超过Discord限制(2000字符),分段发送
        if len(content) > 2000:
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                await channel.send(chunk)
            logging.info(f"消息过长,已分{len(chunks)}段发送")
        else:
            await channel.send(content)
    except Exception as e:
        logging.error(f"发送消息错误: {str(e)}")

# 运行Discord客户端
client.run(token)
