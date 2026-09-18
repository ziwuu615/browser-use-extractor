"""评测：量化网页结构化采集 Agent 的效果（企业级数据质量 + 成本 + 时延）。

指标（每任务 + 分类汇总 + 全局）：
- 成功率：agent 成功 且 条目数 >= min_items
- 字段完整率：必填字段非空的占比
- 数据质量：validator 校验通过率（非空/正则/数值范围/枚举/包含关键词）
- 成本与时延：token、平均耗时、P95 耗时

validator 类型：
    non_empty   非空
    regex       正则匹配（re.search，默认忽略大小写）
    range       数值落在 [min, max]（自动抽取字符串里的首个数字）
    one_of      值在枚举内（忽略大小写）
    contains    值包含任一关键词

用法：
    python -m app.eval                      # 跑全部
    python -m app.eval --category 学术       # 只跑某分类（低反爬可实测）
    python -m app.eval --id arxiv_cs_ai     # 只跑某任务
    python -m app.eval --report eval_report.json   # 输出 JSON 报告
    python -m app.eval --headless 0         # 有头模式观察
"""
import argparse
import json
import re
import sys
from pathlib import Path

from .extractor import extract_sync


def _force_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 数据质量校验
# ---------------------------------------------------------------------------
def validate_value(value, rule: dict) -> tuple[bool, str]:
    """检查单个字段值是否满足规则，返回 (是否通过, 失败原因)。"""
    rtype = rule.get("type", "non_empty")
    s = str(value) if value is not None else ""

    if rtype == "non_empty":
        return bool(s.strip()), "为空"

    if rtype == "regex":
        pattern = rule.get("pattern", "")
        if not pattern:
            return True, ""
        flags = re.IGNORECASE if rule.get("ignore_case", True) else 0
        return bool(re.search(pattern, s, flags)), f"不匹配 /{pattern}/"

    if rtype == "range":
        m = re.search(r"-?\d+(\.\d+)?", s.replace(",", "").replace("，", ""))
        if not m:
            return False, f"无数字 {s!r}"
        v = float(m.group())
        lo = float(rule.get("min", float("-inf")))
        hi = float(rule.get("max", float("inf")))
        return lo <= v <= hi, f"数值 {v} 超出 [{lo}, {hi}]"

    if rtype == "one_of":
        allowed = {str(x).lower() for x in rule.get("values", [])}
        return s.lower() in allowed, "不在枚举内"

    if rtype == "contains":
        subs = rule.get("values", [])
        sv = s.lower()
        return any(str(x).lower() in sv for x in subs), "不含关键词"

    return True, ""


def evaluate_task(task: dict, result) -> dict:
    """对一次采集结果做完整评估（纯逻辑，不触发 agent），返回评估报告。"""
    data = result.data
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        items = []

    fields = task.get("fields", [])
    validators = task.get("validators", {})
    min_items = int(task.get("min_items", 1))

    n_items = len(items)
    n_cells = n_items * len(fields)
    empty_cells = 0
    total_checks = 0
    passed_checks = 0
    failed_samples: list[str] = []

    for it in items:
        if not isinstance(it, dict):
            continue
        for f in fields:
            v = it.get(f)
            if v is None or not str(v).strip():
                empty_cells += 1
            if f in validators:
                total_checks += 1
                ok, reason = validate_value(v, validators[f])
                if ok:
                    passed_checks += 1
                elif len(failed_samples) < 5:
                    failed_samples.append(f"{f}={v!r} {reason}")

    field_completeness = (n_cells - empty_cells) / n_cells if n_cells else 1.0
    data_quality = passed_checks / total_checks if total_checks else 1.0
    success = bool(result.success) and n_items >= min_items
    # 通过 = 成功 + 字段完整 100% + 数据质量 >= 0.8
    passed = success and field_completeness >= 0.99 and data_quality >= 0.8

    return {
        "id": task.get("id", task.get("name", "")),
        "name": task.get("name", ""),
        "category": task.get("category", "未分类"),
        "passed": passed,
        "success": success,
        "n_items": n_items,
        "min_items": min_items,
        "field_completeness": round(field_completeness, 3),
        "data_quality": round(data_quality, 3),
        "steps": result.steps,
        "duration_s": round(result.duration_s, 1),
        "tokens": int((result.usage or {}).get("total_tokens", 0)),
        "errors": list(result.errors),
        "failed_samples": failed_samples,
    }


def aggregate(reports: list[dict]) -> dict:
    """汇总多任务评估结果：全局指标 + 分类指标。"""
    n = len(reports)
    if n == 0:
        return {"total": 0, "success_rate": 0.0, "categories": []}

    durations = [r["duration_s"] for r in reports]
    tokens = [r["tokens"] for r in reports]
    p95 = sorted(durations)[max(0, int((n - 1) * 0.95))]

    cats: dict[str, list[dict]] = {}
    for r in reports:
        cats.setdefault(r["category"], []).append(r)

    return {
        "total": n,
        "passed": sum(1 for r in reports if r["passed"]),
        "success_rate": round(sum(1 for r in reports if r["passed"]) / n, 3),
        "avg_steps": round(sum(r["steps"] for r in reports) / n, 1),
        "avg_duration_s": round(sum(durations) / n, 1),
        "p95_duration_s": round(p95, 1),
        "avg_tokens": int(sum(tokens) / n),
        "total_tokens": sum(tokens),
        "categories": [
            {
                "category": c,
                "tasks": len(rs),
                "passed": sum(1 for r in rs if r["passed"]),
                "success_rate": round(sum(1 for r in rs if r["passed"]) / len(rs), 3),
                "avg_data_quality": round(sum(r["data_quality"] for r in rs) / len(rs), 3),
            }
            for c, rs in sorted(cats.items())
        ],
    }


