from typing import Dict
from .base import BaseRSSSource
from bs4 import BeautifulSoup
import re
import hashlib
from datetime import datetime

class QbitaiRSS(BaseRSSSource):
    def __init__(self, channel_ids: list[str]):
        super().__init__(
            url="https://www.qbitai.com/category/%E8%B5%84%E8%AE%AF/feed",
            channel_ids=channel_ids
        )
    
    def get_entry_id(self, entry: Dict) -> str:
        """生成文章的唯一标识"""
        # 尝试使用多个字段组合生成唯一标识
        id_components = []
        
        # 使用guid
        if hasattr(entry, 'guid'):
            id_components.append(str(entry.guid))
            
        # 使用链接
        if hasattr(entry, 'link'):
            id_components.append(str(entry.link))
            
        # 使用标题
        if hasattr(entry, 'title'):
            id_components.append(str(entry.title))
            
        # 使用发布时间
        if hasattr(entry, 'published'):
            id_components.append(str(entry.published))
            
        # 如果没有任何可用字段，使用父类的方法
        if not id_components:
            return super().get_entry_id(entry)
            
        # 组合所有字段生成唯一标识
        id_str = '|'.join(id_components)
        return hashlib.md5(id_str.encode()).hexdigest()
        
    async def should_post_entry(self, entry) -> bool:
        """判断是否应该发送这篇文章"""
        try:
            # 检查必要字段是否存在
            if not hasattr(entry, 'title') or not hasattr(entry, 'link'):
                return False
                
            # 检查是否已发送过
            entry_id = self.get_entry_id(entry)
            if entry_id in self.history:
                self.logger.info(f"跳过已发送文章：{getattr(entry, 'title')} (ID: {entry_id})")
                return False
                
            # 检查发布时间
            published_time = None
            if hasattr(entry, 'published_parsed'):
                published_time = entry.published_parsed
            elif hasattr(entry, 'updated_parsed'):
                published_time = entry.updated_parsed
                
            if published_time:
                # 只发送最近72小时的文章
                now = datetime.now()
                entry_time = datetime(*published_time[:6])
                time_diff = now - entry_time
                if time_diff.total_seconds() > 72 * 3600:
                    self.logger.info(f"跳过过期文章：{getattr(entry, 'title')}")
                    return False
                    
            return True
        except Exception as e:
            await self.handle_error(f"Check entry error: {str(e)}")
            return False
        
    def clean_xml(self, content: str) -> str:
        """特定的XML清理逻辑"""
        # 修复未定义的实体引用
        content = content.replace('&hellip;', '...')
        # 移除非法字符
        content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
        return super().clean_xml(content)
        
    async def parse_entry(self, entry) -> Dict:
        """QbitAI特定的解析逻辑"""
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
        await super().handle_error(f"qbitai RSS处理错误: {error_msg}") 