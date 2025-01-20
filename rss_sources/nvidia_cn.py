from typing import Dict
from .base import BaseRSSSource

class NvidiaCnRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://blogs.nvidia.cn/feed/",
            channel_ids=channel_ids
        )
    
    async def parse_entry(self, entry) -> Dict:
        # 获取基础解析结果
        data = await super().parse_entry(entry)
        
        # 可以添加特定的处理逻辑
        # 例如提取特定标签、格式化等
        
        return data
        
    async def handle_error(self, error_msg: str):
        # 特定的错误处理
        await super().handle_error(f"nvidia cn RSS处理错误: {error_msg}") 