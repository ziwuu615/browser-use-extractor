# 🧭 网页结构化数据采集 Agent（Computer Use）

基于 **[browser-use](https://github.com/browser-use/browser-use)**（110k+ stars）二次开发的「计算机使用」Agent：用自然语言描述目标，Agent 自动打开浏览器、导航、定位页面元素并抽取成**结构化 JSON**。这是 2026 年 Agent 领域最前沿的 **Computer Use / 浏览器智能体** 方向，与 OpenAI Operator、Claude Computer Use 同类能力。

> 配套项目：[smolagents 代码库/PR 智能问答](https://github.com/ziwuu615/smolagents)（文本 RAG + MCP + 多智能体）。本项目补齐「视觉/浏览器交互 + 结构化抽取」这一能力维度，两者共用 MCP / FastAPI / 评测 的工程范式。

---

## 核心特性

- **自然语言 → 结构化数据**：输入 URL + 字段（或自由目标），输出 JSON。
- **双模式抽取**：
  - `fields` 模式 —— 用 pydantic `create_model` **动态构造 schema**，强制模型按 schema 输出，结果直接反序列化成 typed 对象；
  - `goal` 模式 —— 自由文本目标，容错解析 JSON。
- **纯文本 / DOM 模式**：不依赖视觉模型，`deepseek-chat`（便宜、国内直连）即可跑通；切换 `QWEN_MODEL=qwen-vl-plus` 可升级为视觉模式。
- **三种入口**：CLI、FastAPI HTTP、Streamlit Web UI。
- **并发控制 + 结果导出**：`MAX_CONCURRENCY` 信号量限制并发浏览器实例数；CLI `--output/--format` 导出 JSON/CSV。
- **Docker 化**：Chromium + `--no-sandbox`，一键部署。

---

## 快速开始

```bash
# 1. 建 venv 并装依赖
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS 用 .venv/bin/python

# 2. 配 Key（复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY；无稳定版 Chrome 会自动用 Edge）
cp .env.example .env

# 3. 跑一条 CLI（低反爬真实网页：arXiv 论文列表）
.venv/Scripts/python -m app.cli "https://arxiv.org/list/cs.AI/recent" --fields title,authors
```

输出（节选）：

```json
{
  "success": true,
  "data": {
    "items": [
      {"title": "A Deep Generative Model for Synthesizing Labeled Wireless Signals",
       "authors": "Yuxiao Li, Keke Hu, Santiago Mazuelas, Yuan Shen"},
      {"title": "CUA-Universe: A Scalable and Dynamic Environment for Hybrid GUI+CLI Agents",
       "authors": "Haoting Shi, Wenhao Wang, ..."}
    ]
  },
  "steps": 2,
  "duration_s": 23.5
}
```

---

## 三种使用方式

### 1) CLI

```bash
python -m app.cli "URL" "采集目标（自然语言）"              # goal 模式
python -m app.cli "URL" --fields title,price,date           # 结构化 schema 模式
python -m app.cli "URL" --fields title,authors --max-steps 20 --headless 0
python -m app.cli "URL" --fields title,authors -o out.csv   # 导出 CSV（.json 后缀导出 JSON）
python -m app.cli "URL" --fields title,authors --format csv # 直接打印 CSV
```

### 2) HTTP（FastAPI）

```bash
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://arxiv.org/list/cs.AI/recent", "fields": ["title", "authors"]}'
```

### 3) Web UI（Streamlit）

```bash
streamlit run app/ui.py
```

### 4) Docker

```bash
docker build -t web-extractor .
docker run --rm -p 8000:8000 -e DEEPSEEK_API_KEY=sk-xxx web-extractor
```

---

## 视觉模式（VLM）

默认走 **DOM 文本模式**（`deepseek-chat`，便宜）。遇到纯文本 DOM 搞不定的页面（Canvas 渲染、验证码、复杂不规则布局）可开**视觉模式**——Agent 每步把页面截图（base64）喂给多模态模型。

```bash
# 1. .env 配置 VLM Key（二选一，国内直连）
QWEN_API_KEY=sk-xxx        # 通义 Qwen-VL（默认 qwen-vl-plus）
# 或 GLM_API_KEY=xxx       # 智谱 GLM-4V（默认 glm-4v-flash）

# 2. CLI 加 --vision
python -m app.cli "URL" --fields title,price --vision

# HTTP：POST /extract 的 body 加 "vision": true
# Web UI：勾选「视觉模式」
```

> 注意：browser-use 会自动把 DeepSeek 的 `use_vision` 强制置 False（DeepSeek 无视觉能力），所以视觉模式必须配 Qwen-VL / GLM-4V。视觉模式比 DOM 文本模式慢、贵（实测 arXiv 单任务 3 步 / 95s / 61k token，文本模式 3 步 / 29s / 52k token），适合纯文本 DOM 搞不定的页面。

---

## MCP Server

把采集能力暴露为 MCP 工具，任何 MCP 客户端（Claude Desktop / Cursor / Claude Code 等）都能调用：

- `extract_web_data(url, fields, max_steps, use_vision)` —— 按字段结构化抽取
- `extract_web_goal(url, goal, max_steps, use_vision)` —— 自然语言目标抽取

**Claude Desktop**（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "web-extractor": {
      "command": "C:\\Users\\zhaozhuweijia516\\Desktop\\browser_use\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"],
      "cwd": "C:\\Users\\zhaozhuweijia516\\Desktop\\browser_use"
    }
  }
}
```

**Claude Code**：

```bash
claude mcp add web-extractor -- .venv/Scripts/python.exe -m app.mcp_server
```

> 说明：本项目 venv 装的是 mcp **2.x**，`FastMCP` 已改名为 `MCPServer`（`from mcp.server.mcpserver import MCPServer`）。`mcp<2` 时代的老代码要照此迁移。

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  入口层      CLI (app/cli.py)  ·  FastAPI (app/server.py)  ·  Streamlit (app/ui.py)
├─────────────────────────────────────────────────────────────┤
│  编排层      app/extractor.py   —— 任务构造 / schema 动态生成 / 结果归一化
├─────────────────────────────────────────────────────────────┤
│  模型层      app/config.py      —— browser_use.ChatOpenAI（OpenAI 兼容）
│                                DeepSeek deepseek-chat / Qwen-VL（可切视觉）
├─────────────────────────────────────────────────────────────┤
│  浏览器层    browser_use 0.13  —— cdp-use 直连 Chromium/Edge（CDP 协议，非 Playwright）
└─────────────────────────────────────────────────────────────┘
```

