"""配置加载：config.toml（参数与订阅源）+ .env（密钥）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.10（ITX Ubuntu 22.04）
    import tomli as tomllib

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.toml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

VALID_BOOTSTRAP = {"mark", "catch_up"}
VALID_PROVIDERS = {"auto", "google", "llm", "none"}


# ---------- 旧 RSS 管线（rss 子命令，默认关闭）----------

@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str
    lang: str = ""


@dataclass(frozen=True)
class PollConfig:
    interval_minutes: int = 30
    max_age_hours: int = 72
    bootstrap: str = "mark"
    request_timeout_seconds: int = 20
    retention_days: int = 14
    enrich_summaries: bool = True


@dataclass(frozen=True)
class TranslationConfig:
    provider: str = "auto"
    summary_chars: int = 400


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = True
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


# ---------- 3.0：共脑问答 + 选题编辑简报 ----------

@dataclass(frozen=True)
class BridgeConfig:
    base_url: str = "http://192.168.5.33:9100"
    collection: str = "knowledge-base-vectors"
    token_file: str = "D:/Hermes/projects/local-data-bridge/config/bridge-client-pc.yaml"
    top_k: int = 6
    timeout_seconds: int = 30


@dataclass(frozen=True)
class ArchiveConfig:
    # AGI Force 发布归档目录（publish_YYYYMMDD_HHMMSS.json）
    path: str = "Z:/jovi工作目录/briefing-archive"
    lookback_days: int = 1


@dataclass(frozen=True)
class BriefingConfig:
    enabled: bool = True
    time: str = "20:15"          # 本机本地时间，消费当天 AGI Force 早晚两班
    watch_n: int = 6             # 📌 值得关注条数
    inspiration_n: int = 2       # ✍️ 写作灵感条数


@dataclass(frozen=True)
class BotConfig:
    channel_id: int = 0          # 仅响应/推送此频道（兼容旧配置；0 表示不限制）
    channel_ids: tuple[int, ...] = ()  # 允许的多个频道

    @property
    def allowed_channel_ids(self) -> frozenset[int]:
        ids = set(self.channel_ids)
        if self.channel_id:
            ids.add(self.channel_id)
        return frozenset(ids)


@dataclass(frozen=True)
class LegacyRSSConfig:
    enabled: bool = False        # 旧 2.0 RSS 实时推送与 AGI Force 重复，默认关闭


@dataclass(frozen=True)
class AppConfig:
    # 旧 RSS 管线
    poll: PollConfig = PollConfig()
    translation: TranslationConfig = TranslationConfig()
    llm: LLMConfig = LLMConfig()
    feeds: list[FeedConfig] = field(default_factory=list)
    # 3.0
    bridge: BridgeConfig = BridgeConfig()
    archive: ArchiveConfig = ArchiveConfig()
    briefing: BriefingConfig = BriefingConfig()
    bot: BotConfig = BotConfig()
    legacy_rss: LegacyRSSConfig = LegacyRSSConfig()
    # 密钥/运行环境
    webhook_url: str = ""
    bot_token: str = ""
    llm_api_key: str = ""
    bridge_token: str = ""
    proxy: str = ""
    data_dir: Path = DEFAULT_DATA_DIR

    @property
    def history_path(self) -> Path:
        return self.data_dir / "history.json"

    @property
    def digest_history_path(self) -> Path:
        return self.data_dir / "digest_history.json"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "intel.db"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "bot.log"

    @property
    def effective_provider(self) -> str:
        """旧 RSS 管线的翻译引擎选择。"""
        if self.translation.provider != "auto":
            return self.translation.provider
        if self.llm.enabled and self.llm_api_key:
            return "llm"
        return "google"

    @property
    def llm_ready(self) -> bool:
        return self.llm.enabled and bool(self.llm_api_key)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 TOML 段（override 覆盖 base；[[feeds]] 等列表整体替换）。"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _section(raw: dict, name: str) -> dict:
    return raw.get(name, {}) or {}


HERMES_ENV = Path(os.path.expandvars(r"%LOCALAPPDATA%/hermes/.env"))


def _read_hermes_key(name: str) -> str:
    """rssbot 自己的 .env 没配 key 时，回退读 hermes 的密钥（本机同一用户）。"""
    try:
        for line in HERMES_ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _read_bridge_token(token_file: str) -> str:
    """从 local-data-bridge 的客户端 yaml 解析 token（key 不在 .env 时用）。"""
    import re

    try:
        text = Path(token_file).read_text(encoding="utf-8")
        m = re.search(r'token:\s*["\']?([^"\'\s]+)', text)
        return m.group(1) if m else ""
    except OSError:
        return ""


def load_config(config_path: Path | str | None = None) -> AppConfig:
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件: {config_path}")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    # 机器本地覆盖（config.local.toml，不进 git）：ITX 上用它改路径/代理/频道等
    local_path = config_path.with_name("config.local.toml")
    if local_path.exists():
        with open(local_path, "rb") as f:
            raw = _deep_merge(raw, tomllib.load(f))

    poll = PollConfig(**_section(raw, "poll"))
    translation = TranslationConfig(**_section(raw, "translation"))
    llm = LLMConfig(**_section(raw, "llm"))
    bridge = BridgeConfig(**_section(raw, "bridge"))
    archive = ArchiveConfig(**_section(raw, "archive"))
    briefing = BriefingConfig(**_section(raw, "briefing"))
    legacy_rss = LegacyRSSConfig(**_section(raw, "rss"))

    bot_raw = _section(raw, "bot")
    bot_raw = {k: v for k, v in bot_raw.items() if k in BotConfig.__dataclass_fields__}
    # .env 兼容单频道
    channel_env = os.getenv("DISCORD_CHANNEL_ID", "").strip()
    if channel_env and not bot_raw.get("channel_id") and not bot_raw.get("channel_ids"):
        bot_raw["channel_id"] = int(channel_env)
    channel_ids_env = os.getenv("DISCORD_CHANNEL_IDS", "").strip()
    if channel_ids_env and not bot_raw.get("channel_ids"):
        bot_raw["channel_ids"] = tuple(int(x) for x in channel_ids_env.split(",") if x.strip())
    bot = BotConfig(**bot_raw)

    if poll.bootstrap not in VALID_BOOTSTRAP:
        raise ValueError(f"poll.bootstrap 必须是 {VALID_BOOTSTRAP} 之一")
    if translation.provider not in VALID_PROVIDERS:
        raise ValueError(f"translation.provider 必须是 {VALID_PROVIDERS} 之一")

    feeds = [FeedConfig(**item) for item in raw.get("feeds", [])]

    # 从 cwd 向上查找 .env（部署目录自洽；本地开发也命中项目根）
    load_dotenv()
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    bot_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    llm_api_key = os.getenv("LLM_API_KEY", "").strip() or _read_hermes_key("DEEPSEEK_API_KEY")
    bridge_token = (
        os.getenv("BRIDGE_TOKEN", "").strip()
        or _read_hermes_key("BRIDGE_TOKEN")
        or _read_bridge_token(bridge.token_file)
    )
    proxy = _section(raw, "http").get("proxy", "").strip() or os.getenv("HTTPS_PROXY", "").strip()

    custom_data_dir = raw.get("data_dir", "").strip()
    data_dir = Path(custom_data_dir) if custom_data_dir else DEFAULT_DATA_DIR
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir

    return AppConfig(
        poll=poll,
        translation=translation,
        llm=llm,
        feeds=feeds,
        bridge=bridge,
        archive=archive,
        briefing=briefing,
        bot=bot,
        legacy_rss=legacy_rss,
        webhook_url=webhook_url,
        bot_token=bot_token,
        llm_api_key=llm_api_key,
        bridge_token=bridge_token,
        proxy=proxy,
        data_dir=data_dir,
    )
