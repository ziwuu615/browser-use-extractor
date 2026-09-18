"""洞察层：把采集到的竞品/口碑数据转成业务结论。

采集层回答「数据准不准」，洞察层回答「老板真正关心的问题」：
- 竞品威胁评估：对比价格/评分，找出能威胁我方的竞品（规则化，确定可测）
- 市场反馈摘要：聚合口碑文本，用 LLM 提取高频正负面话题与建议

产物：结构化 JSON + markdown 报告，供运营/选品直接读。

用法：
    python -m app.insight --products examples/insight_products.json \
                          --comments examples/feedback_comments.json \
                          --my-price 249 --my-rating 4.8
    python -m app.insight --store data/store.sqlite   # 从落库数据生成报告
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# 数值解析
# ---------------------------------------------------------------------------
def parse_price(v: Any) -> float | None:
    """从 "$249.00" / "249" / "¥199" / "199元" 提取数字价格。"""
    m = re.search(r"-?\d+(\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group()) if m else None


def parse_rating(v: Any) -> float | None:
    m = re.search(r"-?\d+(\.\d+)?", str(v or ""))
    return float(m.group()) if m else None


# ---------------------------------------------------------------------------
# 竞品威胁评估（规则化，确定性、可测）
# ---------------------------------------------------------------------------
def _threat(price_pct: float, rating_diff: float) -> tuple[str, str]:
    """由相对价格差与评分差给出威胁等级与理由（价格优先，评分作修正）。"""
    if price_pct <= -0.10:
        if rating_diff >= -0.20:
            return "高", f"价格低 {abs(price_pct):.0%} 且评分相近/更高"
        return "中", f"价格低 {abs(price_pct):.0%} 但评分明显偏低"
    if price_pct <= -0.05:
        return "中", f"价格低 {abs(price_pct):.0%}"
    if rating_diff >= 0.20 and price_pct <= 0.05:
        return "中", "价格相当但评分更高"
    return "低", "价格更高或评分不占优"


def analyze_competitors(products: list[dict], my_price: float | None = None,
                        my_rating: float | None = None) -> dict:
    """对竞品列表做威胁评估，返回结构化结论。"""
    rows: list[dict] = []
    ref_price = my_price
    if ref_price is None:  # 未指定我方价格时，以最低价为参照
        prices = [parse_price(p.get("price")) for p in products]
        prices = [x for x in prices if x is not None]
        ref_price = min(prices) if prices else None
    ref_rating = my_rating

    for p in products:
        price = parse_price(p.get("price"))
        rating = parse_rating(p.get("rating"))
        if price is None and rating is None:
            continue
        price_pct = ((price - ref_price) / ref_price) if (price is not None and ref_price) else 0.0
        rating_diff = (rating - ref_rating) if (rating is not None and ref_rating is not None) else 0.0
        level, reason = _threat(price_pct, rating_diff)
        rows.append({
            "title": p.get("title", ""),
            "price": price,
            "rating": rating,
            "price_diff_pct": round(price_pct, 3),
            "threat": level,
            "reason": reason,
        })

    high = [r for r in rows if r["threat"] == "高"]
    conclusion = (
        f"存在 {len(high)} 个高威胁竞品：{'、'.join(r['title'] for r in high)}，建议立即跟进价格或卖点。"
        if high
        else "当前暂无高威胁竞品，需持续监控价格与评分变化。"
    )
    return {"products": rows, "conclusion": conclusion}


# ---------------------------------------------------------------------------
# 市场反馈摘要（LLM 分析）
# ---------------------------------------------------------------------------
def _llm_chat(messages: list[dict]) -> str:
    from openai import OpenAI

    if os.getenv("DEEPSEEK_API_KEY"):
        client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"),
                        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    elif os.getenv("QWEN_API_KEY"):
        client = OpenAI(api_key=os.getenv("QWEN_API_KEY"),
                        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
        model = os.getenv("QWEN_MODEL", "qwen-plus")
    else:
        raise SystemExit("未检测到 API Key：请配置 DEEPSEEK_API_KEY 或 QWEN_API_KEY。")

    resp = client.chat.completions.create(model=model, messages=messages, temperature=0.0)
    return resp.choices[0].message.content or ""


def _try_parse_json(text: str) -> Any:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if starts:
        start = min(starts)
        closer = "]" if text[start] == "[" else "}"
        end = text.rfind(closer)
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


def analyze_feedback(comments: list[dict], top_n: int = 30) -> dict:
    """聚合口碑文本，用 LLM 提取高频正负面话题与建议。"""
    texts = [str(c.get("content", "")).strip() for c in comments if c.get("content")]
    if not texts:
        return {"positive": [], "negative": [], "suggestion": "", "error": "无口碑数据"}
    sample = texts[:top_n]
    prompt = (
        "你是电商选品分析师。下面是关于一款产品的用户评论，请提炼：\n"
        "1) 正面高频话题（最多 5 条，每条 2-6 字）；\n"
        "2) 负面高频话题（最多 5 条）；\n"
        "3) 一句话建议。\n"
        '只输出 JSON：{"positive": ["..."], "negative": ["..."], "suggestion": "..."}\n\n'
        "评论：\n" + "\n".join(f"- {t}" for t in sample)
    )
    raw = _llm_chat([{"role": "user", "content": prompt}])
    parsed = _try_parse_json(raw)
    if isinstance(parsed, dict):
        return {
            "positive": parsed.get("positive", []),
            "negative": parsed.get("negative", []),
            "suggestion": parsed.get("suggestion", ""),
        }
    return {"positive": [], "negative": [], "suggestion": raw}


# ---------------------------------------------------------------------------
# 报告汇总
# ---------------------------------------------------------------------------
def generate_report(products: list[dict], comments: list[dict],
                    my_price: float | None = None, my_rating: float | None = None,
                    with_feedback: bool = True) -> dict:
    report = {
        "competitors": analyze_competitors(products, my_price, my_rating),
        "feedback": analyze_feedback(comments) if with_feedback else None,
    }
    return report


def to_markdown(report: dict) -> str:
    lines = ["# 竞品与市场洞察报告\n"]
    comp = report.get("competitors") or {}
    lines.append("## 竞品威胁评估\n")
    lines.append("| 竞品 | 价格 | 评分 | 价格差 | 威胁 | 理由 |")
    lines.append("|------|------|------|--------|------|------|")
    for r in comp.get("products", []):
        price = f"{r['price']:.2f}" if r["price"] is not None else "-"
        rating = f"{r['rating']}" if r["rating"] is not None else "-"
        lines.append(f"| {r['title']} | {price} | {rating} | {r['price_diff_pct']:+.0%} | {r['threat']} | {r['reason']} |")
    lines.append(f"\n**结论**：{comp.get('conclusion', '')}\n")

    fb = report.get("feedback")
    if fb:
        lines.append("## 市场反馈摘要\n")
        lines.append(f"- 正面高频：{'、'.join(fb.get('positive', [])) or '（无）'}")
        lines.append(f"- 负面高频：{'、'.join(fb.get('negative', [])) or '（无）'}")
        lines.append(f"- 建议：{fb.get('suggestion') or '（无）'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _load_json(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"未找到文件 {path}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return data if isinstance(data, list) else [data]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="竞品与市场洞察报告")
    ap.add_argument("--products", help="竞品数据 JSON 文件")
    ap.add_argument("--comments", help="口碑评论 JSON 文件")
    ap.add_argument("--store", help="从 SQLite 落库读数据（备选）")
    ap.add_argument("--my-price", type=float, default=None, help="我方价格（参照）")
    ap.add_argument("--my-rating", type=float, default=None, help="我方评分（参照）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认 markdown）")
    args = ap.parse_args()

    if args.store:
        from .store import Store
        store = Store(args.store)
        rows = store.query(limit=1000)
        products = [r["data"] for r in rows if "price" in r["data"] or "rating" in r["data"]]
        comments = [r["data"] for r in rows if "content" in r["data"]]
        store.close()
    else:
        products = _load_json(args.products) if args.products else []
        comments = _load_json(args.comments) if args.comments else []

    report = generate_report(products, comments, args.my_price, args.my_rating)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(report))


if __name__ == "__main__":
    main()
