"""金标准（ground truth）评测：比对提取结果与人工标注真值，算准确率/召回率。

与 validator（格式校验）不同，golden 评测比对的是「字段值是否正确」：
- 条目召回率 recall：golden 里有多少条被采到（按主字段模糊匹配）
- 条目准确率 precision：采到的条目里有多少对得上 golden
- 字段准确率 field_accuracy：匹配上的条目里，字段值一致的比例
- F1：recall 与 precision 的调和平均

匹配用模糊比较（归一化 + 子串 + 序列相似度 + 数值容差），容忍大小写/空格/标点差异。
金标准数据来自「冻结的 HTML 快照 + 人工标注」，可离线、可重复、可 CI 回归。
"""
from __future__ import annotations

import difflib
import re
from typing import Any


def normalize(s: Any) -> str:
    """归一化：小写、去空白、去标点/符号，保留字母数字与中文。"""
    s = str(s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w一-鿿]+", "", s)
    return s


def _to_num(s: str) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", s.replace(",", ""))
    return float(m.group()) if m else None


def similarity(a: Any, b: Any) -> float:
    """两值相似度 0-1。数值按相对误差，字符串按 归一化 + 子串 + 序列相似度。"""
    a, b = str(a or "").strip(), str(b or "").strip()
    if a == b:
        return 1.0
    # 数值比较：容忍格式差异（199.99 vs $199.99 vs 199,99）
    na, nb = _to_num(a), _to_num(b)
    if na is not None and nb is not None:
        if nb == 0:
            return 1.0 if na == 0 else 0.0
        rel = abs(na - nb) / abs(nb)
        return 1.0 if rel < 0.01 else max(0.0, 1.0 - rel)
    na_, nb_ = normalize(a), normalize(b)
    if not na_ or not nb_:
        return 0.0
    if na_ == nb_:
        return 1.0
    if na_ in nb_ or nb_ in na_:
        return 0.9
    return difflib.SequenceMatcher(None, na_, nb_).ratio()


def fuzzy_equal(a: Any, b: Any, threshold: float = 0.8) -> bool:
    return similarity(a, b) >= threshold


def match_items(golden: list[dict], extracted: list[dict], match_field: str,
                threshold: float = 0.6) -> list[tuple[dict, dict]]:
    """贪心匹配：每个 golden 条目匹配最相似且超阈值的 extracted 条目，返回配对列表。"""
    pool = [e for e in extracted if isinstance(e, dict)]
    pairs: list[tuple[dict, dict]] = []
    for g in golden:
        best, best_score = None, 0.0
        for e in pool:
            s = similarity(g.get(match_field), e.get(match_field))
            if s > best_score:
                best, best_score = e, s
        if best is not None and best_score >= threshold:
            pairs.append((g, best))
            pool.remove(best)
    return pairs


def evaluate_golden(golden: dict, extracted_items: list[dict]) -> dict | None:
    """对提取结果做金标准评测；golden 无 items 配置时返回 None。"""
    expected = golden.get("items") or golden.get("expected_items")
    if not isinstance(expected, list) or not expected:
        return None
    fields = golden.get("fields") or [k for k in expected[0].keys()]
    match_field = golden.get("match_field") or (fields[0] if fields else "")
    threshold = float(golden.get("threshold", 0.6))
    field_threshold = float(golden.get("field_threshold", 0.8))

    pairs = match_items(expected, extracted_items, match_field, threshold)
    n_golden = len(expected)
    n_extracted = len([e for e in extracted_items if isinstance(e, dict)])

    recall = len(pairs) / n_golden if n_golden else 1.0
    precision = len(pairs) / n_extracted if n_extracted else 0.0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) else 0.0

    total_fields = 0
    matched_fields = 0
    for g, e in pairs:
        for f in fields:
            if f not in g:
                continue
            total_fields += 1
            if fuzzy_equal(g.get(f), e.get(f), field_threshold):
                matched_fields += 1
    field_accuracy = matched_fields / total_fields if total_fields else 1.0

    return {
        "golden_items": n_golden,
        "matched_items": len(pairs),
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "f1": round(f1, 3),
        "field_accuracy": round(field_accuracy, 3),
    }