# ---------------------------------------------------------------------------
# 评测主流程
# ---------------------------------------------------------------------------
def load_benchmark(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"未找到评测集 {p}。请先在 benchmark/web_tasks.json 里添加任务。")
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        return data["tasks"]
    if isinstance(data, list):
        return data
    raise SystemExit("评测集需为 list 或 {\"tasks\": [...]}")


def run_eval(tasks: list[dict], headless: bool | None, max_steps: int) -> list[dict]:
    reports = []
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task['name']} ...", flush=True)
        try:
            result = extract_sync(
                url=task["url"],
                fields=task.get("fields"),
                max_steps=max_steps,
                headless=headless,
            )
        except Exception as e:  # 单条异常不中断整个评测
            reports.append({
                "id": task.get("id"), "name": task.get("name"),
                "category": task.get("category", "未分类"),
                "passed": False, "success": False, "n_items": 0,
                "min_items": task.get("min_items", 1),
                "field_completeness": 0.0, "data_quality": 0.0,
                "steps": 0, "duration_s": 0.0, "tokens": 0,
                "errors": [f"异常: {e}"], "failed_samples": [],
            })
            print(f"     ❌ 异常：{e}", flush=True)
            continue
        report = evaluate_task(task, result)
        reports.append(report)
        mark = "✅" if report["passed"] else f"❌ 条数{report['n_items']}/{report['min_items']} 完整率{report['field_completeness']} 质量{report['data_quality']}"
        print(f"     {mark}  steps={report['steps']}  {report['duration_s']}s  tokens={report['tokens']}", flush=True)
        for s in report["failed_samples"]:
            print(f"        - {s}", flush=True)
    return reports


def _print_report(reports: list[dict], summary: dict) -> None:
    print("\n" + "=" * 72)
    print("企业级采集评测汇总")
    print("=" * 72)
    print(f"通过率   : {summary['passed']}/{summary['total']} = {summary['success_rate']:.1%}")
    print(f"平均步数 : {summary['avg_steps']}")
    print(f"平均耗时 : {summary['avg_duration_s']}s   P95: {summary['p95_duration_s']}s")
    print(f"平均 token: {summary['avg_tokens']}   总 token: {summary['total_tokens']}")

    print("\n" + "-" * 72)
    print(f"{'分类':<10}{'任务数':>6}{'通过':>6}{'通过率':>9}{'平均质量':>10}")
    for c in summary["categories"]:
        print(f"{c['category']:<10}{c['tasks']:>6}{c['passed']:>6}{c['success_rate']:>8.1%}{c['avg_data_quality']:>10.3f}")

    print("\n" + "-" * 72)
    print(f"{'任务':<22}{'结果':<6}{'条数':>5}{'完整率':>8}{'质量':>7}{'步数':>5}{'耗时':>7}{'token':>8}")
    for r in reports:
        mark = "✅" if r["passed"] else "❌"
        print(f"{r['name'][:22]:<22}{mark:<6}{r['n_items']:>5}{r['field_completeness']:>8.2f}{r['data_quality']:>7.2f}{r['steps']:>5}{r['duration_s']:>6.0f}s{r['tokens']:>8}")


def main() -> None:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="企业级网页结构化采集 Agent 评测")
    ap.add_argument("--benchmark", default="benchmark/web_tasks.json", help="评测集文件")
    ap.add_argument("--category", default=None, help="只跑某分类（如 学术/电商/招聘/房产/舆情/社区/本地生活）")
    ap.add_argument("--id", default=None, help="只跑某任务 id")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    ap.add_argument("--headless", type=int, choices=[0, 1], default=None, help="1 无头 / 0 有头")
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--report", default=None, help="输出 JSON 报告文件路径")
    args = ap.parse_args()

    tasks = load_benchmark(args.benchmark)
    if args.category:
        tasks = [t for t in tasks if t.get("category") == args.category]
    if args.id:
        tasks = [t for t in tasks if t.get("id") == args.id]
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        raise SystemExit("没有匹配的任务")

    print(f"评测样本数：{len(tasks)}")
    reports = run_eval(tasks, headless=None if args.headless is None else bool(args.headless),
                       max_steps=args.max_steps)
    summary = aggregate(reports)
    _print_report(reports, summary)

    if args.report:
        payload = {"summary": summary, "tasks": reports}
        Path(args.report).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已输出 JSON 报告 → {args.report}")


if __name__ == "__main__":
    main()
