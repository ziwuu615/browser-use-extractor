# 🧭 多源数据采集 Agent（Dual-Engine Data Collection）

基于 **[browser-use](https://github.com/browser-use/browser-use)**（110k+ stars）的「计算机使用」采集引擎，叠加**平台数据适配层**，把分散在「各大平台 + 长尾网站」的数据，统一采集、归一化、落库成**结构化数据资产**。

一句话：**输入 URL 或平台关键词，输出去重后的结构化数据（SQLite）**，供选品、竞品监控、市场调研、垂直数据服务等场景直接消费。

---

## 解决什么问题

企业做数据采集通常卡在三处：

| 痛点 | 本项目怎么解 |
|------|------------|
| **覆盖面**：数据散在 7 大平台和无数长尾网站，要攒一堆爬虫脚本 | **双引擎**：高频标准平台走平台数据（快、量大），长尾/多变/需视觉的页面走 browser-use 通用引擎（零选择器、改版不崩）——一套接口覆盖全网 |
| **维护成本**：页面一改版，写死的选择器就崩，得持续返工 | browser-use 用自然语言描述目标，不依赖具体 DOM 选择器 |
| **交付形态**：多数工具采完即丢，无法沉淀、查询、对账 | **批量 + 落库**：一个任务清单跑一批，结果进 SQLite（去重、可查询、记录 token 成本） |

## 一个具体场景（电商竞品监控）

> 监控「无线蓝牙耳机」：商品列表页（价格/评分）走 browser-use 通用引擎；小红书关键词数据走平台适配器归一化——统一落库，之后按平台/时间查询、对比。

---

## 核心特性

- **双引擎采集**
  - `browser-use` 通用引擎：自然语言 → 结构化 JSON；DOM 文本 / 视觉双模式，按页面类型切换以控制成本。
  - `mediacrawler` 平台适配器：读 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 等工具导出的 CSV/JSON/JSONL，按列映射归一化。
- **批量任务 + 落库**：`python -m app.collect run -m manifest.json`，并发执行、SQLite 去重持久化。
- **成本可观测**：每次任务记录步数 / 耗时 / token。
- **四入口**：CLI（单条 + 批量）/ FastAPI / Streamlit / MCP。
- **Docker 化**。

---

## 快速开始

```bash
# 1. 建 venv 并装依赖
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS 用 .venv/bin/python

# 2. 配 Key（复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY；无稳定版 Chrome 会自动用 Edge）
cp .env.example .env

# 3. 冒烟测试（低反爬页面，确认链路通）
.venv/Scripts/python -m app.cli "https://arxiv.org/list/cs.AI/recent" --fields title,authors

# 4. 批量采集（企业场景：一批任务 + 落库）
.venv/Scripts/python -m app.collect run -m examples/manifest.example.json
.venv/Scripts/python -m app.collect stats
.venv/Scripts/python -m app.collect query --platform xhs --limit 20
```

---

## 使用方式

### 1) CLI —— 单条

```bash
python -m app.cli "URL" "采集目标（自然语言）"              # goal 模式
python -m app.cli "URL" --fields title,price,rating         # 结构化 schema 模式
python -m app.cli "URL" --fields title,price --vision       # 视觉模式
python -m app.cli "URL" --fields title,price -o out.csv     # 导出 CSV
```

### 2) CLI —— 批量（落库）

```bash
python -m app.collect run -m examples/manifest.example.json
python -m app.collect query --platform xhs --limit 20
python -m app.collect stats
```

manifest 里每条任务两种形态：

```json
{
  "tasks": [
    {"url": "https://www.amazon.com/s?k=wireless+earbuds", "fields": ["title", "price", "rating"]},
    {"platform": "xhs", "file": "examples/mediacrawler_xhs_sample.json", "item_type": "note"}
  ]
}
```

### 3) HTTP（FastAPI）

```bash
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/extract` | 单 URL 抽取（向后兼容） |
| POST | `/collect` | 批量采集 → SQLite |
| GET | `/query?platform=xhs` | 查询已落库数据 |
| GET | `/sources` | 列出引擎与平台 |
| GET | `/stats` | 库统计 |

设 `API_KEY` 后，`/collect` `/query` `/stats` 需要请求头 `X-API-Key`。

### 4) Web UI（Streamlit） & Docker

```bash
streamlit run app/ui.py
docker build -t web-extractor . && docker run --rm -p 8000:8000 -e DEEPSEEK_API_KEY=sk-xxx web-extractor
```

---

## 双引擎架构

```
                         ┌────────────────────────────┐
                         │  入口层  CLI / FastAPI / Streamlit / MCP
                         └──────────────┬─────────────┘
                                        │  CollectionRequest
                     ┌──────────────────┴──────────────────┐
                     │            app/sources/router.py     │  ← 按目标选择引擎
          ┌──────────┴───────────┐            ┌─────────────┴────────────┐
          │ BrowserUseSource      │            │ MediaCrawlerSource        │
          │ 通用自适应引擎          │            │ 平台数据适配器             │
          │ (browser-use + CDP)   │            │ (读导出文件 + 列映射)       │
          │ 长尾/多变/需视觉页面    │            │ 7 平台：xhs/douyin/...    │
          └──────────┬───────────┘            └─────────────┬────────────┘
                     └──────────────────┬──────────────────┘
                                        │  归一化 CollectedItem
                     ┌──────────────────┴──────────────────┐
                     │           app/store.py（SQLite）      │  ← 去重 / 持久化 / 查询
                     │        items 表 + runs 表（成本对账）  │
                     └─────────────────────────────────────┘
```

- **`app/sources/`** 数据源抽象层：`DataSource` 接口 + 两个引擎实现 + 路由。
- **`app/store.py`** SQLite 落库：`items` 按 `(source, platform, native_id)` 唯一约束去重；`runs` 记录每次任务的条数/token/耗时。
- **`app/batch.py`** 批量编排：manifest → 路由 → 并发执行 → 落库。

---

## 平台数据适配（MediaCrawler 集成）

平台数据由 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 独立导出（CSV/JSON/JSONL），本项目的 `MediaCrawlerSource` 读入并按列映射归一化，与 browser-use 的产出汇入同一张表。

- **为什么是「读导出文件」而不是「运行时调用」**：MediaCrawler 需要扫码登录、平台风控、IP 代理池，是独立运行的工具，本项目不 vendor 其代码，只消费它的导出结果。
- **字段映射（小红书笔记）**：`note_id→id`、`title→title`、`desc→content`、`user.nickname→author`、`liked_count→like_count`、`collected_count→collect_count`、`time→publish_time`、`tag_list→tags` … 未覆盖的字段透传。
- **合规边界**：MediaCrawler 采用 **NON-COMMERCIAL LEARNING LICENSE（仅学习/研究）**。本项目仅把它当作「数据文件的其中一种来源」接入；商业化数据源应改用合规 API 或自有数据。

---

## 视觉模式（VLM）

默认走 **DOM 文本模式**（`deepseek-chat`，便宜）。遇到纯文本 DOM 搞不定的页面（Canvas 渲染、验证码、复杂不规则布局）可开**视觉模式**——Agent 每步把页面截图（base64）喂给多模态模型。

```bash
python -m app.cli "URL" --fields title,price --vision    # 需 QWEN_API_KEY 或 GLM_API_KEY
```

> 成本对比（实测）：DOM 文本模式 ~29s/52k token，视觉模式 ~95s/61k token。**只在文本搞不定时才上视觉，是成本控制的关键**。

---

## 反爬与合规

Computer Use 方式本身具备天然的反爬优势：控制真实浏览器、带真实指纹、执行 JS，大量针对「脚本请求」的前端反爬对它无效。其余反爬按**分层治理**落地：

| 层 | 状态 | 实现 |
|----|------|------|
| robots.txt 合规 | ✅ | 采集前自动检查 `robots.txt`，被禁止则跳过（`app/robots.py`，`ROBOTS_CHECK` 开关） |
| 并发限流 | ✅ | `MAX_CONCURRENCY` 信号量限制并发浏览器实例 |
| 域名限流 | ✅ | 同域名两次采集保持最小间隔（`app/humanize.py`，`RATE_LIMIT_INTERVAL`） |
| IP 代理池 | ✅ | 多代理轮换（`app/proxy.py`，`PROXY` / `PROXY_POOL` / `PROXY_FILE`） |
| 行为拟人化 | ✅ | 动作间随机延迟 + 可选自定义 UA（`app/humanize.py`，`HUMANIZE`） |
| 验证码/强对抗 | 🚫 边界 | 识别型验证码用视觉模式；滑块 / reCAPTCHA 不硬破，换数据源 |

合规原则：只采集公开数据、遵守 robots.txt 与站点条款、控制采集频率；强对抗商业站点用合规数据源（平台适配层或合规 API）接入。

---

## 技术要点 / 关键工程决策（踩坑记录）

| # | 问题 | 根因 | 解决 |
|---|------|------|------|
| 1 | 启动 30s 超时卡死 | browser-use 默认联网下载 uBlock 扩展，国内连不上源 | `enable_default_extensions=False` |
| 2 | DeepSeek 报 `response_format type is unavailable` | DeepSeek 只支持 `json_object`，不支持 `json_schema` | `dont_force_structured_output=True` + `add_schema_to_system_prompt=True` |
| 3 | 导航到畸形 URL（任务文本拼进 URL） | `directly_open_url` 朴素正则吞中文标点 | 用 `initial_actions` 显式导航，URL 不进 task |
| 4 | 无稳定版 Chrome | Windows 只有 Edge/Canary | `executable_path` 指向 Edge（Chromium 内核走 CDP） |
| 5 | 结构化字段不可枚举 | 采集目标动态变化 | pydantic `create_model` 动态构造 schema |
| 6 | 视觉模式 Qwen-VL 输出包 ``` 围栏 → 解析崩 | Qwen-VL 自由输出把 JSON 包进 markdown 围栏 | Qwen-VL 走 `response_format=json_schema` 强制干净 JSON |

> 版本说明：browser-use **0.13.x** 架构已重构——不再依赖 langchain/playwright，改为 **cdp-use**（Chrome DevTools Protocol）直连浏览器，LLM 用自带 `browser_use.ChatOpenAI`。网上大量教程仍停留在 0.7.x 旧 API，本项目已对新版适配。

---

## 评测

内置**企业级评测集**（`benchmark/web_tasks.json`）：**21 个任务、7 类企业场景**（学术 / 社区 / 电商 / 招聘 / 房产 / 本地生活 / 舆情），每个任务带**数据质量校验规则（validator）**——非空 / 正则 / 数值范围 / 枚举 / 包含关键词。

评测指标：成功率、字段完整率、**数据质量（validator 通过率）**、步数 / 耗时（含 P95）/ token 成本，并按分类汇总。

```bash
python -m app.eval                        # 跑全部 21 条
python -m app.eval --category 学术          # 只跑某分类（低反爬可实测）
python -m app.eval --id arxiv_cs_ai       # 只跑某任务
python -m app.eval --report eval_report.json   # 输出 JSON 报告
```

> 学术（arXiv）/ 社区（HN、维基百科）类为低反爬站点，可直接实测；电商（亚马逊/京东/淘宝）/ 招聘（BOSS/拉勾）/ 房产（链家/贝壳）/ 本地生活（大众点评）/ 舆情（微博/知乎）类为业务模板——反爬较强，需接入企业数据源（或平台数据适配层 MediaCrawler）后运行，validator 规则即企业数据质量标准。

**金标准（ground truth）评测**（`benchmark/golden_tasks.json`）：基于「冻结 HTML 快照 + 人工标注真值」的离线评测，比对提取值与期望值，算**字段准确率 / 条目召回率 / 精确率 / F1**（`app/golden.py` 模糊匹配引擎）。可离线、可重复、可 CI 回归。

```bash
python -m app.eval --benchmark benchmark/golden_tasks.json   # 金标准评测（本地 fixture，不依赖线上站点）
```

实测（DeepSeek deepseek-chat，DOM 文本模式，2026-09）：

**学术类 arXiv（6 任务，真实站点）：**

| 指标 | 数值 |
|------|------|
| 成功率 | 6/6 = **100%** |
| 平均步数 | 2.8 |
| 平均耗时 | 16.6s（P95 19.4s） |
| 平均 token | ~46k / 任务（每任务抽满 50 篇论文） |

**金标准（本地 fixture，2 任务）：**

| 指标 | 数值 |
|------|------|
| 通过率 | 2/2 = **100%** |
| 字段准确率 | **100%** |
| 召回率 / 精确率 / F1 | 1.0 / 1.0 / 1.0 |

---

## 目录结构

```
browser_use/
├── app/
│   ├── config.py            # LLM（DeepSeek 文本 / Qwen-VL 视觉）+ 浏览器 + 落库配置
│   ├── extractor.py         # browser-use 核心：动态 schema / 双模式 / 并发
│   ├── proxy.py             # 反爬：IP 代理池（轮换）
│   ├── robots.py            # 反爬：robots.txt 合规检查
│   ├── humanize.py          # 反爬：行为拟人化 + 域名限流
│   ├── sources/             # 数据源抽象层（双引擎）
│   │   ├── base.py          #   DataSource / CollectedItem / CollectionRequest
│   │   ├── browser_use.py   #   通用引擎
│   │   ├── mediacrawler.py  #   平台数据适配器
│   │   └── router.py        #   双引擎路由
│   ├── store.py             # SQLite 落库（去重 / 查询 / 成本对账）
│   ├── batch.py             # 批量编排（manifest → 并发 → 落库）
│   ├── collect.py           # 批量 CLI（run / query / stats）
│   ├── cli.py               # 单条 CLI
│   ├── server.py            # FastAPI
│   ├── ui.py                # Streamlit
│   ├── mcp_server.py        # MCP server
│   ├── golden.py            # 金标准评测（准确率/召回/F1 模糊匹配）
│   └── eval.py              # 评测
├── examples/
│   ├── manifest.example.json          # 批量任务清单示例
│   └── mediacrawler_xhs_sample.json   # 平台数据样例（适配器自测用）
├── benchmark/web_tasks.json    # 企业级评测集（21 任务 + validator）
├── benchmark/golden_tasks.json # 金标准评测集（ground truth）
├── benchmark/fixtures/         # 本地 HTML 快照（金标准 fixture）
├── .env.example / requirements.txt / Dockerfile
└── README.md
```

---

## Roadmap

- [ ] IP 代理池 + 行为拟人化
- [ ] 定时调度（竞品/价格监控的持续性采集）
- [ ] 更多平台的归一化映射（抖音/微博/知乎）
- [ ] OpenTelemetry trace 替代内置日志
- [ ] 多 Browser 实例池 + 任务队列

---

## License

MIT
