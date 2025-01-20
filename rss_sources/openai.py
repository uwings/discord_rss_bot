from typing import Dict
from .base import BaseRSSSource

class OpenaiRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://openai.com/blog/rss.xml",
            channel_ids=channel_ids
        )
    
    def get_headers(self) -> Dict:
        """自定义请求头"""
        headers = super().get_headers()
        headers.update({
            'Referer': 'https://openai.com/',
            'Origin': 'https://openai.com'
        })
        return headers
        
    async def parse_entry(self, entry) -> Dict:
        """OpenAI特定的解析逻辑"""
        data = await super().parse_entry(entry)
        
        # 如果有特定的处理逻辑可以在这里添加
        # 例如提取特定标签、格式化等
        
        return data
        
    async def handle_error(self, error_msg: str):
        # 特定的错误处理
        await super().handle_error(f"OpenAI RSS处理错误: {error_msg}") 