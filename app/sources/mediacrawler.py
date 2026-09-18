"""平台数据适配器：把 MediaCrawler 等平台工具导出的数据文件归一化进统一 Schema。

设计选择——「读导出文件」而非「运行时调用」：
- MediaCrawler 是独立运行的工具（扫码登录 / 平台风控 / IP 代理池），本项目不 vendor 其代码；
- 它能把数据导出成 CSV / JSON / JSONL / SQLite，本适配器读入这些文件、按列映射归一化，
  与 browser-use 引擎的产出汇入同一数据资产。

合规边界：MediaCrawler 采用 NON-COMMERCIAL LEARNING LICENSE（仅学习/研究用途）。
本项目只把它当作「数据文件的其中一种来源」接入；商业化数据源应改用合规 API 或自有数据。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import CollectionRequest, CollectionResult, CollectedItem, DataSource, content_id


def _to_int(v: Any) -> int:
    """计数类字段统一转 int（MediaCrawler 里 liked_count 等是字符串）。"""
    if v is None or v == "":
        return 0
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _to_iso(ts: Any) -> str:
    """时间戳转 ISO 字符串（兼容秒/毫秒）。"""
    if not ts:
        return ""
    try:
        t = int(ts)
        if t > 10_000_000_000:  # 毫秒
            t //= 1000
        return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return str(ts)


def _author(user: Any) -> tuple[str, str]:
    if isinstance(user, dict):
        return str(user.get("nickname", "")), str(user.get("user_id", ""))
    return "", ""


# 字段名取自 MediaCrawler media_platform/xhs/field.py 的 Note NamedTuple。
def _normalize_xhs_note(rec: dict) -> dict:
    nickname, user_id = _author(rec.get("user"))
    return {
        "title": rec.get("title", ""),
        "content": rec.get("desc", ""),
        "author": nickname,
        "author_id": user_id,
        "like_count": _to_int(rec.get("liked_count")),
        "comment_count": _to_int(rec.get("comment_count")),
        "share_count": _to_int(rec.get("share_count")),
        "collect_count": _to_int(rec.get("collected_count")),
        "publish_time": _to_iso(rec.get("time")),
        "type": rec.get("type", ""),
        "tags": rec.get("tag_list", []),
        "image_urls": rec.get("img_urls", []),
    }


# 小红书评论（MediaCrawler 导出常见列；缺省列取空不影响）。
def _normalize_xhs_comment(rec: dict) -> dict:
    nickname, user_id = _author(rec.get("user"))
    return {
        "content": rec.get("content", ""),
        "author": nickname,
        "author_id": user_id,
        "like_count": _to_int(rec.get("like_count")),
        "publish_time": _to_iso(rec.get("create_time") or rec.get("time")),
    }


def _normalize_generic(rec: dict) -> dict:
    """通用兜底：透传字段，常见计数字段统一转 int。"""
    out = {k: v for k, v in rec.items()}
    for k in ("liked_count", "like_count", "comment_count", "share_count", "collected_count"):
        if k in out:
            out[k] = _to_int(out[k])
    return out


_NORMALIZERS = {
    ("xhs", "note"): _normalize_xhs_note,
    ("xhs", "comment"): _normalize_xhs_comment,
}


def _native_id(rec: dict, platform: str, data: dict) -> str:
    """优先用平台原始 ID 做去重键，否则退回内容哈希。"""
    for cid in ("note_id", "comment_id", "id", "aweme_id", "bvid", "mblog_id"):
        if rec.get(cid):
            return str(rec[cid])
    return content_id(data)


def _load_records(file: str) -> list[dict]:
    """读 MediaCrawler 导出文件（.json / .jsonl / .csv），返回记录列表。"""
    p = Path(file)
    if not p.exists():
        raise FileNotFoundError(f"未找到数据文件 {file}")
    suffix = p.suffix.lower()
    if suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "data", "notes", "comments", "contents"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
    if suffix == ".jsonl":
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out
    if suffix == ".csv":
        with p.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    raise ValueError(f"不支持的导出格式：{suffix}（支持 .json/.jsonl/.csv）")


class MediaCrawlerSource(DataSource):
    """平台数据适配器：读 MediaCrawler 导出文件并归一化。

    request.extra 约定：
        file      导出文件路径
        item_type 记录类型（note / comment），缺省按平台推断
    """
    name = "mediacrawler"

    async def collect(self, request: CollectionRequest) -> CollectionResult:
        file = request.extra.get("file") or request.target
        item_type = request.extra.get("item_type") or "note"
        platform = request.platform or "xhs"
        records = _load_records(file)

        items: list[CollectedItem] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            fn = _NORMALIZERS.get((platform, item_type))
            data = fn(rec) if fn else _normalize_generic(rec)
            items.append(CollectedItem(
                source=self.name,
                platform=platform,
                data=data,
                native_id=_native_id(rec, platform, data),
                url=str(rec.get("url", rec.get("note_url", ""))),
            ))

        return CollectionResult(
            source=self.name,
            platform=platform,
            success=len(items) > 0,
            items=items,
            raw={"file": str(file), "records": len(records)},
            errors=[] if records else [f"未从 {file} 读到任何记录"],
        )
