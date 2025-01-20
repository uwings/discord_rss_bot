from typing import Dict
from .base import BaseRSSSource
from bs4 import BeautifulSoup
import re

class StabilityRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://stability.ai/news/rss.xml",
            channel_ids=channel_ids
        )
    
    def get_headers(self) -> Dict:
        """自定义请求头"""
        headers = super().get_headers()
        headers.update({
            'Referer': 'https://stability.ai/',
            'Origin': 'https://stability.ai'
        })
        return headers
        
    def clean_xml(self, content: str) -> str:
        """特定的XML清理逻辑"""
        # 移除CDATA结束标记后的多余内容
        content = re.sub(r'\]\]>.*?\]\]>', ']]>', content)
        # 移除多余的XML声明
        content = re.sub(r'<\?xml[^>]*\?>', '', content)
        # 处理特殊的Squarespace标记
        content = content.replace('Site-Server v@build.version@', 'Site-Server')
        return super().clean_xml(content)
        
    async def parse_entry(self, entry) -> Dict:
        """Stability特定的解析逻辑"""
        data = await super().parse_entry(entry)
        
        # 清理内容中的HTML标签和特殊格式
        if data.get('summary'):
            # 移除Key Takeaways部分
            summary = re.sub(r'\*\*Key Takeaways:?\*\*.*?(?=\n\n)', '', data['summary'], flags=re.DOTALL)
            # 移除其他Markdown标记
            summary = re.sub(r'\*\*.*?\*\*', '', summary)
            # 清理多余的空行
            summary = re.sub(r'\n{3,}', '\n\n', summary)
            soup = BeautifulSoup(summary, 'html.parser')
            data['summary'] = soup.get_text(separator=' ', strip=True)
            
        return data
        
    async def handle_error(self, error_msg: str):
        await super().handle_error(f"stability RSS处理错误: {error_msg}") 