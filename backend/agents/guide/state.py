# backend/agents/guide/state.py
# 多轮导购 Agent 状态（M5a：由 Interview 五阶段状态机平移）
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class GuideStage:
    NEEDS_DISCOVERY = "needs_discovery"
    BUDGET_CONFIRM  = "budget_confirm"
    MATCHING        = "matching"
    COMPARE_QA      = "compare_qa"
    RECOMMEND_CLOSE = "recommend_close"
    FINISHED        = "finished"


class NeedsInfo(BaseModel):
    """需求抽取（结构化输出）"""
    needs: str = Field(..., description="用户需求一句话概括，中文")
    budget: Optional[float] = Field(None, description="预算上限（元），未提及为 null")
    preferences: list[str] = Field(default_factory=list, description="偏好标签，如 送礼/便携/低糖")


class Recommendation(BaseModel):
    product_id: str = Field(..., description="推荐商品的 UUID")
    reason: str = Field(..., description="推荐理由，20~50字，结合用户需求")


class GuideReport(BaseModel):
    """结束时的推荐报告"""
    summary: str = Field(..., description="整体推荐总结，80~150字")
    recommendations: list[Recommendation] = Field(..., description="1~5 条推荐，按优先级")


class GuideState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    tenant_id: str
    session_id: str
    initial_message: str                # 首轮用户输入（可为空字符串）
    current_stage: str
    stage_turn_count: int
    total_turn_count: int
    max_turns: int
    needs: str
    budget: Optional[float]
    preferences: list[str]
    candidates: list[dict]              # [{product_id,title,price,category,rating}]
    existing_summary: Optional[str]
    report: Optional[dict]              # {summary, recommendations}
    fallback_used: bool
    structured_output: Optional[dict]
