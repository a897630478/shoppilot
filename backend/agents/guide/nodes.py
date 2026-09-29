# backend/agents/guide/nodes.py
# 多轮导购节点（M5a：平移自 Interview——状态机推进 + 阶段化生成 + 报告落库）
import asyncio
import json

from langchain_core.messages import HumanMessage, BaseMessage
from sqlalchemy import text

from backend.agents.guide.prompts import (
    SYSTEM_PROMPT,
    NEEDS_EXTRACT_PROMPT,
    OPENING_PROMPT,
    STAGE_PROMPTS,
    REPORT_PROMPT,
)
from backend.agents.guide.state import (
    GuideState,
    GuideStage,
    NeedsInfo,
    GuideReport,
)
from backend.core.llm_factory import get_llm, get_structured_llm
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

STAGE_ORDER = [
    GuideStage.NEEDS_DISCOVERY,
    GuideStage.BUDGET_CONFIRM,
    GuideStage.MATCHING,
    GuideStage.COMPARE_QA,
    GuideStage.RECOMMEND_CLOSE,
]
STAGE_MIN_TURNS = {
    GuideStage.NEEDS_DISCOVERY: 1,
    GuideStage.BUDGET_CONFIRM: 1,
    GuideStage.MATCHING: 2,
    GuideStage.COMPARE_QA: 0,
    GuideStage.RECOMMEND_CLOSE: 1,
}
STAGE_MAX_TURNS = {
    GuideStage.NEEDS_DISCOVERY: 4,
    GuideStage.BUDGET_CONFIRM: 3,
    GuideStage.MATCHING: 6,
    GuideStage.COMPARE_QA: 8,
    GuideStage.RECOMMEND_CLOSE: 2,
}

FORCE_END_KEYWORDS = ["直接推荐", "结束选购", "不用问了", "就这些", "结束吧"]


def _msg_text(msg: BaseMessage) -> str:
    c = msg.content
    if isinstance(c, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in c)
    return str(c)


