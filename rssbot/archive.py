"""AGI Force 发布归档读取器。

读 Z:/.../briefing-archive/publish_YYYYMMDD_*.json，合并当天早晚两班，
按 URL 去重。条目已经过 GLM ≥7 分筛选且是中文精编：
  {title, summary, url, source_ids}
"""

from __future__ import annotations

import glob
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import ArchiveConfig

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    summary: str
    url: str
    source_ids: list[str] = field(default_factory=list)
    period: str = ""       # 早报/晚报，调试用

    def source_label(self, mapping: dict[str, str]) -> str:
        names = [mapping.get(sid, sid) for sid in self.source_ids]
        return "/".join(dict.fromkeys(names)) if names else "AGI Force"


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
                       urlencode(query), ""))


def load_publish_archive(cfg: ArchiveConfig, day: date) -> list[NewsItem]:
    pattern = str(Path(cfg.path) / f"publish_{day:%Y%m%d}_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"{day} 没有发布归档（查找 {pattern}）。当天 AGI Force 是否已运行？")

    by_url: dict[str, NewsItem] = {}
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("归档文件读取失败 %s: %s", path, exc)
            continue
        period = doc.get("period", "")
        for raw in doc.get("published_items", []):
            url = (raw.get("url") or "").strip()
            title = (raw.get("title") or "").strip()
            if not url or not title:
                continue
            key = normalize_url(url)
            if key in by_url:
                # 合并两班重复条目的来源标记
                existing = by_url[key]
                for sid in raw.get("source_ids", []):
                    if sid not in existing.source_ids:
                        existing.source_ids.append(sid)
                continue
            by_url[key] = NewsItem(
                title=title,
                summary=(raw.get("summary") or "").strip(),
                url=url,
                source_ids=list(raw.get("source_ids", [])),
                period=period,
            )

    items = list(by_url.values())
    logger.info("归档 %s：%d 个班次文件，去重后 %d 条", day, len(files), len(items))
    return items


# 来源频道显示名（与 skills-sync/sources_map.json 一致）
SOURCE_LABELS = {
    "S1": "创投前沿", "S2": "深度科技", "S3": "极客前线", "S4": "环球视野",
    "S5": "开发者生态", "S6": "前沿论文", "S7": "权威洞察", "S8": "AI精选",
    "S9": "社区热榜", "S10": "KOL追踪", "S11": "官方发布",
}
