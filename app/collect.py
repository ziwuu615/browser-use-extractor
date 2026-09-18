"""CLI 入口：批量采集 / 查询 / 统计。

用法：
    python -m app.collect run -m examples/manifest.example.json
    python -m app.collect query --platform xhs --limit 20
    python -m app.collect stats
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import config
from .batch import load_manifest, run_batch
from .store import Store


def _force_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _run_batch_sync(tasks: list[dict], concurrency: int | None) -> dict:
    return asyncio.run(run_batch(tasks, concurrency=concurrency))


def cmd_run(args: argparse.Namespace) -> None:
    tasks = load_manifest(args.manifest)
    print(f"任务数：{len(tasks)}，落库：{config.store_path()}", flush=True)
    summary = _run_batch_sync(tasks, concurrency=args.concurrency)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_query(args: argparse.Namespace) -> None:
    store = Store(config.store_path())
    rows = store.query(source=args.source, platform=args.platform, limit=args.limit)
    store.close()
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_stats(args: argparse.Namespace) -> None:
    store = Store(config.store_path())
    print(json.dumps(store.counts(), ensure_ascii=False, indent=2))
    store.close()


def main() -> None:
    _force_utf8()
    ap = argparse.ArgumentParser(description="批量采集 + 数据落库")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="跑一批采集任务")
    p_run.add_argument("-m", "--manifest", required=True, help="任务清单 JSON 文件")
    p_run.add_argument("--concurrency", type=int, default=None,
                       help="并发数（默认读 MAX_CONCURRENCY）")
    p_run.set_defaults(func=cmd_run)

    p_q = sub.add_parser("query", help="查询已落库数据")
    p_q.add_argument("--source", default=None)
    p_q.add_argument("--platform", default=None)
    p_q.add_argument("--limit", type=int, default=20)
    p_q.set_defaults(func=cmd_query)

    p_s = sub.add_parser("stats", help="库统计")
    p_s.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
