from typing import Dict
from .base import BaseRSSSource
from bs4 import BeautifulSoup

class TechcrunchRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://techcrunch.com/tag/ai/feed",
            channel_ids=channel_ids
        )
    
    def get_headers(self) -> Dict:
        """自定义请求头"""
        headers = super().get_headers()
        headers.update({
            'Referer': 'https://techcrunch.com/',
            'Origin': 'https://techcrunch.com'
        })
        return headers
        
    async def parse_entry(self, entry) -> Dict:
        """TechCrunch特定的解析逻辑"""
        data = await super().parse_entry(entry)
        
        # 确保获取完整的内容
        if not data.get('summary') and hasattr(entry, 'content'):
            data['summary'] = entry.content[0].value if entry.content else ''
            
        # 清理内容中的HTML标签
        if data.get('summary'):
            soup = BeautifulSoup(data['summary'], 'html.parser')
            # 移除所有script和style标签
            for script in soup(['script', 'style']):
                script.decompose()
            data['summary'] = soup.get_text(separator=' ', strip=True)
            
        return data
        
    async def handle_error(self, error_msg: str):
        await super().handle_error(f"techcrunch RSS处理错误: {error_msg}") 