"""已发送文章去重存储：JSON + 原子写入 + 按保留期清理。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .models import utc_now

logger = logging.getLogger(__name__)


class History:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = {}

    def load(self) -> "History":
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info("加载历史记录 %d 条", len(self._data))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("历史记录损坏，将重新初始化: %s", exc)
            backup = self.path.with_suffix(".corrupt.json")
            try:
                self.path.rename(backup)
                logger.warning("损坏的历史记录已备份到 %s", backup)
            except OSError:
                pass
            self._data = {}
        return self

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def mark(self, key: str, *, title: str, link: str, source: str) -> None:
        self._data[key] = {
            "title": title,
            "link": link,
            "source": source,
            "sent_at": utc_now().isoformat(),
        }

    def prune(self, retention_days: int) -> int:
        cutoff = utc_now().timestamp() - retention_days * 86400
        before = len(self._data)
        kept = {}
        for key, item in self._data.items():
            try:
                ts = item.get("sent_at", "")
                # 兼容旧的 epoch 形式
                if isinstance(ts, (int, float)):
                    age_ts = float(ts)
                else:
                    from datetime import datetime

                    age_ts = datetime.fromisoformat(ts).timestamp()
            except (ValueError, TypeError):
                age_ts = cutoff + 1  # 无法解析时间的保留
            if age_ts > cutoff:
                kept[key] = item
        self._data = kept
        removed = before - len(self._data)
        if removed:
            logger.info("清理 %d 条过期历史记录", removed)
        return removed

    def save(self) -> None:
        """临时文件 + os.replace 原子写入，避免崩溃时损坏 JSON。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
