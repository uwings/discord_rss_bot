from typing import Dict
from .base import BaseRSSSource
from bs4 import BeautifulSoup
import re

class GoogleAIRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://blog.google/technology/ai/rss",
            channel_ids=channel_ids
        )
    
    def clean_xml(self, content: str) -> str:
        """特定的XML清理逻辑"""
        # 修复未闭合的标签
        content = re.sub(r'<(br|hr|img)([^>]*[^/])>', r'<\1\2/>', content)
        # 修复嵌套的CDATA标签
        content = re.sub(r'\]\]>\s*\]\]>', ']]>', content)
        # 移除非法字符
        content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
        return super().clean_xml(content)
        
    async def parse_entry(self, entry) -> Dict:
        """Google AI特定的解析逻辑"""
        data = await super().parse_entry(entry)
        
        # 清理内容中的HTML标签
        if data.get('summary'):
            # 移除所有HTML注释
            summary = re.sub(r'<!--.*?-->', '', data['summary'], flags=re.DOTALL)
            # 移除script和style标签及其内容
            soup = BeautifulSoup(summary, 'html.parser')
            for tag in soup(['script', 'style', 'iframe']):
                tag.decompose()
            # 移除所有class和id属性
            for tag in soup.find_all(True):
                if 'class' in tag.attrs:
                    del tag.attrs['class']
                if 'id' in tag.attrs:
                    del tag.attrs['id']
            data['summary'] = soup.get_text(separator=' ', strip=True)
            
        return data
        
    async def handle_error(self, error_msg: str):
        # 特定的错误处理
        await super().handle_error(f"Google AI RSS处理错误: {error_msg}") 