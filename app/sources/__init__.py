"""数据源抽象层：统一「通用浏览器引擎」与「平台数据源」的采集接口。"""
from .base import CollectionRequest, CollectionResult, CollectedItem, DataSource, content_id
from .browser_use import BrowserUseSource
from .mediacrawler import MediaCrawlerSource
from .router import PLATFORMS, route

__all__ = [
    "CollectionRequest",
    "CollectionResult",
    "CollectedItem",
    "DataSource",
    "content_id",
    "BrowserUseSource",
    "MediaCrawlerSource",
    "PLATFORMS",
    "route",
]
