"""配置加载：config.toml（订阅源与参数）+ .env（密钥）。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.toml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

VALID_BOOTSTRAP = {"mark", "catch_up"}
VALID_PROVIDERS = {"auto", "google", "llm", "none"}


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str
    lang: str = ""  # "zh" 表示中文源，跳过翻译；留空则自动检测


@dataclass(frozen=True)
class PollConfig:
    interval_minutes: int = 30
    max_age_hours: int = 72
    bootstrap: str = "mark"
    request_timeout_seconds: int = 20
    retention_days: int = 14


@dataclass(frozen=True)
class TranslationConfig:
    provider: str = "auto"
    summary_chars: int = 400


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


@dataclass(frozen=True)
class AppConfig:
    poll: PollConfig
    translation: TranslationConfig
    llm: LLMConfig
    feeds: list[FeedConfig] = field(default_factory=list)
    webhook_url: str = ""
    llm_api_key: str = ""
    proxy: str = ""
    data_dir: Path = DEFAULT_DATA_DIR

    @property
    def history_path(self) -> Path:
        return self.data_dir / "history.json"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "bot.log"

    @property
    def effective_provider(self) -> str:
        """auto：配置了 LLM 且有 key 则用 llm，否则用免费 google。"""
        if self.translation.provider != "auto":
            return self.translation.provider
        if self.llm.enabled and self.llm_api_key:
            return "llm"
        return "google"


def load_config(config_path: Path | str | None = None) -> AppConfig:
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件: {config_path}")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    poll = PollConfig(**raw.get("poll", {}))
    translation = TranslationConfig(**raw.get("translation", {}))
    llm = LLMConfig(**raw.get("llm", {}))

    if poll.bootstrap not in VALID_BOOTSTRAP:
        raise ValueError(f"poll.bootstrap 必须是 {VALID_BOOTSTRAP} 之一，当前: {poll.bootstrap!r}")
    if translation.provider not in VALID_PROVIDERS:
        raise ValueError(f"translation.provider 必须是 {VALID_PROVIDERS} 之一，当前: {translation.provider!r}")

    feeds = [FeedConfig(**item) for item in raw.get("feeds", [])]
    if not feeds:
        raise ValueError("config.toml 中没有配置任何订阅源 [[feeds]]")

    load_dotenv(PROJECT_ROOT / ".env")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    llm_api_key = os.getenv("LLM_API_KEY", "").strip()
    # 代理：优先 config.toml，其次环境变量
    proxy = raw.get("http", {}).get("proxy", "").strip() or os.getenv("HTTPS_PROXY", "").strip()

    # 可选：config.toml 顶层 data_dir（相对路径相对于项目根）
    custom_data_dir = raw.get("data_dir", "").strip()
    data_dir = Path(custom_data_dir) if custom_data_dir else DEFAULT_DATA_DIR
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir

    return AppConfig(
        poll=poll,
        translation=translation,
        llm=llm,
        feeds=feeds,
        webhook_url=webhook_url,
        llm_api_key=llm_api_key,
        proxy=proxy,
        data_dir=data_dir,
    )
