# backend/agents/review/state.py
# 评价分析 Agent 状态（M4a：由 Resume 六维评分平移）
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class DimensionResult(BaseModel):
    """单维度评分结果（结构化输出用）"""
    score: int = Field(..., ge=0, le=100, description="0-100 分")
    issues: list[str] = Field(default_factory=list, description="该维度发现的问题，最多3条")
    suggestions: list[str] = Field(default_factory=list, description="改进建议，最多3条")


class ProsCons(BaseModel):
    """优缺点挖掘结果"""
    pros: list[str] = Field(..., description="优点清单，2~4条，每条15~40字")
    cons: list[str] = Field(..., description="缺点清单，2~4条，每条15~40字")


class ReviewSummary(BaseModel):
    """报告总结"""
    summary: str = Field(..., description="120~200字的中文总结，客观中立")


class ReviewState(TypedDict):
    """评价分析 Agent 状态（一次性线性图，无 checkpointer）"""
    messages: Annotated[list[BaseMessage], add_messages]
    tenant_id: str
    product_id: str
    report_id: str
    triggered_by: Optional[str]
    product_title: str                 # 商品名（提示词上下文）
    product_category: Optional[str]
    reviews: list[dict]                # [{author, rating, content}] 最多30条
    dimension_scores: list[dict]       # [{key,name,score,weight,issues,suggestions}]
    weighted_score: float
    pros: list[str]
    cons: list[str]
    summary: Optional[str]
    fallback_used: bool
