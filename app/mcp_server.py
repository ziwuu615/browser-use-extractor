"""MCP server：把网页结构化采集能力暴露为 MCP 工具。

任何 MCP 客户端（Claude Desktop / Cursor / Claude Code 等）都能拉起本服务并调用：
    extract_web_data(url, fields)   —— 按字段列表抽取结构化数据（schema 强制）
    extract_web_goal(url, goal)     —— 按自然语言目标抽取（自由形式）

运行（stdio 传输，供 MCP 客户端以子进程方式拉起）：
    python -m app.mcp_server

说明：本 venv 装的是 mcp 2.x，FastMCP 已改名为 MCPServer（from mcp.server.mcpserver）。
"""
from mcp.server.mcpserver import MCPServer

from .extractor import extract

server = MCPServer(
    name="web-extractor",
    description="网页结构化数据采集 Agent：打开任意网页，按字段或自然语言目标抽取成 JSON。",
)


@server.tool()
async def extract_web_data(
    url: str,
    fields: list[str],
    max_steps: int = 20,
    use_vision: bool = False,
) -> dict:
    """打开网页并按字段列表抽取结构化数据（pydantic schema 强制，结果最稳）。

    Args:
        url: 目标网页 URL，例如 https://arxiv.org/list/cs.AI/recent
        fields: 要抽取的字段列表，例如 ["title", "authors", "date"]
        max_steps: Agent 最大步数（默认 20）
        use_vision: 视觉模式（需 QWEN_API_KEY/GLM_API_KEY），默认 False 走 DOM 文本模式
    """
    result = await extract(url=url, fields=fields, max_steps=max_steps, use_vision=use_vision or None)
    return result.to_dict()


@server.tool()
async def extract_web_goal(
    url: str,
    goal: str,
    max_steps: int = 20,
    use_vision: bool = False,
) -> dict:
    """打开网页并按自然语言目标抽取数据（自由形式，结果尽量解析成 JSON）。

    Args:
        url: 目标网页 URL
        goal: 自然语言采集目标，例如 "提取页面上所有商品的名称和价格"
        max_steps: Agent 最大步数（默认 20）
        use_vision: 视觉模式，默认 False
    """
    result = await extract(url=url, goal=goal, max_steps=max_steps, use_vision=use_vision or None)
    return result.to_dict()


if __name__ == "__main__":
    server.run()
