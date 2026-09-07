"""评测：量化网页结构化采集 Agent 的效果。

指标（每任务 + 汇总）：
- 成功率：agent 报告成功 且 结构校验通过（条目数 >= min_items、每条字段完整非空）
- 平均步数 / 平均耗时
- token 成本（prompt/completion/total，取自 browser-use 的 history.usage）

用法：
    python -m app.eval                 # 跑全部
    python -m app.eval --limit 2       # 只跑前 2 条（快速验证）
    python -m app.eval --headless 0    # 有头模式观察

标注格式（benchmark/web_tasks.json）：
    [{"id": "...", "name": "...", "url": "...", "fields": ["title","authors"], "min_items": 10}]
"""
import argparse
import json
import sys
from pathlib import Path

from .extractor import extract_sync


def _force_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_benchmark(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"未找到评测集 {p}。请先在 benchmark/web_tasks.json 里添加任务。")
    return json.loads(p.read_text(encoding="utf-8"))


def _check(task: dict, result) -> tuple[bool, str]:
    """结构校验：成功 + 条目数达标 + 每条所有字段非空。"""
    if not result.success:
        return False, "agent 报告失败"
    data = result.data
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return False, "未抽取到 items 列表"
    min_items = int(task.get("min_items", 1))
    if len(items) < min_items:
        return False, f"条目数 {len(items)} < 要求 {min_items}"
    for it in items:
        if not isinstance(it, dict):
            return False, "存在非对象条目"
        for f in task.get("fields", []):
            v = it.get(f)
            if not v or not str(v).strip():
                return False, f"字段「{f}」为空"
    return True, ""


def _tokens(usage: dict | None) -> int:
    return int((usage or {}).get("total_tokens", 0))


def run_eval(bench: list[dict], headless: bool | None, max_steps: int) -> None:
    rows: list[tuple] = []
    for i, task in enumerate(bench, 1):
        print(f"[{i}/{len(bench)}] {task['name']} ...", flush=True)
        try:
            result = extract_sync(
                url=task["url"],
                fields=task.get("fields"),
                max_steps=max_steps,
                headless=headless,
            )
        except Exception as e:  # 单条异常不中断整个评测
            rows.append((task["id"], False, f"异常: {e}", 0, 0.0, None))
            print(f"     ❌ 异常：{e}", flush=True)
            continue
        passed, reason = _check(task, result)
        rows.append((task["id"], passed, reason, result.steps, result.duration_s, result.usage))
        mark = "✅" if passed else f"❌ {reason}"
        print(f"     {mark}  steps={result.steps}  {result.duration_s:.1f}s  tokens={_tokens(result.usage)}", flush=True)

    n = len(bench)
    ok = sum(1 for r in rows if r[1])
    total_tokens = sum(_tokens(r[5]) for r in rows)
    avg_steps = sum(r[3] for r in rows) / n
    avg_dur = sum(r[4] for r in rows) / n

    print("\n" + "=" * 62)
    print("评测汇总")
    print("=" * 62)
    print(f"成功率   : {ok}/{n} = {ok / n:.1%}")
    print(f"平均步数 : {avg_steps:.1f}")
    print(f"平均耗时 : {avg_dur:.1f}s")
    print(f"总 token : {total_tokens}（平均 {total_tokens / n:.0f}/任务）")
    print("\n" + "-" * 62)
    print(f"{'任务':<16}{'结果':<6}{'步数':>5}{'耗时':>8}{'token':>8}")
    for task_id, passed, reason, steps, dur, usage in rows:
        mark = "✅" if passed else "❌"
        print(f"{task_id:<16}{mark:<6}{steps:>5}{dur:>7.1f}s{_tokens(usage):>8}")


def main() -> None:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="网页结构化采集 Agent 评测")
    ap.add_argument("--benchmark", default="benchmark/web_tasks.json", help="评测集文件")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    ap.add_argument("--headless", type=int, choices=[0, 1], default=None, help="1 无头 / 0 有头")
    ap.add_argument("--max-steps", type=int, default=20)
    args = ap.parse_args()

    bench = load_benchmark(args.benchmark)
    if args.limit:
        bench = bench[: args.limit]
    print(f"评测样本数：{len(bench)}")
    run_eval(bench, headless=None if args.headless is None else bool(args.headless), max_steps=args.max_steps)


if __name__ == "__main__":
    main()
