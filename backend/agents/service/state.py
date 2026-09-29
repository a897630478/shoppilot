# backend/agents/service/state.py
# 售后客服 Agent 状态（M4b：由 Exam 三轨批改平移；一次性图 + 条件分流，无 checkpointer）
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class TicketReply(BaseModel):
    """工单回复（结构化输出）"""
    reply: str = Field(..., description="给客户的中文回复，60~120字，礼貌清晰")
    suggestion: str = Field(..., description="给审批人的处理建议（如需人工），30~60字；自动处理时可为空串")
    confidence: float = Field(..., ge=0, le=1, description="处理方案置信度")


class ServiceState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    tenant_id: str
    user_id: str
    ticket_id: str
    order_id: str
    ticket_type: str                   # logistics | refund | exchange
    reason: str                        # 用户填写的诉求
    # load_order 产出
    order_status: str
    total_amount: float
    product_title: str
    quantity: int
    # 分轨产出
    reply: str
    suggestion: str
    confidence: float
    needs_review: bool
    final_status: str                  # resolved | pending
    fallback_used: bool
