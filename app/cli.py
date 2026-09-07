"""命令行入口。

示例：
    python -m app.cli "https://arxiv.org/list/cs.AI/recent" "提取论文标题和作者"
    python -m app.cli "https://arxiv.org/list/cs.AI/recent" --fields title,authors,date
"""
import argparse
import sys

from .export import to_csv, to_json
from .extractor import extract_sync


def _force_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，遇到重音/emoji 会崩；强制 UTF-8 输出。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _parse_fields(s: str | None) -> list[str] | None:
    if not s:
        return None
    return [f.strip() for f in s.split(",") if f.strip()]


def main() -> None:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="网页结构化数据采集 Agent（browser-use + DeepSeek）")
    ap.add_argument("url", help="目标网页 URL")
    ap.add_argument("goal", nargs="?", default="", help="采集目标（自然语言），与 --fields 二选一")
    ap.add_argument("-f", "--fields", help="逗号分隔的字段，如 title,authors,date（走结构化 schema 模式）")
    ap.add_argument("--max-steps", type=int, default=25, help="Agent 最大步数")
    ap.add_argument("--headless", type=int, choices=[0, 1], default=None,
                    help="1 无头 / 0 有头（默认读 .env 的 HEADLESS）")
    ap.add_argument("--vision", action="store_true", help="视觉模式（需配 QWEN_API_KEY/GLM_API_KEY 的 VLM）")
    ap.add_argument("--json", action="store_true", help="以纯 JSON 输出（默认即 JSON，保留此参数便于管道）")
    ap.add_argument("-o", "--output", help="把结果写入文件（.csv 后缀自动导出 CSV，否则 JSON）")
    ap.add_argument("--format", choices=["json", "csv"], default=None,
                    help="输出格式（默认 JSON；--output 时按后缀推断）")
    args = ap.parse_args()

    fields = _parse_fields(args.fields)
    if not args.goal and not fields:
        ap.error("需要提供采集目标 goal，或用 -f/--fields 指定字段")

    result = extract_sync(
        url=args.url,
        goal=args.goal,
        fields=fields,
        max_steps=args.max_steps,
        headless=None if args.headless is None else bool(args.headless),
        use_vision=True if args.vision else None,
    )
    result_dict = result.to_dict()
    fmt = args.format or ("csv" if args.output and args.output.endswith(".csv") else "json")

    if args.output:
        text = to_csv(result_dict, args.output) if fmt == "csv" else to_json(result_dict, args.output)
        print(f"已写入 {args.output}")
    else:
        text = to_csv(result_dict) if fmt == "csv" else to_json(result_dict)
        print(text)


if __name__ == "__main__":
    main()
