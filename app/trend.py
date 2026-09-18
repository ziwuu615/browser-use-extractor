"""记忆管理：趋势记忆 + 变化检测。

竞品监控的灵魂是「盯变化」——记住历史采集，对比新采集，标出价格/评分变化、新竞品、下架竞品。
历史记忆复用 store 落库（items 含 collected_at）；变化检测按稳定身份键（默认 title）跨采集匹配，
对比数值字段（price / rating）。阈值可配：价格变化 >= 5%、评分变化 >= 0.2 才告警。

用法：
    python -m app.trend --products examples/insight_products.json --store data/store.sqlite --id-field title
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _num(v: Any) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group()) if m else None


def _latest_by_key(history: list[dict], id_field: str) -> dict[str, dict]:
    """按 id_field 分组取每组最新一条（query 按 id DESC 返回，首个即最新）。"""
    latest: dict[str, dict] = {}
    for r in history:
        data = r.get("data") or {}
        key = str(data.get(id_field, "")).strip()
        if key and key not in latest:
            latest[key] = data
    return latest


def detect_changes(history: list[dict], new_items: list[dict], id_field: str = "title",
                   price_threshold: float = 0.05, rating_threshold: float = 0.2) -> dict:
    """对比历史与新采集，返回变化清单（纯逻辑，可离线测）。"""
    latest = _latest_by_key(history, id_field)
    removed = set(latest.keys())
    price_changes: list[dict] = []
    rating_changes: list[dict] = []
    new_keys: list[str] = []

    for item in new_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get(id_field, "")).strip()
        if not key:
            continue
        if key in latest:
            removed.discard(key)
            old = latest[key]
            po, pn = _num(old.get("price")), _num(item.get("price"))
            if po is not None and pn is not None and po > 0 and abs(pn - po) / po >= price_threshold:
                price_changes.append({
                    "title": key, "old_price": po, "new_price": pn,
                    "change_pct": round((pn - po) / po, 4),
                })
            ro, rn = _num(old.get("rating")), _num(item.get("rating"))
            if ro is not None and rn is not None and abs(rn - ro) >= rating_threshold:
                rating_changes.append({"title": key, "old_rating": ro, "new_rating": rn})
        else:
            new_keys.append(key)

    return {
        "price_changes": price_changes,
        "rating_changes": rating_changes,
        "new_items": new_keys,
        "removed": sorted(removed),
    }


def summarize(changes: dict) -> str:
    """把变化清单转成可读的告警文本。"""
    lines: list[str] = []
    for c in changes.get("price_changes", []):
        arrow = "↓" if c["change_pct"] < 0 else "↑"
        lines.append(f"[价格] {c['title']}：{c['old_price']:.2f} → {c['new_price']:.2f}（{c['change_pct']:+.0%} {arrow}）")
    for c in changes.get("rating_changes", []):
        arrow = "↓" if c["new_rating"] < c["old_rating"] else "↑"
        lines.append(f"[评分] {c['title']}：{c['old_rating']} → {c['new_rating']} {arrow}")
    for n in changes.get("new_items", []):
        lines.append(f"[新竞品] {n}")
    for r in changes.get("removed", []):
        lines.append(f"[下架] {r}")
    return "\n".join(lines) if lines else "无变化"


def changes_from_store(store, new_items: list[dict], id_field: str = "title",
                       source: str | None = None, platform: str | None = None) -> dict:
    """从落库读历史，对比新采集，返回变化清单。"""
    history = store.query(source=source, platform=platform, limit=100000)
    return detect_changes(history, new_items, id_field)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="记忆管理：变化检测")
    ap.add_argument("--products", help="本次采集的商品数据 JSON 文件")
    ap.add_argument("--store", default="data/store.sqlite", help="历史落库路径")
    ap.add_argument("--id-field", default="title", help="稳定身份键（跨采集匹配用）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    from .store import Store
    store = Store(args.store)
    new_items: list[dict] = []
    if args.products:
        data = json.loads(Path(args.products).read_text(encoding="utf-8"))
        new_items = data.get("items") if isinstance(data, dict) else data
    changes = changes_from_store(store, new_items, args.id_field)
    store.close()

    if args.json:
        print(json.dumps(changes, ensure_ascii=False, indent=2))
    else:
        print(summarize(changes))


if __name__ == "__main__":
    main()
