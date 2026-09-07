"""核心：基于 browser-use 的「计算机使用」网页结构化数据采集 Agent。

用法（同步封装见 extract_sync）：
    result = await extract("https://arxiv.org/list/cs.AI/recent", "提取论文标题和作者")
    result = await extract(url, goal="", fields=["title", "authors", "date"])

两种模式：
1. fields 模式 —— 动态构造 pydantic schema（output_model_schema），browser-use 强制模型
   按 schema 输出结构化结果，结果从 history.structured_output 直接拿，最稳。
2. goal 模式 —— 自由文本目标，从 history.final_result() 里尽量解析 JSON，拿不到则回退原始文本。
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, create_model

from browser_use import Agent, Browser

from . import config


@dataclass
class ExtractionResult:
    """一次采集的完整结果，方便序列化成 JSON 返回给 CLI / HTTP。"""
    success: bool
    data: Any = None                 # 结构化结果（dict / 原始文本）
    raw: str = ""                    # agent 的最终文本
    steps: int = 0
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)
    usage: dict | None = None          # token 统计（prompt/completion/total + 可选 cost）

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "raw": self.raw,
            "steps": self.steps,
            "duration_s": round(self.duration_s, 2),
            "errors": self.errors,
            "usage": self.usage,
        }


def _build_schema_model(fields: list[str]) -> type[BaseModel] | None:
    """由字段列表动态构造 `Extraction{items: list[Item{<field>: str}]}`。

    browser-use 会把这个 schema 注入 system prompt 并强制结构化输出。
    """
    cleaned = [f.strip() for f in fields if f and f.strip()]
    if not cleaned:
        return None
    item_model = create_model("Item", **{f: (str, ...) for f in cleaned})
    return create_model("Extraction", items=(list[item_model], ...))


def _try_parse_json(text: str) -> Any:
    """从模型输出文本里尽力提取 JSON（容忍前后夹带的说明文字）。"""
    if not text:
        return None
    text = text.strip()
    # 去掉 ```json ... ``` 代码块围栏
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    for candidate in (text,):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # 取首个 [ 或 { 到最后一个 ] 或 } 的子串再试
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if starts:
        start = min(starts)
        closer = "]" if text[start] == "[" else "}"
        end = text.rfind(closer)
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _usage_dict(history) -> dict | None:
    """从 history.usage（browser_use UsageSummary）提取 token/cost 统计。"""
    usage = getattr(history, "usage", None)
    if usage is None:
        return None
    d = {
        "prompt_tokens": int(getattr(usage, "total_prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "total_completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
    cost = float(getattr(usage, "total_cost", 0.0) or 0.0)
    if cost:
        d["cost_usd"] = round(cost, 6)
    return d


# 并发控制：限制同时开多少个浏览器实例（FastAPI 并发请求时防资源耗尽）。
_semaphore: "asyncio.Semaphore | None" = None


def _get_semaphore() -> "asyncio.Semaphore":
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(config.max_concurrency())
    return _semaphore


async def extract(
    url: str,
    goal: str = "",
    fields: list[str] | None = None,
    max_steps: int = 25,
    headless: bool | None = None,
    use_vision: bool | None = None,
) -> ExtractionResult:
    """打开 url 并完成采集。fields 非空走结构化模式，否则走自由目标模式。

    use_vision=True 走视觉模式（需 QWEN_API_KEY/GLM_API_KEY 配 VLM）；None 读 .env 默认。
    """
    use_vision_eff = config.use_vision() if use_vision is None else use_vision
    llm = config.build_llm(use_vision=use_vision_eff)
    schema_model = _build_schema_model(fields or [])

    # URL 交给 initial_actions 显式导航，不写进 task：
    # browser-use 的 directly_open_url 用朴素正则抽 URL，中文标点会被吞进 URL 造成畸形导航。
    if schema_model is not None:
        task = f"提取页面中主要条目（列表/卡片）的以下字段：{', '.join(fields)}。"
    else:
        task = f"{goal or '提取页面核心信息'}。以 JSON 形式输出结果。"

    async with _get_semaphore():  # 并发上限：最多 MAX_CONCURRENCY 个浏览器实例同时跑
        browser = Browser(
            headless=config.headless() if headless is None else headless,
            executable_path=config.browser_executable(),
            enable_default_extensions=False,  # 关闭 uBlock 等扩展：默认会联网下载，国内连不上源会卡死启动
        )
        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            use_vision=use_vision_eff,
            use_thinking=False,          # DeepSeek deepseek-chat 无推理模式，显式关闭
            output_model_schema=schema_model,
            max_actions_per_step=5,
            initial_actions=[{"navigate": {"url": url, "new_tab": False}}],
            # Qwen-VL 等模型有把 JSON 包进 ``` 代码块的坏习惯，dont_force_structured_output
            # 模式下 browser-use 按纯 JSON 解析会崩，这里显式禁止围栏。
            extend_system_message=(
                "CRITICAL: Always respond with raw JSON only. Never wrap your response "
                "in markdown code fences (```) or add any text outside the JSON object."
            ),
        )

        try:
            history = await agent.run(max_steps=max_steps)

            data: Any = None
            raw = history.final_result() or ""

            if schema_model is not None and history.structured_output is not None:
                data = history.structured_output.model_dump(mode="json")
            else:
                data = _try_parse_json(raw)
                if data is None:
                    data = raw

            steps = getattr(history, "number_of_steps", 0)
            duration = getattr(history, "total_duration_seconds", 0.0)
            errs = getattr(history, "errors", [])
            return ExtractionResult(
                success=bool(history.is_successful),
                data=data,
                raw=raw,
                steps=steps() if callable(steps) else steps,
                duration_s=float(duration() if callable(duration) else duration or 0.0),
                errors=[str(e) for e in (errs() if callable(errs) else errs) if e],
                usage=_usage_dict(history),
            )
        finally:
            try:
                await browser.close()
            except Exception:
                pass


def extract_sync(
    url: str,
    goal: str = "",
    fields: list[str] | None = None,
    max_steps: int = 25,
    headless: bool | None = None,
    use_vision: bool | None = None,
) -> ExtractionResult:
    """同步封装，供脚本/CLI 直接调用。"""
    return asyncio.run(
        extract(url, goal=goal, fields=fields, max_steps=max_steps,
                headless=headless, use_vision=use_vision)
    )
