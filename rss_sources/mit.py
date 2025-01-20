from typing import Dict
from .base import BaseRSSSource
from bs4 import BeautifulSoup
import re

class MitRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="http://news.mit.edu/rss/topic/artificial-intelligence2",
            channel_ids=channel_ids
        )
    
    def clean_xml(self, content: str) -> str:
        """特定的XML清理逻辑"""
        # 修复未定义的实体引用
        content = content.replace('&raquo;', '»')
        content = content.replace('&laquo;', '«')
        content = content.replace('&rsquo;', ''')
        content = content.replace('&lsquo;', ''')
        content = content.replace('&rdquo;', '"')
        content = content.replace('&ldquo;', '"')
        # 移除非法字符
        content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
        return super().clean_xml(content)
        
    async def parse_entry(self, entry) -> Dict:
        """MIT特定的解析逻辑"""
        data = await super().parse_entry(entry)
        
        # 清理内容中的HTML标签
        if data.get('summary'):
            # 移除多余的空白和换行
            summary = re.sub(r'\s+', ' ', data['summary'])
            # 移除HTML标签
            soup = BeautifulSoup(summary, 'html.parser')
            data['summary'] = soup.get_text(separator=' ', strip=True)
            
        return data
        
    async def handle_error(self, error_msg: str):
        # 特定的错误处理
        await super().handle_error(f"mit RSS处理错误: {error_msg}") 