def _latest_user_text(state: GuideState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            return _msg_text(msg)
    return state.get("initial_message") or ""


def _candidates_block(candidates: list[dict]) -> str:
    if not candidates:
        return "（暂无候选，先与顾客确认需求）"
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(f"{i}. {c['product_id']} | {c['title']} | ¥{c['price']} | {c.get('category') or ''}")
    return "\n".join(lines)


async def load_context_node(state: GuideState) -> dict:
    """只读加载历史摘要（会话行由 API 创建）。"""
    try:
        from backend.core.memory import build_thread_id
        thread_id = build_thread_id(state["user_id"], state["session_id"])
        async with AsyncSessionLocal() as db:
            row = (await db.execute(text(
                "SELECT summary FROM recommendation_sessions WHERE thread_id = :tid"
            ), {"tid": thread_id})).first()
        return {"existing_summary": row[0] if row else None}
    except Exception as e:
        logger.warning("guide.load_context_failed", error=str(e))
        return {"existing_summary": None}


def check_stage(state: GuideState) -> dict:
    """纯逻辑状态机：强制结束判定 + 阶段推进（平移自 Interview check_stage）。"""
    answer = _latest_user_text(state)
    total = state.get("total_turn_count", 0) + 1
    stage = state.get("current_stage") or GuideStage.NEEDS_DISCOVERY
    stage_turn = state.get("stage_turn_count", 0) + 1
    max_turns = state.get("max_turns", 16)

    # ── 强制结束：关键词 或 轮次接近上限（同轮跳 FINISHED 生成报告）──
    if any(kw in answer for kw in FORCE_END_KEYWORDS) or total >= max_turns - 2:
        if stage != GuideStage.FINISHED:
            logger.info("guide.force_end", total=total, stage=stage)
        return {"current_stage": GuideStage.FINISHED,
                "total_turn_count": total, "stage_turn_count": stage_turn}

    # ── 推荐收尾阶段：产出一轮最终推荐后，下一轮进入 FINISHED ──
    if stage == GuideStage.RECOMMEND_CLOSE and stage_turn >= 2:
        return {"current_stage": GuideStage.FINISHED,
                "total_turn_count": total, "stage_turn_count": stage_turn}

    # ── 阶段推进：max 驱动；预算明确可提前离开 budget 阶段 ──
    if stage in STAGE_ORDER:
        idx = STAGE_ORDER.index(stage)
        can_advance = stage_turn >= STAGE_MAX_TURNS[stage]
        if stage == GuideStage.BUDGET_CONFIRM and state.get("budget") is not None and stage_turn >= 1:
            can_advance = True
        if can_advance and idx < len(STAGE_ORDER) - 1:
            next_stage = STAGE_ORDER[idx + 1]
            logger.info("guide.stage_advance", frm=stage, to=next_stage)
            return {"current_stage": next_stage, "total_turn_count": total,
                    "stage_turn_count": 1}

    return {"current_stage": stage, "total_turn_count": total,
            "stage_turn_count": stage_turn}


async def _search_candidates(state: GuideState) -> list[dict]:
    """向量检索候选 → PG 补全/预算过滤 → 前 3；空则 ILIKE 兜底。"""
    from backend.core.reranker import retrieve

    query = state.get("needs") or _latest_user_text(state) or "商品"
    loop = asyncio.get_running_loop()
    docs, _ = await loop.run_in_executor(
        None, lambda: retrieve(query, tenant_id=state["tenant_id"], recall_top_k=8, rerank_top_k=8)
    )
    pids: list[str] = []
    for d in docs:
        pid = (getattr(d, "metadata", {}) or {}).get("product_id")
        if pid and pid not in pids:
            pids.append(pid)

    async with AsyncSessionLocal() as db:
        rows = []
        if pids:
            placeholders = ",".join(f":p{i}" for i in range(len(pids)))
            params = {f"p{i}": pid for i, pid in enumerate(pids)}
            sql = (f"SELECT id, title, price, category, rating FROM products "
                   f"WHERE is_active AND id IN ({placeholders})")
            if state.get("budget") is not None:
                sql += " AND price <= :budget"
                params["budget"] = state["budget"]
            rows = (await db.execute(text(sql), params)).fetchall()
        if not rows:  # ILIKE 兜底
            kw = (state.get("needs") or query)[:6]
            params = {"kw": f"%{kw}%"}
            sql = ("SELECT id, title, price, category, rating FROM products "
                   "WHERE is_active AND (title ILIKE :kw OR category ILIKE :kw)")
            if state.get("budget") is not None:
                sql += " AND price <= :budget"
                params["budget"] = state["budget"]
            sql += " ORDER BY rating DESC NULLS LAST LIMIT 3"
            rows = (await db.execute(text(sql), params)).fetchall()

    order = {pid: i for i, pid in enumerate(pids)}
    candidates = [
        {"product_id": str(r[0]), "title": r[1], "price": float(r[2]),
         "category": r[3], "rating": r[4]}
        for r in rows
    ]
    candidates.sort(key=lambda c: order.get(c["product_id"], 99))
    return candidates[:3]


async def generate_response_node(state: GuideState) -> dict:
    """按阶段生成导购回应（token 流由 API 层捕获本节点的 LLM stream）。"""
    stage = state.get("current_stage") or GuideStage.NEEDS_DISCOVERY
    answer = _latest_user_text(state)
    needs = state.get("needs") or "尚未明确"
    budget = state.get("budget")
    updates: dict = {"fallback_used": False}

    # ── 需求/预算类阶段：先结构化抽取，再生成回应 ──
    if stage in (GuideStage.NEEDS_DISCOVERY, GuideStage.BUDGET_CONFIRM):
        try:
            info = await get_structured_llm("guide", NeedsInfo).ainvoke([
                {"role": "user", "content": NEEDS_EXTRACT_PROMPT.format(
                    needs=needs, budget=budget, answer=answer)}])
            updates["needs"] = info.needs or needs
            if info.budget is not None:
                updates["budget"] = float(info.budget)
            if info.preferences:
                updates["preferences"] = list(dict.fromkeys(
                    (state.get("preferences") or []) + info.preferences))[:8]
        except Exception as e:
            logger.warning("guide.extract_failed", error=str(e))
            updates["fallback_used"] = True
        needs = updates.get("needs", needs)
        budget = updates.get("budget", budget)

    # ── 检索类阶段：填充候选 ──
    if stage in (GuideStage.MATCHING, GuideStage.COMPARE_QA, GuideStage.RECOMMEND_CLOSE):
        if not state.get("candidates"):
            updates["candidates"] = await _search_candidates(state)
    candidates = updates.get("candidates") or state.get("candidates") or []

    # ── 选提示词 ──
    if stage == GuideStage.NEEDS_DISCOVERY and state.get("total_turn_count", 0) <= 1 and not state.get("needs"):
        prompt = OPENING_PROMPT.format(answer=answer)
    else:
        template = STAGE_PROMPTS.get(stage, STAGE_PROMPTS[GuideStage.NEEDS_DISCOVERY])
        prompt = template.format(
            needs=needs, budget=budget, answer=answer,
            candidates_block=_candidates_block(candidates),
        )

    # ── 历史摘要注入 System ──
    system = SYSTEM_PROMPT
    if state.get("existing_summary"):
        system += f"\n\n【本会话历史摘要】\n{state['existing_summary']}"

    # 窗口历史（不含最新一条，最新作当前输入）
    history = state.get("messages", [])[:-1][-10:]
    lc_messages = [{"role": "system", "content": system}]
    for m in history:
        role = "assistant" if not isinstance(m, HumanMessage) else "user"
        lc_messages.append({"role": role, "content": _msg_text(m)})
    lc_messages.append({"role": "user", "content": prompt})

    from langchain_core.messages import AIMessage
    try:
        resp = await get_llm("guide", temperature=0.6, streaming=True).ainvoke(lc_messages)
        updates["messages"] = [AIMessage(content=_msg_text(resp))]
    except Exception as e:
        logger.warning("guide.generate_failed", stage=stage, error=str(e))
        updates["fallback_used"] = True
        updates["messages"] = [AIMessage(
            content="抱歉，我这边稍微走神了，能再说一下您的需求吗？")]
    return updates


async def generate_report_node(state: GuideState) -> dict:
    """结束：结构化推荐报告（兜底=全部候选）。"""
    candidates = state.get("candidates") or await _search_candidates(state)
    valid_ids = {c["product_id"] for c in candidates}
    block = _candidates_block(candidates)

    report: dict | None = None
    try:
        result = await get_structured_llm("guide", GuideReport).ainvoke([
            {"role": "user", "content": REPORT_PROMPT.format(
                needs=state.get("needs") or "未明确",
                budget=state.get("budget"),
                preferences="、".join(state.get("preferences") or []) or "无",
                candidates_block=block,
                history_summary=state.get("existing_summary") or "无",
            )}])
        recs = [r for r in result.recommendations if r.product_id in valid_ids][:5]
        if recs:
            report = {
                "summary": result.summary,
                "recommendations": [{"product_id": r.product_id, "reason": r.reason}
                                    for r in recs],
            }
    except Exception as e:
        logger.warning("guide.report_llm_failed", error=str(e))

    if report is None:  # 兜底
        report = {
            "summary": f"根据需求「{state.get('needs') or '未明确'}」，为您推荐以下商品。",
            "recommendations": [
                {"product_id": c["product_id"],
                 "reason": f"¥{c['price']}，{c['title']}，与您的需求较匹配"}
                for c in candidates[:3]
            ],
        }
    return {"report": report, "current_stage": GuideStage.FINISHED,
            "candidates": candidates}


async def save_report_node(state: GuideState) -> dict:
    """报告落库 + recommendation_results 重建（先删后插幂等）。"""
    from backend.core.memory import build_thread_id
    thread_id = build_thread_id(state["user_id"], state["session_id"])
    report = state.get("report") or {}
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT id FROM recommendation_sessions WHERE thread_id = :tid"
        ), {"tid": thread_id})).first()
        if row is None:
            raise ValueError("recommendation session not found")
        session_pk = row[0]
        await db.execute(text(
            "UPDATE recommendation_sessions SET result = :r, stage = 'finished', "
            "status = 'finished', summary = :s, finished_at = NOW(), updated_at = NOW() "
            "WHERE thread_id = :tid"
        ), {"r": json.dumps(report, ensure_ascii=False),
            "s": report.get("summary"), "tid": thread_id})
        await db.execute(text(
            "DELETE FROM recommendation_results WHERE session_id = :sid"
        ), {"sid": session_pk})
        for i, rec in enumerate(report.get("recommendations") or [], 1):
            await db.execute(text(
                "INSERT INTO recommendation_results (session_id, product_id, rank, reason) "
                "VALUES (:sid, :pid, :rank, :reason)"
            ), {"sid": session_pk, "pid": rec["product_id"],
                "rank": i, "reason": rec["reason"]})
        await db.commit()
    logger.info("guide.report_saved", thread_id=thread_id,
                n=len(report.get("recommendations") or []))
    return {}


async def save_memory_node(state: GuideState) -> dict:
    """对话摘要 UPSERT（每轮用最新对话让 LLM 压缩更新；失败保留旧摘要）。"""
    from backend.core.memory import build_thread_id

    try:
        llm = get_llm("qa", temperature=0)
        recent = []
        for m in state.get("messages", [])[-8:]:
            role = "顾客" if isinstance(m, HumanMessage) else "导购"
            recent.append(f"{role}: {_msg_text(m)[:120]}")
        if not recent:
            return {}
        resp = await llm.ainvoke(
            "把以下导购对话压缩为 3 句以内的摘要（保留需求/预算/已推荐商品），只输出摘要：\n"
            + "\n".join(recent)
        )
        summary = _msg_text(resp).strip()
        thread_id = build_thread_id(state["user_id"], state["session_id"])
        async with AsyncSessionLocal() as db:
            await db.execute(text(
                "UPDATE recommendation_sessions SET summary = :s, updated_at = NOW() "
                "WHERE thread_id = :tid"
            ), {"s": summary, "tid": thread_id})
            await db.commit()
        return {"existing_summary": summary}
    except Exception as e:
        logger.warning("guide.save_memory_failed", error=str(e))
        return {}