---

## 技术要点 / 关键工程决策（踩坑记录）

这些是本项目从 0 到 1 过程中定位并解决的**真实兼容性问题**：

| # | 问题 | 根因 | 解决 |
|---|------|------|------|
| 1 | 启动 30s 超时、卡死 | browser-use 默认联网下载 uBlock Origin Lite 扩展，国内连不上源 | `enable_default_extensions=False` |
| 2 | DeepSeek 报 `This response_format type is unavailable` | DeepSeek 只支持 `response_format=json_object`，不支持 `json_schema` | `dont_force_structured_output=True` + `add_schema_to_system_prompt=True`（schema 写进提示词而非强制 response_format） |
| 3 | 导航到畸形 URL（任务文本被拼进 URL） | `directly_open_url` 用朴素正则抽 URL，中文标点被吞进 URL | 用 `initial_actions` 显式导航，URL 不进 task |
| 4 | 无稳定版 Chrome | Windows 机器只有 Edge / Canary | `executable_path` 指向 Edge（Chromium 内核走 CDP） |
| 5 | 结构化字段不可枚举 | 采集目标动态变化 | pydantic `create_model` 按字段动态构造 schema |
| 6 | 视觉模式 Qwen-VL 输出包 ``` 围栏 → 解析崩 | Qwen-VL 自由输出会把 JSON 包进 markdown 围栏（DeepSeek 不会） | Qwen-VL 走 browser-use 默认 `response_format=json_schema`（Qwen 支持、DeepSeek 不支持）强制干净 JSON |

> 版本说明：browser-use **0.13.x** 架构已重构——不再依赖 langchain / playwright，改为 **cdp-use**（Chrome DevTools Protocol）直连浏览器，LLM 用自带的 `browser_use.ChatOpenAI`。网上大量教程仍停留在 0.7.x 的旧 API，本项目直接对新版 API 做了适配。

---

## 目录结构

```
browser_use/
├── app/
│   ├── __init__.py
│   ├── config.py        # LLM（DeepSeek 文本 / Qwen-VL 视觉）+ 浏览器配置
│   ├── extractor.py     # 核心：ExtractionResult / extract() / 动态 schema
│   ├── cli.py           # CLI 入口
│   ├── server.py        # FastAPI
│   ├── ui.py            # Streamlit
│   ├── mcp_server.py    # MCP server（MCPServer，2 个工具）
│   └── eval.py          # 评测
├── benchmark/
│   └── web_tasks.json   # 评测集
├── .env.example
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## 评测

内置结构校验评测集（`benchmark/web_tasks.json`）：每条任务跑 Agent 后校验「agent 成功 + 条目数达标 + 每条字段完整非空」，统计步数 / 耗时 / token 成本（token 取自 browser-use 的 `history.usage`）。

```bash
python -m app.eval               # 跑全部
python -m app.eval --limit 2     # 快速验证前 2 条
python -m app.eval --headless 0  # 有头模式观察
```

实测（DeepSeek deepseek-chat，文本/DOM 模式，5 条 arXiv 列表页）：

| 指标 | 数值 |
|------|------|
| 成功率 | 5/5 = **100%** |
| 平均步数 | 4.4 |
| 平均耗时 | 45.0s |
| 平均 token | ~82k / 任务 |

## Roadmap

- [ ] 扩充评测集到更多站点类型（详情页 / 表单 / 翻页 / 登录）
- [ ] 暴露为 MCP server，让其他 Agent 直接调用「浏览器能力」
- [ ] OpenTelemetry trace 替代 browser-use 内置日志
- [ ] 并发：多 Browser 实例池 + 任务队列

---

## License

MIT
