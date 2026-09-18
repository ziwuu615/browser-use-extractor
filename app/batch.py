"""批量采集：读任务清单（manifest），并发执行，统一落库。

企业场景的核心：一次采一批、结果沉淀成数据资产，而不是一次一个 URL。
manifest 里每条任务两种形态：
  {"url": "...", "fields": [...], "goal": "..."}                     → 通用引擎
  {"platform": "xhs", "file": "data/xhs.json", "item_type": "note"}  → 平台数据适配器
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .sources.base import CollectionRequest
from .sources.router import route
from .store import Store


async def _run_one(task: dict, store: Store) -> dict:
    request = CollectionRequest(
        target=task.get("url") or task.get("file") or "",
        platform=task.get("platform", "web"),
        fields=task.get("fields"),
        goal=task.get("goal", ""),
        max_steps=int(task.get("max_steps", 25)),
        use_vision=bool(task.get("vision", False)),
        extra={k: v for k, v in task.items() if k in ("file", "item_type") and v},
    )
    source = route(request)
    result = await source.collect(request)
    store.save_run({
        "run_id": uuid.uuid4().hex,
        "source": result.source,
        "platform": result.platform,
        "target": request.target,
        "success": result.success,
        "n_items": len(result.items),
        "total_tokens": (result.usage or {}).get("total_tokens", 0),
        "duration_s": result.duration_s,
        "errors": result.errors,
    })
    inserted = store.upsert_items(result.items)
    return {
        "source": result.source,
        "platform": result.platform,
        "target": request.target,
        "success": result.success,
        "n_items": len(result.items),
        "inserted": inserted,
        "errors": result.errors,
    }


async def run_batch(tasks: list[dict], store: Store | None = None,
                    concurrency: int | None = None) -> dict:
    """并发跑一批任务并落库，返回汇总。单条失败不中断整批。"""
    store = store or Store(config.store_path())
    concurrency = max(1, concurrency or config.max_concurrency())
    sem = asyncio.Semaphore(concurrency)
    started = datetime.now(timezone.utc).isoformat()

    async def guard(task: dict) -> dict:
        async with sem:
            try:
                return await _run_one(task, store)
            except Exception as e:  # 单条异常兜底，不拖垮整批
                return {
                    "target": task.get("url") or task.get("file"),
                    "source": None,
                    "platform": task.get("platform", "web"),
                    "success": False,
                    "n_items": 0,
                    "inserted": 0,
                    "errors": [str(e)],
                }

    results = await asyncio.gather(*(guard(t) for t in tasks))
    ok = sum(1 for r in results if r.get("success"))
    return {
        "started_at": started,
        "total": len(tasks),
        "success": ok,
        "failed": len(tasks) - ok,
        "tasks": results,
        "store": store.counts(),
    }


def load_manifest(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"未找到任务清单 {path}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        return data["tasks"]
    if isinstance(data, list):
        return data
    raise SystemExit('manifest 需为 list 或 {"tasks": [...]}')
