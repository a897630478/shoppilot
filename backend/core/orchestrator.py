# backend/core/orchestrator.py
# Orchestrator：Agent 编排服务
# 职责：接收 API 层请求 → 单 Agent 直达（多 Agent Pipeline 已随教育模块移除）

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

from backend.core.logger import get_logger
from backend.core.retry import with_retry          # 重试降级装饰器（三层兜底）
from backend.core.exceptions import (               # 统一异常体系
    AgentExecutionError,
    IntentRouteError,
)

logger = get_logger(__name__)


class ExecutionMode(str, Enum):
    """执行模式：决定一个请求怎么跑。"""
    SINGLE   = "single"     # 单 Agent 直达（最常见）
    CLARIFY  = "clarify"    # 澄清对话（意图不明，需追问）


class AgentType(str, Enum):
    """Agent 类型标识（QA 为在用能力；其余成员保留仅为路由事件载荷兼容）。"""
    QA        = "qa"         # 商品导购问答
    EXAM      = "exam"       # 已移除（售后客服占位载荷）
    RESUME    = "resume"     # 已移除（评价分析占位载荷）
    INTERVIEW = "interview"  # 已移除（智能导购占位载荷）

class AgentRequest(BaseModel):
    """所有 Agent 请求的统一入参 Schema"""
    student_id:    str = Field(..., description="发起请求的用户 ID")
    tenant_id:     str = Field(default="tenant_default", description="租户 ID")
    session_id:    str = Field(..., description="会话 ID，用于 thread_id 拼接")
    agent_type:    AgentType = Field(..., description="目标 Agent 类型")
    user_message:  str = Field(..., description="用户输入的原始文本")
    context:       dict[str, Any] = Field(default_factory=dict, description="附加上下文（文件路径/历史数据等）")

    @property
    def thread_id(self) -> str:
        """LangGraph Checkpointer 使用的线程 ID（与各 Agent 的 build_thread_id 格式一致）"""
        return f"student_{self.student_id}_session_{self.session_id}"


class AgentResponse(BaseModel):
    """所有 Agent 响应的统一出参 Schema"""
    success:       bool = Field(..., description="执行是否成功")
    agent_type:    AgentType = Field(..., description="实际执行的 Agent 类型")
    content:       str = Field(default="", description="主要文本响应内容")
    structured:    Optional[dict[str, Any]] = Field(default=None, description="结构化数据（评分/报告等）")
    fallback_used: bool = Field(default=False, description="是否触发了降级处理")
    error_msg:     Optional[str] = Field(default=None, description="失败时的错误信息")
    metadata:      dict[str, Any] = Field(default_factory=dict, description="附加元数据")

