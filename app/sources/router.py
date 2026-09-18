"""双引擎路由：根据采集目标选择数据源。

- 平台任务（target 是 MediaCrawler 导出文件，或 extra 里给了 file）→ MediaCrawlerSource
- 通用 URL → BrowserUseSource

覆盖策略：高频标准平台走平台专用数据（快、量大），长尾/多变/需视觉的页面走通用浏览器
引擎（零选择器、改版不崩）——这就是「双引擎采集服务」的覆盖面与成本路由。
"""
from __future__ import annotations

from .base import CollectionRequest, DataSource
from .browser_use import BrowserUseSource
from .mediacrawler import MediaCrawlerSource

# MediaCrawler 覆盖的平台（路由 + 服务端 /sources 展示用）
PLATFORMS = {"xhs", "douyin", "kuaishou", "bilibili", "weibo", "tieba", "zhihu"}


def route(request: CollectionRequest) -> DataSource:
    """按请求内容返回对应采集引擎。"""
    is_platform_file = bool(request.extra.get("file")) or request.target.lower().endswith(
        (".json", ".jsonl", ".csv")
    )
    if request.platform in PLATFORMS and is_platform_file:
        return MediaCrawlerSource()
    return BrowserUseSource()
