"""数据源抽象层：统一「通用浏览器引擎」与「平台数据源」的采集接口。

设计目标：无论数据来自 browser-use 的自适应抽取，还是 MediaCrawler 等平台专用工具
导出的文件，都归一化成同一种 CollectedItem，交给下游统一落库 / 导出 / 分析。这一步把
项目从「单 URL 抽取工具」升级为「多数据源采集服务」——商业价值来自覆盖面，而不是单点能力。

各引擎实现见：
- browser_use.py   —— 通用自适应引擎（任意网页，自然语言驱动）
- mediacrawler.py  —— 平台数据适配器（读 MediaCrawler 导出的 CSV/JSON/SQLite）
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def content_id(data: dict) -> str:
    """按内容算稳定 ID（去重用）。

    同一批数据反复采集时，只要字段值不变，ID 就不变 → 落库时天然去重。
    """
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


@dataclass
class CollectedItem:
    """一条归一化后的采集记录。"""
    source: str                    # 引擎名："browser-use" / "mediacrawler"
    platform: str                  # 平台："web" / "xhs" / "douyin" / ...
    data: dict                     # 归一化字段（title/author/content/... 尽量对齐）
    native_id: str = ""            # 源平台原始 ID（无则用内容哈希），作去重键
    url: str = ""
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CollectionResult:
    """一次采集的完整结果，可序列化返回给 CLI / HTTP。"""
    source: str
    platform: str
    success: bool
    items: list[CollectedItem] = field(default_factory=list)
    raw: Any = None
    usage: dict | None = None
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "platform": self.platform,
            "success": self.success,
            "items": [it.to_dict() for it in self.items],
            "raw": self.raw,
            "usage": self.usage,
            "duration_s": round(self.duration_s, 2),
            "errors": self.errors,
        }


@dataclass
class CollectionRequest:
    """一次采集请求的通用描述，各 source 按需取用。"""
    target: str                    # URL（browser-use）或平台关键词/文件路径（平台源）
    platform: str = "web"          # 目标平台标识，路由用
    fields: list[str] | None = None
    goal: str = ""
    max_steps: int = 25
    use_vision: bool = False
    extra: dict = field(default_factory=dict)


class DataSource(ABC):
    """采集引擎抽象。每个实现负责一种数据来源。"""
    name: str = "base"

    @abstractmethod
    async def collect(self, request: CollectionRequest) -> CollectionResult:
        """执行一次采集，返回归一化结果。"""
        ...
