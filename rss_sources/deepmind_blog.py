from typing import Dict
from .base import BaseRSSSource

class DeepmindBlogRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://www.deepmind.com/blog/feed/basic",  # 更新URL
            channel_ids=channel_ids
        )
    
    async def parse_entry(self, entry) -> Dict:
        """DeepMind特定的解析逻辑"""
        data = await super().parse_entry(entry)
        
        # 确保获取完整的内容
        if not data.get('summary') and hasattr(entry, 'content'):
            data['summary'] = entry.content[0].value if entry.content else ''
            
        return data
        
    async def handle_error(self, error_msg: str):
        await super().handle_error(f"deepmind_blog RSS处理错误: {error_msg}") 