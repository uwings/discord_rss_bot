import aiohttp
import feedparser
from datetime import datetime
from typing import Optional, List, Dict
import logging
import asyncio
from bs4 import BeautifulSoup, CData
import html
import json
import os
import hashlib
from pathlib import Path
import re
import ssl
import certifi

class BaseRSSSource:
    # 文章历史记录文件
    HISTORY_FILE = 'article_history.json'
    # 历史记录保留时间（7天）
    HISTORY_KEEP_DAYS = 7
    # 共享的历史记录
    _shared_history = {}
    
    @classmethod
    def load_history(cls):
        """加载文章历史记录"""
        try:
            if not cls._shared_history:
                if os.path.exists(cls.HISTORY_FILE):
                    with open(cls.HISTORY_FILE, 'r', encoding='utf-8') as f:
                        cls._shared_history = json.load(f)
                else:
                    cls._shared_history = {}
            return cls._shared_history
        except Exception as e:
            logging.error(f"加载历史记录出错: {str(e)}")
            return {}
            
    @classmethod
    def save_history(cls, history: Dict = None):
        """保存文章历史记录"""
        try:
            if history is not None:
                cls._shared_history.update(history)
            # 创建目录（如果不存在）
            Path(cls.HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(cls.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(cls._shared_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存历史记录出错: {str(e)}")
            
    @classmethod
    def clean_history(cls):
        """清理过期的历史记录"""
        try:
            history = cls.load_history()
            now = datetime.now().timestamp()
            # 保留7天内的记录
            cutoff = now - (cls.HISTORY_KEEP_DAYS * 24 * 3600)
            
            old_count = len(history)
            history = {k: v for k, v in history.items() 
                      if v.get('timestamp', 0) > cutoff}
            new_count = len(history)
            
            if old_count != new_count:
                logging.info(f"清理了 {old_count - new_count} 条过期记录")
                cls._shared_history = history
                cls.save_history()
                
            return history
        except Exception as e:
            logging.error(f"清理历史记录出错: {str(e)}")
            return {}

    def __init__(self, url: str, channel_ids: List[str]):
        self.url = url
        self.channel_ids = channel_ids  # 支持多个频道ID
        self.name = self.__class__.__name__
        logging.info(f"初始化RSS源: {self.name} - {self.url}")
        self.last_fetch_time = None
        self.logger = logging.getLogger(self.name)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, application/atom+xml, application/json, text/xml'
        }
        # 使用共享的历史记录
        self.history = self.clean_history()
        
    def get_headers(self) -> Dict:
        """获取请求头，子类可以重写"""
        return self.headers
        
    async def fetch(self) -> Optional[feedparser.FeedParserDict]:
        """获取RSS内容"""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            self.logger.debug(f"[{self.name}] 开始获取RSS: {self.url}")
            self.logger.debug(f"[{self.name}] 使用代理: {os.environ.get('HTTP_PROXY')}")
            
            # 创建SSL上下文
            ssl_context = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
            
            # 创建connector
            connector = aiohttp.TCPConnector(
                ssl=ssl_context,
                force_close=True,
                enable_cleanup_closed=True,
                limit=10,
                ttl_dns_cache=300,
                verify_ssl=True
            )
            
            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                trust_env=True
            ) as session:
                headers = self.get_headers()
                self.logger.debug(f"[{self.name}] 请求头: {headers}")
                
                try:
                    self.logger.debug(f"[{self.name}] 开始发送请求...")
                    async with session.get(
                        self.url,
                        headers=headers,
                        proxy=os.environ.get('HTTP_PROXY')
                    ) as response:
                        self.logger.debug(f"[{self.name}] 收到响应: status={response.status}")
                        
                        if response.status != 200:
                            await self.handle_error(f"HTTP error {response.status}")
                            return None
                            
                        content = await response.text()
                        self.logger.debug(f"[{self.name}] 成功获取内容，长度: {len(content)}")
                        
                        # 尝试修复常见的XML问题
                        content = self.clean_xml(content)
                        
                        # 使用正确的解析器
                        self.logger.debug(f"[{self.name}] 开始解析RSS内容...")
                        feed = feedparser.parse(content, sanitize_html=True)
                        
                        if feed.bozo and feed.bozo_exception:  # feedparser解析错误标志
                            await self.handle_error(f"Parse error: {feed.bozo_exception}")
                            return None
                            
                        self.last_fetch_time = datetime.now()
                        self.logger.debug(f"[{self.name}] RSS解析完成，条目数: {len(feed.entries) if hasattr(feed, 'entries') else 0}")
                        return feed
                except aiohttp.ClientError as e:
                    self.logger.error(f"[{self.name}] 请求错误: {str(e)}", exc_info=True)
                    await self.handle_error(f"Request error: {str(e)}")
                    return None
                    
        except asyncio.TimeoutError:
            self.logger.error(f"[{self.name}] 请求超时")
            await self.handle_error("Fetch timeout")
            return None
        except Exception as e:
            self.logger.error(f"[{self.name}] 获取RSS出错: {str(e)}", exc_info=True)
            await self.handle_error(f"Fetch error: {str(e)}")
            return None
            
    def clean_xml(self, content: str) -> str:
        """清理和修复XML内容"""
        try:
            # 预处理：移除所有控制字符
            content = ''.join(char for char in content if ord(char) >= 32 or char == '\n')
            
            # 移除XML声明
            content = re.sub(r'<\?xml[^>]*\?>', '', content)
            
            # 移除DOCTYPE
            content = re.sub(r'<!DOCTYPE[^>]*>', '', content)
            
            # 处理CDATA
            content = re.sub(r'<!\[CDATA\[(.*?)\]\]>', lambda m: html.escape(m.group(1)), content)
            
            # 处理HTML实体
            entities = {
                '&nbsp;': ' ', '&lt;': '<', '&gt;': '>', '&amp;': '&', '&quot;': '"',
                '&apos;': "'", '&cent;': '¢', '&pound;': '£', '&yen;': '¥', '&euro;': '€',
                '&copy;': '©', '&reg;': '®', '&trade;': '™',
                '&mdash;': '—', '&ndash;': '–', '&hellip;': '…',
                '&bull;': '•', '&middot;': '·',
                '&laquo;': '«', '&raquo;': '»',
                '&lsquo;': ''', '&rsquo;': ''',
                '&ldquo;': '"', '&rdquo;': '"',
                '&prime;': '′', '&Prime;': '″',
                '&frasl;': '⁄', '&permil;': '‰',
                '&larr;': '←', '&uarr;': '↑', '&rarr;': '→', '&darr;': '↓',
            }
            for entity, char in entities.items():
                content = content.replace(entity, char)
            
            # 修复未闭合的标签
            void_elements = ['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 
                           'link', 'meta', 'param', 'source', 'track', 'wbr']
            for tag in void_elements:
                content = re.sub(f'<{tag}([^>]*[^/])>', f'<{tag}\\1/>', content)
            
            # 移除注释
            content = re.sub(r'<!--[\s\S]*?-->', '', content)
            
            # 使用BeautifulSoup清理
            soup = BeautifulSoup(content, 'lxml-xml')
            
            # 移除所有script和style标签
            for tag in soup(['script', 'style']):
                tag.decompose()
                
            # 移除所有事件属性
            for tag in soup.find_all(True):
                attrs = dict(tag.attrs)
                for attr in attrs:
                    if attr.startswith('on'):
                        del tag.attrs[attr]
            
            content = str(soup)
            
            # 移除多余的空白
            content = re.sub(r'\s+', ' ', content)
            content = re.sub(r'>\s+<', '><', content)
            
            return content.strip()
        except Exception as e:
            self.logger.warning(f"Clean XML error: {str(e)}")
            return content
            
    async def parse_entry(self, entry) -> Dict:
        """默认的文章解析方法，子类可以重写"""
        try:
            # 获取摘要
            if isinstance(entry, dict):
                summary = entry.get('summary', '')
                if not summary and entry.get('content'):
                    # 某些源使用content而不是summary
                    content = entry.get('content')
                    if isinstance(content, list) and content:
                        summary = content[0].get('value', '')
                    elif isinstance(content, str):
                        summary = content
                
                return {
                    'title': entry.get('title', ''),
                    'link': entry.get('link', ''),
                    'summary': summary,
                    'published': entry.get('published', entry.get('updated', ''))
                }
            else:
                # 处理feedparser.FeedParserDict对象
                summary = getattr(entry, 'summary', '')
                if not summary and hasattr(entry, 'content'):
                    # 某些源使用content而不是summary
                    summary = entry.content[0].value if entry.content else ''
                
                return {
                    'title': getattr(entry, 'title', ''),
                    'link': getattr(entry, 'link', ''),
                    'summary': summary,
                    'published': getattr(entry, 'published', getattr(entry, 'updated', ''))
                }
        except Exception as e:
            await self.handle_error(f"Parse entry error: {str(e)}")
            return {}
    
    def get_entry_id(self, entry) -> str:
        """生成文章的唯一标识"""
        try:
            # 获取标题和链接
            title = getattr(entry, 'title', '') if not isinstance(entry, dict) else entry.get('title', '')
            link = getattr(entry, 'link', '') if not isinstance(entry, dict) else entry.get('link', '')
            # 使用标题和链接的组合作为唯一标识
            id_str = f"{link}{title}"
            return hashlib.md5(id_str.encode()).hexdigest()
        except Exception as e:
            self.logger.error(f"生成文章ID出错: {str(e)}")
            return hashlib.md5(str(datetime.now().timestamp()).encode()).hexdigest()
        
    async def should_post_entry(self, entry) -> bool:
        """判断是否应该发送这篇文章"""
        try:
            # 检查必要字段是否存在
            if isinstance(entry, dict):
                if not entry.get('title') or not entry.get('link'):
                    return False
            else:
                if not hasattr(entry, 'title') or not hasattr(entry, 'link'):
                    return False
                    
            # 检查是否已发送过
            entry_id = self.get_entry_id(entry)
            if entry_id in self.history:
                self.logger.info(f"跳过已发送文章：{getattr(entry, 'title', '') if not isinstance(entry, dict) else entry.get('title', '')}")
                return False
                
            # 检查发布时间
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
                # 只发送最近72小时的文章
                now = datetime.now()
                entry_time = datetime(*published_time[:6])
                time_diff = now - entry_time
                if time_diff.total_seconds() > 72 * 3600:
                    self.logger.info(f"跳过过期文章：{getattr(entry, 'title', '') if not isinstance(entry, dict) else entry.get('title', '')}")
                    return False
                    
            return True
        except Exception as e:
            self.logger.error(f"检查文章是否应该发送时出错: {str(e)}")
            return False
            
    async def mark_as_sent(self, entry) -> None:
        """标记文章为已发送"""
        try:
            # 获取文章信息
            title = getattr(entry, 'title', '') if not isinstance(entry, dict) else entry.get('title', '')
            link = getattr(entry, 'link', '') if not isinstance(entry, dict) else entry.get('link', '')
            entry_id = self.get_entry_id(entry)
            
            # 更新历史记录
            self.history[entry_id] = {
                'title': title,
                'link': link,
                'timestamp': datetime.now().timestamp(),
                'source': self.name
            }
            
            # 保存到文件
            self.__class__.save_history(self.history)
            self.logger.info(f"已标记文章为已发送: {title}")
        except Exception as e:
            self.logger.error(f"标记文章为已发送时出错: {str(e)}")
    
    async def handle_error(self, error_msg: str):
        """错误处理，子类可以重写"""
        self.logger.error(f"[{self.name}] {error_msg}")

    async def fetch_feed(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, headers=self.get_headers()) as response:
                    if response.status == 200:
                        content = await response.text()
                        feed = feedparser.parse(content)
                        logging.info(f"成功获取RSS源 [{self.name}] 的内容")
                        return feed
                    else:
                        logging.error(f"获取RSS源 [{self.name}] 失败: HTTP {response.status}")
                        return None
        except Exception as e:
            logging.error(f"获取RSS源 [{self.name}] 出错: {str(e)}")
            return None

    async def parse_entry(self, entry: Dict) -> str:
        """解析RSS条目,返回要发送的消息内容"""
        try:
            title = entry.get('title', 'No Title')
            link = entry.get('link', '')
            summary = entry.get('summary', '')
            
            # 清理HTML标签
            clean_summary = BeautifulSoup(summary, 'html.parser').get_text()
            
            message = f"**{title}**\n\n{clean_summary}\n\n原文链接: {link}"
            logging.info(f"解析文章 [{self.name}]: {title}")
            return message
        except Exception as e:
            logging.error(f"解析文章失败 [{self.name}]: {str(e)}")
            raise