class Orchestrator:
    """
    Agent 编排服务。

    职责：
        - 单 Agent 模式：直接调用对应 Agent 的 LangGraph 图
        - 串联 Pipeline 模式：按顺序调用多个 Agent，前序输出注入后序输入
        - 澄清对话模式：返回结构化追问，等待用户补充信息后重新路由

    所有 Agent 图在首次使用时懒加载，避免启动时全量加载占用资源。
    """

    def __init__(self):
        # Agent 图注册表（懒加载，key=AgentType，value=编译后的 LangGraph）
        self._agent_graphs: dict[AgentType, Any] = {}

        logger.info("orchestrator.initialized")

    def _get_agent_graph(self, agent_type: AgentType) -> Any:
        """
        懒加载 Agent 的 LangGraph 编译图。

        读取/写入：self._agent_graphs（图缓存字典）
        首次访问某 Agent 时才 import 并 build 它的图，之后复用缓存。
        各 Agent 图在对应章节（第 4-7 章）已实现，此处只负责按需取用。
        """
        if agent_type not in self._agent_graphs:        # 缓存里没有 → 首次加载
            if agent_type == AgentType.QA:
                from backend.agents.qa.graph import build_qa_graph          # 第 5 章
                self._agent_graphs[agent_type] = build_qa_graph()

            elif agent_type == AgentType.EXAM:
                raise RuntimeError(
                    "教育考试 Agent 已在 M5b 移除，请使用售后客服（/service）")

            elif agent_type == AgentType.RESUME:
                raise RuntimeError(
                    "教育简历 Agent 已在 M5b 移除，请使用评价分析（/reviews）")

            elif agent_type == AgentType.INTERVIEW:
                raise RuntimeError(
                    "教育面试 Agent 已在 M5b 移除，请使用智能导购（/guide）")

            else:
                raise ValueError(f"未知 AgentType: {agent_type}")

            logger.info(
                "orchestrator.agent_graph_loaded",
                agent_type=agent_type.value,
            )

        return self._agent_graphs[agent_type]           # 返回（缓存的）编译图

    async def handle(self, request: AgentRequest) -> AgentResponse:
        """
        统一请求处理入口（单 Agent 直达；多 Agent Pipeline 已移除）。

        返回：AgentResponse（统一响应格式，无论成功失败都返回它，不向上抛异常）
        """
        logger.info(
            "orchestrator.handle_start",
            agent_type=request.agent_type.value,
            student_id=request.student_id,
        )

        try:
            return await self._run_single_agent(request)

        except Exception as e:                           # 兜底：任何异常都转成失败响应，不抛给上层
            logger.error(
                "orchestrator.handle_failed",
                agent_type=request.agent_type.value,
                error=str(e),
                exc_info=True,
            )
            return AgentResponse(
                success=False,
                agent_type=request.agent_type,
                content="系统处理请求时遇到问题，请稍后再试。",  # 给用户的友好兜底文案
                error_msg=str(e),
            )

    async def _run_single_agent(self, request: AgentRequest) -> AgentResponse:
        """
        单 Agent 直达模式：直接调用目标 Agent 的 LangGraph 图。

        读取 request：agent_type / user_message / student_id / tenant_id / session_id / context
        返回：AgentResponse（从 Agent 图最终 State 提取 content + structured + fallback_used）
        使用 with_retry 包装，自动处理重试和降级（来自 3.5）。
        """
        graph = self._get_agent_graph(request.agent_type)    # 懒加载取出目标 Agent 图

        # 构建 LangGraph 输入 State（统一三件套 + context 展开）
        initial_state = {
            "messages": [HumanMessage(content=request.user_message)],  # 用户消息
            "student_id": request.student_id,
            "tenant_id": request.tenant_id,
            "session_id": request.session_id,
            **request.context,                           # 附加上下文（如文件路径、简历结果）平铺进 State
        }

        config = {                                       # LangGraph 运行配置
            "configurable": {
                "thread_id": request.thread_id,          # 用 thread_id 命中 MemorySaver 检查点
            }
        }

        @with_retry(agent_type=request.agent_type.value)  # 给本次调用套上三层兜底（重试→降级→系统兜底）
        async def _invoke():
            return await graph.ainvoke(initial_state, config=config)  # 真正跑 Agent 图

        result_state = await _invoke()                   # 执行（失败时 with_retry 自动处理）
        # print(f'result_state66666 = {result_state}')
        # 从最终 State 提取响应内容：取最后一条消息的文本
        last_message = result_state["messages"][-1]
        content = last_message.text if hasattr(last_message, "text") else str(last_message.content)

        return AgentResponse(
            success=True,
            agent_type=request.agent_type,
            content=content,                             # 主文本响应
            structured=result_state.get("structured_output"),   # 结构化数据（报告/评分，若有）
            fallback_used=result_state.get("fallback_used", False),  # 是否走了降级
        )
# 模块级单例（应用生命周期内复用）
# ──────────────────────────────────────────────────────────────
_orchestrator_instance: Optional[Orchestrator] = None    # 全局唯一实例（初始为空）


def get_orchestrator() -> Orchestrator:
    """获取 Orchestrator 单例（FastAPI 依赖注入使用）"""
    global _orchestrator_instance
    if _orchestrator_instance is None:                   # 第一次调用才创建
        _orchestrator_instance = Orchestrator()
    return _orchestrator_instance                        # 之后都返回同一个实例


