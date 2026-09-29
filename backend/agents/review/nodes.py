# backend/agents/review/nodes.py
# 评价分析 Agent 五节点（线性一次性图）——骨架平移自 Resume 六维并行评分
import asyncio
import json

from langchain_core.messages import HumanMessage
from sqlalchemy import text

from backend.agents.review.prompts import (
    SYSTEM_PROMPT,
    DIMENSION_REVIEW_PROMPTS,
    MINE_PROS_CONS_PROMPT,
    GENERATE_SUMMARY_PROMPT,
)
from backend.agents.review.state import (
    ReviewState,
    DimensionResult,
    ProsCons,
    ReviewSummary,
)
from backend.core.llm_factory import get_structured_llm
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

# 六维定义（key 与 prompts.DIMENSION_REVIEW_PROMPTS 对齐；权重和 = 1.0）
SIX_DIMENSIONS = [
    {"key": "quality",    "name": "商品质量", "weight": 0.30},
    {"key": "logistics",  "name": "物流配送", "weight": 0.10},
    {"key": "service",    "name": "商家服务", "weight": 0.15},
    {"key": "value",      "name": "性价比",   "weight": 0.20},
    {"key": "fit",        "name": "符合预期", "weight": 0.10},
    {"key": "repurchase", "name": "复购意愿", "weight": 0.15},
]

MAX_REVIEWS = 30
_REVIEW_CHARS = 60          # 单条评价进提示词的截断长度


def _reviews_block(reviews: list[dict]) -> str:
    lines = []
    for i, r in enumerate(reviews[:MAX_REVIEWS], 1):
        stars = r.get("rating") or "?"
        content = (r.get("content") or "")[:_REVIEW_CHARS]
        lines.append(f"{i}. [{stars}星] {content}")
    return "\n".join(lines)


async def load_reviews_node(state: ReviewState) -> dict:
    """按 product_id 拉取商品信息与评价（只取 active 商品）。"""
    async with AsyncSessionLocal() as db:
        prod = (await db.execute(text(
            "SELECT title, category FROM products WHERE id = :pid AND is_active"
        ), {"pid": state["product_id"]})).first()
        if prod is None:
            raise ValueError(f"product not found or inactive: {state['product_id']}")
        rows = (await db.execute(text(
            "SELECT author, rating, content FROM product_reviews "
            "WHERE product_id = :pid ORDER BY created_at DESC LIMIT 30"
        ), {"pid": state["product_id"]})).fetchall()
    reviews = [{"author": r[0], "rating": r[1], "content": r[2]} for r in rows]
    if not reviews:
        raise ValueError("no reviews for product")
    logger.info("review.load_done", product=prod[0], n=len(reviews))
    return {"product_title": prod[0], "product_category": prod[1], "reviews": reviews}


async def run_dimensions_node(state: ReviewState) -> dict:
    """六维并行评分（asyncio.gather，平移自 Resume 六维骨架）。"""
    block = _reviews_block(state["reviews"])

    async def review_one(dim: dict) -> dict:
        prompt = DIMENSION_REVIEW_PROMPTS[dim["key"]].format(
            product_title=state["product_title"], reviews_text=block,
        )
        for attempt in range(3):
            try:
                result = await get_structured_llm("review", DimensionResult).ainvoke(
                    [HumanMessage(content=SYSTEM_PROMPT + "\n\n" + prompt)]
                )
                return {**dim, "score": result.score,
                        "issues": result.issues, "suggestions": result.suggestions}
            except Exception as e:
                if attempt == 2:
                    logger.warning("review.dimension_failed", dim=dim["key"], error=str(e))
                    return {**dim, "score": 60, "issues": [], "suggestions": []}  # 降级中性分
                await asyncio.sleep(1)

    results = await asyncio.gather(*[review_one(d) for d in SIX_DIMENSIONS])
    weighted = round(sum(r["score"] * r["weight"] for r in results), 1)
    return {"dimension_scores": list(results), "weighted_score": weighted}


async def mine_pros_cons_node(state: ReviewState) -> dict:
    """优缺点挖掘。"""
    prompt = MINE_PROS_CONS_PROMPT.format(
        product_title=state["product_title"], reviews_text=_reviews_block(state["reviews"]),
    )
    try:
        result = await get_structured_llm("review", ProsCons).ainvoke(
            [HumanMessage(content=SYSTEM_PROMPT + "\n\n" + prompt)]
        )
        return {"pros": result.pros, "cons": result.cons, "fallback_used": False}
    except Exception as e:
        logger.warning("review.mine_failed", error=str(e))
        return {"pros": [], "cons": [], "fallback_used": True}


async def generate_summary_node(state: ReviewState) -> dict:
    """报告总结。"""
    scores_summary = "、".join(
        f"{d['name']} {d['score']}" for d in state["dimension_scores"]
    )
    prompt = GENERATE_SUMMARY_PROMPT.format(
        product_title=state["product_title"],
        product_category=state.get("product_category") or "未分类",
        weighted_score=state["weighted_score"],
        scores_summary=scores_summary,
        pros="；".join(state.get("pros") or []) or "无",
        cons="；".join(state.get("cons") or []) or "无",
    )
    try:
        result = await get_structured_llm("review", ReviewSummary).ainvoke(
            [HumanMessage(content=prompt)]
        )
        return {"summary": result.summary}
    except Exception as e:
        logger.warning("review.summary_failed", error=str(e))
        return {"summary": f"加权总分 {state['weighted_score']} 分，详见各维度得分。"}


async def save_results_node(state: ReviewState) -> dict:
    """报告持久化到 review_reports（status=done；失败由 API 层回调标 failed）。"""
    scores = {
        "weighted_score": state["weighted_score"],
        "dimensions": state["dimension_scores"],
    }
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE review_reports SET scores = :scores, pros = :pros, cons = :cons, "
            "summary = :summary, status = 'done', updated_at = NOW() WHERE id = :rid"
        ), {
            "scores": json.dumps(scores, ensure_ascii=False),
            "pros": json.dumps(state.get("pros") or [], ensure_ascii=False),
            "cons": json.dumps(state.get("cons") or [], ensure_ascii=False),
            "summary": state.get("summary"),
            "rid": state["report_id"],
        })
        await db.commit()
    logger.info("review.saved", report_id=state["report_id"], score=state["weighted_score"])
    return {}
