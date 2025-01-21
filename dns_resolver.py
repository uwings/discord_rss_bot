import asyncio
import aiodns
import logging
from typing import List, Optional, Dict
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class ResolvedHost:
    ip: str
    timestamp: datetime
    ttl: int = 300  # 默认TTL为5分钟

    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.timestamp + timedelta(seconds=self.ttl)

class DNSResolver:
    # 可信的DNS服务器列表
    TRUSTED_DNS_SERVERS = [
        '1.1.1.1',        # Cloudflare
        '8.8.8.8',        # Google
        '208.67.222.222'  # OpenDNS
    ]
    
    # Discord API相关域名
    DISCORD_HOSTS = [
        'discord.com',
        'gateway.discord.gg',
        'cdn.discordapp.com',
        'media.discordapp.net'
    ]
    
    def __init__(self):
        self._resolver = None
        self._resolved_hosts = {}
        self._current_dns_index = 0
        self.last_resolved = None
    
    async def _init_resolver(self):
        """初始化DNS解析器"""
        if self._resolver is None:
            # 创建新的解析器实例
            self._resolver = aiodns.DNSResolver()
            # 设置nameservers
            self._resolver.nameservers = [self.TRUSTED_DNS_SERVERS[self._current_dns_index]]
            logger.info(f"使用DNS服务器: {self._resolver.nameservers[0]}")
    
    async def _resolve_host(self, hostname: str) -> Optional[List[str]]:
        """解析单个主机名"""
        try:
            await self._init_resolver()
            response = await self._resolver.query(hostname, 'A')
            return [answer.host for answer in response]
        except Exception as e:
            logger.error(f"解析 {hostname} 失败: {str(e)}")
            # 如果当前DNS服务器失败，尝试下一个
            self._current_dns_index = (self._current_dns_index + 1) % len(self.TRUSTED_DNS_SERVERS)
            self._resolver = None  # 重置解析器，下次会使用新的DNS服务器
            return None
    
    async def resolve_discord_hosts(self) -> dict:
        """解析所有Discord相关域名"""
        resolved = {}
        for hostname in self.DISCORD_HOSTS:
            # 检查缓存
            cached = self._resolved_hosts.get(hostname)
            if cached and not cached.is_expired:
                resolved[hostname] = cached.ip
                continue
            
            # 解析新的IP
            ips = await self._resolve_host(hostname)
            if ips:
                # 使用第一个IP地址
                resolved[hostname] = ips[0]
                # 更新缓存
                self._resolved_hosts[hostname] = ResolvedHost(
                    ip=ips[0],
                    timestamp=datetime.now()
                )
                logger.info(f"已解析 {hostname} -> {ips[0]}")
            else:
                logger.warning(f"无法解析 {hostname}")
        
        self.last_resolved = datetime.now()
        return resolved
    
    def get_discord_api_url(self, path: str = '') -> str:
        """获取Discord API的URL，使用解析后的IP"""
        discord_ip = self._resolved_hosts.get('discord.com')
        if discord_ip and not discord_ip.is_expired:
            # 使用IP但保持HTTPS和Host header
            return f"https://{discord_ip.ip}{path}"
        return f"https://discord.com{path}"
    
    @property
    def current_dns_server(self) -> str:
        """获取当前使用的DNS服务器"""
        return self.TRUSTED_DNS_SERVERS[self._current_dns_index]

    def get_discord_ip(self) -> str:
        """获取Discord的IP地址"""
        if not self._resolved_hosts:
            raise RuntimeError("DNS解析尚未完成，请先调用resolve_discord_hosts()")
        
        # 返回discord.com的IP地址
        discord_host = self._resolved_hosts.get('discord.com')
        if not discord_host:
            raise RuntimeError("未找到Discord的IP地址")
            
        if isinstance(discord_host, ResolvedHost):
            return discord_host.ip
        return discord_host  # 如果已经是字符串形式的IP
        
    async def resolve_host(self, host: str) -> str:
        """解析单个主机名"""
        for dns_server in self.TRUSTED_DNS_SERVERS:
            try:
                logging.info(f"使用DNS服务器: {dns_server}")
                resolver = aiodns.DNSResolver(nameservers=[dns_server])
                result = await resolver.query(host, 'A')
                if result and result[0].host:
                    ip = result[0].host
                    logging.info(f"已解析 {host} -> {ip}")
                    return ip
            except Exception as e:
                logging.warning(f"使用DNS服务器 {dns_server} 解析 {host} 失败: {str(e)}")
                continue
        raise RuntimeError(f"无法解析主机名: {host}")

# 创建全局实例
dns_resolver = DNSResolver() 