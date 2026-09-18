"""FastAPI 服务：采集能力（单 URL + 批量）+ 数据落库查询。

启动：
    uvicorn app.server:app --host 0.0.0.0 --port 8000

接口：
    POST /extract      单 URL 抽取（向后兼容）
    POST /collect      批量采集（任务列表）→ SQLite
    GET  /query        查询已落库数据
    GET  /sources      列出可用引擎与平台
    GET  /stats        库统计
    GET  /health
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import config
from .batch import run_batch
from .extractor import extract
from .sources.router import PLATFORMS
from .store import Store

app = FastAPI(title="多数据源采集 Agent", version="0.2.0")

_store = Store(config.store_path())


# ---- 鉴权：API_KEY 非空则启用 ----
async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    key = config.api_key()
    if key and x_api_key != key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


class ExtractRequest(BaseModel):
    url: str
    goal: str = ""
    fields: list[str] | None = None
    max_steps: int = Field(default=25, ge=1, le=100)
    headless: bool | None = None
    vision: bool = False


class Task(BaseModel):
    url: str | None = None
    goal: str = ""
    fields: list[str] | None = None
    platform: str = "web"
    file: str | None = None
    item_type: str | None = None
    max_steps: int = Field(default=25, ge=1, le=100)
    vision: bool = False


class CollectRequest(BaseModel):
    tasks: list[Task]
    concurrency: int | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sources")
async def sources() -> dict[str, Any]:
    return {
        "sources": ["browser-use", "mediacrawler"],
        "platforms": sorted(PLATFORMS),
        "store": config.store_path(),
    }


@app.post("/extract")
async def extract_endpoint(req: ExtractRequest) -> dict[str, Any]:
    result = await extract(url=req.url, goal=req.goal, fields=req.fields,
                           max_steps=req.max_steps, headless=req.headless,
                           use_vision=req.vision or None)
    return result.to_dict()


@app.post("/collect")
async def collect_endpoint(req: CollectRequest,
                           _: None = Depends(require_api_key)) -> dict[str, Any]:
    tasks = [t.model_dump(exclude_none=True) for t in req.tasks]
    return await run_batch(tasks, store=_store, concurrency=req.concurrency)


@app.get("/query")
async def query_endpoint(source: str | None = None, platform: str | None = None,
                         limit: int = 20,
                         _: None = Depends(require_api_key)) -> dict[str, Any]:
    rows = _store.query(source=source, platform=platform, limit=limit)
    return {"count": len(rows), "items": rows}


@app.get("/stats")
async def stats_endpoint(_: None = Depends(require_api_key)) -> dict[str, Any]:
    return _store.counts()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.server:app", host="0.0.0.0", port=8000, reload=True)
