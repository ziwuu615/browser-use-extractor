"""结果导出：JSON / CSV。供 CLI（--output / --format）复用。"""
import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any


def flatten_items(data: Any) -> list[dict]:
    """把抽取结果里的 items（list[dict]）拍平成表格行；没有则返回空列表。"""
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]


def _collect_fieldnames(rows: list[dict]) -> list[str]:
    names: list[str] = []
    for r in rows:
        for k in r:
            if k not in names:
                names.append(k)
    return names


def to_json(result: dict, path: str | None = None, indent: int = 2) -> str:
    """序列化成 JSON；path 非空则写文件。返回字符串。"""
    s = json.dumps(result, ensure_ascii=False, indent=indent)
    if path:
        Path(path).write_text(s, encoding="utf-8")
    return s


def to_csv(result: dict, path: str | None = None) -> str:
    """把 items 拍平成 CSV；path 非空则写文件。返回字符串（无 items 时为空串）。"""
    rows = flatten_items(result.get("data"))
    if not rows:
        return ""
    fieldnames = _collect_fieldnames(rows)
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    s = buf.getvalue()
    if path:
        Path(path).write_text(s, encoding="utf-8", newline="")
    return s
