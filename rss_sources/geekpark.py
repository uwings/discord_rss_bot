from typing import Dict
from .base import BaseRSSSource
from bs4 import BeautifulSoup
import re

class GeekparkRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://www.geekpark.net/rss",
            channel_ids=channel_ids
        )
    
    def clean_xml(self, content: str) -> str:
        """特定的XML清理逻辑"""
        # 修复未转义的HTML实体
        content = content.replace('&amp;amp;', '&amp;')
        content = content.replace('&amp;quot;', '&quot;')
        content = content.replace('&amp;lt;', '&lt;')
        content = content.replace('&amp;gt;', '&gt;')
        # 移除非法字符
        content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
        return super().clean_xml(content)
        
    async def parse_entry(self, entry) -> Dict:
        """GeekPark特定的解析逻辑"""
        data = await super().parse_entry(entry)
        
        # 清理内容中的HTML标签
        if data.get('summary'):
            # 移除script和style标签
            soup = BeautifulSoup(data['summary'], 'html.parser')
            for tag in soup(['script', 'style', 'iframe']):
                tag.decompose()
            # 移除所有属性
            for tag in soup.find_all(True):
                tag.attrs = {}
            data['summary'] = soup.get_text(separator=' ', strip=True)
            
        return data
        
    async def handle_error(self, error_msg: str):
        # 特定的错误处理
        await super().handle_error(f"geekpark RSS处理错误: {error_msg}") 