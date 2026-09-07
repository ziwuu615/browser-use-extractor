"""配置加载：LLM 后端 + 浏览器可执行文件，供 extractor / cli / server 共用。"""
import os

from dotenv import load_dotenv

from browser_use import ChatOpenAI

load_dotenv()

# 本机浏览器候选。Windows 上 Edge 是 Win11 必装、稳定，优先用它走 CDP；Docker/Linux 用 chromium。
_BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome SxS\Application\chrome.exe"),
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]


def build_llm(use_vision: bool = False) -> ChatOpenAI:
    """按 .env 返回 OpenAI 兼容的模型后端。

    use_vision=True  → 多模态 VLM（Qwen-VL / GLM-4V），看页面截图；
    use_vision=False → 文本模型，优先 DeepSeek（DOM 文本模式，便宜），备选 Qwen。
    """
    if use_vision:
        return _build_vision_llm()
    if os.getenv("DEEPSEEK_API_KEY"):
        return ChatOpenAI(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            temperature=0.0,
            # DeepSeek/Qwen 不支持 response_format=json_schema（只支持 json_object），
            # 因此把 schema 写进 system prompt，而不强制 response_format。
            dont_force_structured_output=True,
            add_schema_to_system_prompt=True,
        )
    if os.getenv("QWEN_API_KEY"):
        return ChatOpenAI(
            model=os.getenv("QWEN_MODEL", "qwen-plus"),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=os.getenv("QWEN_API_KEY"),
            temperature=0.0,
            dont_force_structured_output=True,
            add_schema_to_system_prompt=True,
        )
    raise SystemExit(
        "未检测到 API Key：请复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY 后重试。"
    )


def _build_vision_llm() -> ChatOpenAI:
    """多模态 VLM：优先通义 Qwen-VL，备选智谱 GLM-4V（均国内直连、OpenAI 兼容）。

    关键：不设 dont_force_structured_output —— Qwen-VL 支持 response_format=json_schema，
    用 browser-use 默认的强制结构化输出即可得到干净 JSON；反之（自由输出）Qwen-VL 会把
    JSON 包进 ``` 围栏，browser-use 按纯 JSON 解析直接崩（DeepSeek 没这毛病，所以它才需要 dont_force）。
    """
    if os.getenv("QWEN_API_KEY"):
        return ChatOpenAI(
            model=os.getenv("QWEN_VL_MODEL", "qwen-vl-plus"),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=os.getenv("QWEN_API_KEY"),
            temperature=0.0,
        )
    if os.getenv("GLM_API_KEY"):
        # GLM 的 json_schema 支持未验证，保守起见沿用 DeepSeek 的 dont_force 策略。
        return ChatOpenAI(
            model=os.getenv("GLM_MODEL", "glm-4v-flash"),
            base_url=os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
            api_key=os.getenv("GLM_API_KEY"),
            temperature=0.0,
            dont_force_structured_output=True,
            add_schema_to_system_prompt=True,
        )
    raise SystemExit(
        "视觉模式需要多模态模型 Key：请在 .env 配置 QWEN_API_KEY（通义 Qwen-VL）"
        "或 GLM_API_KEY（智谱 GLM-4V）。纯文本模式（不加 --vision）用 DeepSeek 即可。"
    )


def browser_executable() -> str | None:
    """返回第一个存在的浏览器可执行文件路径；都不存在返回 None（browser-use 会自行探测）。

    也支持 CHROME_PATH / BROWSER_PATH 环境变量显式指定（Docker 里常用）。
    """
    for env_name in ("CHROME_PATH", "BROWSER_PATH"):
        env = os.getenv(env_name)
        if env and os.path.isfile(env):
            return env
    for p in _BROWSER_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def headless() -> bool:
    return os.getenv("HEADLESS", "true").strip().lower() in ("1", "true", "yes", "on")


def use_vision() -> bool:
    """是否把截图喂给模型。仅多模态模型时打开，DeepSeek 文本模式必须为 False。"""
    return os.getenv("BROWSER_USE_SCREENSHOT", "false").strip().lower() in ("1", "true", "yes", "on")


def max_concurrency() -> int:
    """并发上限：同时最多开多少个浏览器实例（信号量控制，防资源耗尽）。"""
    try:
        return max(1, int(os.getenv("MAX_CONCURRENCY", "3")))
    except ValueError:
        return 3
