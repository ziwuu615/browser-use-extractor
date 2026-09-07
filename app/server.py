"""FastAPI 服务：把「网页结构化数据采集」能力暴露为 HTTP 接口。

启动：
    uvicorn app.server:app --host 0.0.0.0 --port 8000

调用示例：
    curl -X POST http://127.0.0.1:8000/extract \
        -H "Content-Type: application/json" \
        -d '{"url": "https://arxiv.org/list/cs.AI/recent", "fields": ["title", "authors"]}'
"""
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .extractor import extract

app = FastAPI(title="网页结构化数据采集 Agent", version="0.1.0")


class ExtractRequest(BaseModel):
    url: str
    goal: str = ""                                # 自然语言采集目标（与 fields 二选一）
    fields: list[str] | None = None               # 结构化字段列表（走 schema 模式）
    max_steps: int = Field(default=25, ge=1, le=100)
    headless: bool | None = None                  # 不传则读 .env 的 HEADLESS
    vision: bool = False                          # True 走视觉模式（需 VLM Key）


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract")
async def extract_endpoint(req: ExtractRequest) -> dict[str, Any]:
    result = await extract(
        url=req.url,
        goal=req.goal,
        fields=req.fields,
        max_steps=req.max_steps,
        headless=req.headless,
        use_vision=req.vision or None,
    )
    return result.to_dict()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.server:app", host="0.0.0.0", port=8000, reload=True)
