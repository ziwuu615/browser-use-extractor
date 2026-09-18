"""通用引擎：把现有 browser-use 抽取能力包装成 DataSource。

覆盖平台专用引擎（MediaCrawler 等）顾不到的：长尾站点、结构多变页面、需要视觉理解的页面。
这是本项目「零选择器、改版不崩」的差异化卖点。
"""
from __future__ import annotations

from ..extractor import extract
from .base import CollectionRequest, CollectionResult, CollectedItem, DataSource, content_id


class BrowserUseSource(DataSource):
    name = "browser-use"

    async def collect(self, request: CollectionRequest) -> CollectionResult:
        result = await extract(
            url=request.target,
            goal=request.goal,
            fields=request.fields,
            max_steps=request.max_steps,
            use_vision=request.use_vision or None,
        )

        items: list[CollectedItem] = []
        data = result.data
        rows = data.get("items") if isinstance(data, dict) else None
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    items.append(CollectedItem(
                        source=self.name,
                        platform=request.platform or "web",
                        data=r,
                        native_id=content_id(r),
                        url=request.target,
                    ))
        elif isinstance(data, dict) and data:
            items.append(CollectedItem(
                source=self.name,
                platform=request.platform or "web",
                data=data,
                native_id=content_id(data),
                url=request.target,
            ))

        return CollectionResult(
            source=self.name,
            platform=request.platform or "web",
            success=result.success,
            items=items,
            raw=data,
            usage=result.usage,
            duration_s=result.duration_s,
            errors=result.errors,
        )
