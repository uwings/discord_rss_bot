from typing import Dict
from .base import BaseRSSSource
from bs4 import BeautifulSoup
import re

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
        try:
            # 获取基本信息
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '')
            
            # 获取摘要
            summary = ''
            if hasattr(entry, 'summary'):
                summary = entry.summary
            elif hasattr(entry, 'description'):
                summary = entry.description
            elif hasattr(entry, 'content'):
                if isinstance(entry.content, list) and entry.content:
                    summary = entry.content[0].value
                else:
                    summary = str(entry.content)
                    
            # 获取发布时间
            published = getattr(entry, 'published', getattr(entry, 'updated', ''))
            
            # 清理内容中的HTML标签
            if summary:
                # 移除所有HTML注释
                summary = re.sub(r'<!--.*?-->', '', summary, flags=re.DOTALL)
                # 移除多余的空白和换行
                summary = re.sub(r'\s+', ' ', summary)
                # 移除HTML标签
                soup = BeautifulSoup(summary, 'html.parser')
                for tag in soup(['script', 'style', 'iframe']):
                    tag.decompose()
                summary = soup.get_text(separator=' ', strip=True)
                
            return {
                'title': title,
                'link': link,
                'summary': summary,
                'published': published
            }
        except Exception as e:
            await self.handle_error(f"解析文章错误: {str(e)}")
            return {}
        
    async def handle_error(self, error_msg: str):
        await super().handle_error(f"techcrunch RSS处理错误: {error_msg}") 