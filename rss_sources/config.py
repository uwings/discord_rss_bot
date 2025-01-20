from typing import List, Dict
from .base import BaseRSSSource

class RSSConfig:
    def __init__(self):
        self.sources: List[BaseRSSSource] = []
        
    def add_source(self, source: BaseRSSSource):
        """添加RSS源"""
        self.sources.append(source)
        
    def get_sources(self) -> List[BaseRSSSource]:
        """获取所有RSS源"""
        return self.sources
    
    def get_sources_by_channel(self, channel_id: str) -> List[BaseRSSSource]:
        """获取指定频道的所有RSS源"""
        return [source for source in self.sources if channel_id in source.channel_ids] 