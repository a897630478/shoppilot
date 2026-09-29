# backend/api/v1/unified_chat.py
# 统一 AI 助手入口：意图识别 → 路由决策可视化 → Agent 执行
#
# SSE 事件类型：
#   routing_decision  路由决策结果（agent_type / confidence / reason / execution_mode）
#   progress          QA 流水线进度提示（检索知识库...等）
#   token             QA Agent 流式 token
#   guidance          非 QA 意图的引导消息（含跳转链接）
#   meta              QA 回答完毕后的元数据（answer_mode / sources 等）
#   done              流结束信号
#   error             异常

import json
import re
from dataclasses import dataclass
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage

from backend.core.orchestrator import AgentType, ExecutionMode   # 8.2 定义的枚举
from backend.core.memory import build_thread_id                  # 5.10 的 thread_id 工具
from backend.core.llm_factory import get_llm                     # 3.4 的 LLM 工厂
from backend.dependencies import get_current_user                # 3.6 的认证依赖
from backend.core.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


# ── label 中文名映射（路由卡片展示用；service/review/guide 为 M4/M5 预告）──
_LABEL_DISPLAY = {
    "qa":          "商品导购问答",
    "service":     "售后服务中心",
    "review":      "商品评价分析",
    "guide":       "智能选购推荐",
    "clarify":     "智能助手",
}

# ── 未上线能力的引导卡（M4/M5 交付前指向现有页面）─────────────────
_GUIDANCE_BY_LABEL = {
    "service": {
        "message": "售后服务已上线：请到「我的订单」找到对应订单，点击「申请售后」发起物流/退款/换货工单，AI 将自动处理或转人工审批。",
        "action_label": "查看我的订单",
        "action_url": "/orders",
    },
    "review": {
        "message": "商品口碑报告已上线：请打开具体商品详情页，点击「AI 口碑分析」即可生成六维口碑报告。",
        "action_label": "去商品列表",
        "action_url": "/products",
    },
    "guide": {
        "message": "智能选购推荐已上线：点击下方按钮开始多轮导购，我会了解您的需求并给出商品推荐。",
        "action_label": "开始智能导购",
        "action_url": "/guide",
    },
}

# ── QA Agent 节点进度提示（与 qa.py 保持一致，8.5 用到）────────
_PROGRESS_LABELS = {
    "classify_query":        "理解问题中...",
    "load_memory_and_embed": "检索知识库...",
    "retrieve":              "召回相关文档...",
    "rerank":                "精排中...",
    "hyde_generate":         "理解问题中...",
    "multi_query_rewrite":   "改写查询中...",
    "generate_general":      "思考中...",
}
_GENERATE_NODES = {"generate_rag", "generate_direct", "generate_general"}  # QA 的三个生成节点
# ── 去除末尾标点空白，用于关键词精确比对 ──────────────────────────
_STRIP_TAIL_RE = re.compile(r"[\s!！?？。~～,.，。]+$")

# ── 类别一：问候（你好 / 在吗）────────────────────────────────────
_HELLO_KEYWORDS = frozenset([
    "你好", "您好", "hi", "hello", "hey", "哈喽", "嗨",
    "在吗", "在不在", "在线吗", "有人吗",
])

# ── 类别二：感谢（谢谢 / 辛苦了 / 太棒了）────────────────────────
_THANKS_KEYWORDS = frozenset([
    "谢谢", "感谢", "多谢", "谢了", "非常感谢", "万分感谢",
    "辛苦了", "辛苦", "麻烦了", "不好意思",
    "太棒了", "太好了", "厉害", "厉害了", "牛", "牛啊", "牛逼",
    "好的好的", "明白了", "懂了", "知道了", "收到",
])

# ── 类别三：道别（再见 / bye）──────────────────────────────────────
_BYE_KEYWORDS = frozenset([
    "再见", "拜拜", "拜", "88", "886", "bye", "goodbye", "byebye",
    "下次见", "下次再聊", "先走了", "先撤了", "溜了", "闪了",
])

# ── 类别四：身份询问（你是谁 / 介绍你自己）── 正则匹配 ──────────────
_IDENTITY_RE = re.compile(
    r"(你|您)(是谁|叫什么|的名字|是什么|是.*AI|是.*机器人|是.*助手)"
    r"|介绍.{0,4}(你自己|自己|一下)"
    r"|你是谁"
    r"|你叫(啥|什么名)",
    re.IGNORECASE,
)

# ── 类别五：功能询问（你能做什么 / 怎么用）── 正则匹配 ──────────────
_CAPABILITY_RE = re.compile(
    r"(你|您)(能|可以|会).{0,6}(做|帮|干)"
    r"|(你|您).{0,4}(功能|用途|能力|特点)"
    r"|怎么(用|使用)(你|您|这个)?"
    r"|(使用说明|帮助菜单|help|usage)"
    r"|你能帮(我|忙)吗",
    re.IGNORECASE,
)


# ── 多 Agent 能力说明（HELLO / IDENTITY / CAPABILITY 共享结尾）────
_MULTI_AGENT_TIP = (
    "- **购物全链路**：从商品咨询到下单售后，我都会尽力协助\n"
)

# ── 五类回复模板（节选问候，其余结构相同）──────────────────────────
_REPLY_HELLO = (
    "您好！我是 ShopPilot 智能导购助手。\n\n"
    "我可以帮您：\n"
    "- **商品咨询**：直接输入商品问题，我会基于商品库检索并解答\n"
    "- **售后查询**：告诉我「我要退货退款」，查看订单与售后指引（售后中心即将上线）\n"
    "- **评价分析**：告诉我「帮我分析商品口碑」，生成口碑报告（即将上线）\n"
    "- **选购推荐**：告诉我「帮我挑个礼物」，多轮沟通后给出推荐（即将上线）\n"
    + _MULTI_AGENT_TIP
    + "\n请问有什么可以帮到您？"
)

_REPLY_THANKS = (
    "不客气，很高兴能帮到您！\n\n"
    "如果还有其他购物问题，随时告诉我，我随时在线。"
)

_REPLY_BYE = (
    "再见！祝您购物愉快，期待下次为您服务。\n\n"
    "随时欢迎回来挑选商品！"
)

_REPLY_IDENTITY = (
    "我是 **ShopPilot 商城的智能导购助手**，一个面向顾客的电商 AI 服务系统。\n\n"
    "我的能力：\n"
    "- **商品导购问答**：基于商品库的 RAG 检索，即时解答商品问题（已上线）\n"
    "- **售后服务中心**：退货退款与物流查询（即将上线）\n"
    "- **商品评价分析**：AI 口碑报告生成（即将上线）\n"
    "- **智能选购推荐**：多轮沟通精准推荐（即将上线）\n"
    + _MULTI_AGENT_TIP
    + "\n有什么可以帮到您吗？"
)

_REPLY_CAPABILITY = (
    "我能为您提供以下功能：\n\n"
    "**已上线**\n"
    "- 直接输入商品问题 → 商品导购问答（基于商品库检索，流式回答）\n"
    "- 「立即下单」 → 商品详情页模拟下单，订单页可模拟支付\n\n"
    "**即将上线**\n"
    + "- 「怎么退货」 → 售后服务中心，可先在订单页查看订单\n"
    + "- 「帮我分析评价」 → 商品评价分析报告\n"
    + "- 「帮我挑一个」 → 多轮智能选购推荐\n\n"
    + _MULTI_AGENT_TIP
    + "\n直接告诉我您的需求，我会自动路由到最合适的能力。"
)

def _pre_filter(text: str) -> str | None:
    """
    规则前置拦截，返回模板回复字符串；无命中返回 None（继续正常路由）。
    五类社交/元场景均为零 Token 消耗（不调 LLM）。
    """
    t = text.strip()
    # print(f"t-->{t}")# 去首尾空白
    t_lower = _STRIP_TAIL_RE.sub("", t.lower())      # 转小写 + 去末尾标点，得到比对用文本
    # print(f't_lower-->{t_lower}')
    # 类别一：问候（精确匹配整句）
    if t_lower in _HELLO_KEYWORDS:
        return _REPLY_HELLO

    # 类别二：感谢（精确匹配整句）
    if t_lower in _THANKS_KEYWORDS:
        return _REPLY_THANKS

    # 类别三：道别（精确匹配整句）
    if t_lower in _BYE_KEYWORDS:
        return _REPLY_BYE

    # 类别四：身份询问（正则，用原文 t 而非去标点的 t_lower）
    if _IDENTITY_RE.search(t):
        return _REPLY_IDENTITY

    # 类别五：功能询问（正则）
    if _CAPABILITY_RE.search(t):
        return _REPLY_CAPABILITY

    return None                                      # 五类都没命中 → 交给 LLM 路由

# ── LLM 路由 Prompt：把用户输入归到 5 类电商意图之一，返回 JSON ──
_ROUTE_PROMPT = """判断用户需求应路由到哪个功能。

可选功能：
- qa       : 商品咨询与选购问答（参数、价格、对比、推荐，直接提问）
- service  : 售后问题（退货、退款、换货、物流查询、订单异常）
- review   : 商品评价分析（用户要求分析口碑、总结评价、生成报告）
- guide    : 多轮导购推荐（用户要"帮我挑/推荐/选"且需求较复杂，需要多轮沟通）
- clarify  : 意图不明确，无法判断，需要追问

严格按以下 JSON 格式返回，不要有其他内容：
{{"label": "功能名", "reason": "一句话说明判断依据"}}

用户输入：{message}"""

# label → AgentType 映射（agent 枚举仅作 routing_decision 事件载荷占位，
# service/review/guide 在 M4/M5 换成真实 Agent）
_LABEL_TO_AGENT: dict[str, AgentType] = {
    "qa":       AgentType.QA,
    "service":  AgentType.EXAM,      # 占位载荷，M4 换真实售后 Agent
    "review":   AgentType.RESUME,    # 占位载荷，M4 换真实评价 Agent
    "guide":    AgentType.INTERVIEW, # 占位载荷，M5 换真实导购 Agent
    "clarify":  AgentType.QA,
}

# label → ExecutionMode 映射
_LABEL_TO_MODE: dict[str, ExecutionMode] = {
    "qa":      ExecutionMode.SINGLE,
    "service": ExecutionMode.SINGLE,
    "review":  ExecutionMode.SINGLE,
    "guide":   ExecutionMode.SINGLE,
    "clarify": ExecutionMode.CLARIFY,
}

_VALID_LABELS = frozenset(_LABEL_TO_AGENT.keys())    # 合法 label 集合（校验 LLM 输出用）


@dataclass
class _RouteResult:
    """LLM 路由结果，对齐前端展示需要的字段。"""
    label:          str            # "qa"|"service"|"review"|"guide"|"clarify"
    agent_type:     AgentType      # 由 label 映射
    execution_mode: ExecutionMode  # 由 label 映射
    confidence:     float          # LLM 路由固定返回 0.85（无置信度概念，仅供前端展示）
    reason:         str            # 一句话判断依据

async def _llm_route(message: str) -> _RouteResult:
    """
    调用 LLM 对用户输入做跨 Agent 路由判断。

    替代原 IntentRouter（MiniLM 7 分类 + LLM 兜底）——跨 Agent 路由直接用 LLM 判断，
    无需本地分类模型（这个路径调用频率低，LLM 开销可接受）。
    异常时降级返回 qa 路由，不阻断 SSE 流。

    参数：message（用户原始输入）
    返回：_RouteResult（label + agent_type + execution_mode + confidence + reason）
    """
    try:
        llm = get_llm("intent", temperature=0)       # 取"intent"专用模型（3.4 配置），温度0求稳定
        resp = await llm.ainvoke([                    # 调 LLM
            HumanMessage(content=_ROUTE_PROMPT.format(message=message))
        ])
        raw = resp.text.strip()
        parsed = json.loads(raw)                      # 解析 LLM 返回的 JSON
        label = parsed.get("label", "qa").strip().lower()    # 取 label（缺省 qa）
        reason = parsed.get("reason", "LLM 路由判断")        # 取判断依据

        if label not in _VALID_LABELS:               # LLM 返回了非法 label → 降级 qa
            logger.warning("unified_chat.llm_route_unknown_label", label=label, fallback="qa")
            label = "qa"

        logger.info("unified_chat.llm_route_result", label=label, reason=reason)

    except Exception as e:                            # 调用/解析失败 → 降级 qa，不阻断流
        logger.warning("unified_chat.llm_route_failed", error=str(e), fallback="qa")
        label  = "qa"
        reason = "路由判断异常，默认转入智能问答"

    return _RouteResult(                              # 组装路由结果
        label=label,
        agent_type=_LABEL_TO_AGENT[label],           # label → AgentType
        execution_mode=_LABEL_TO_MODE[label],        # label → ExecutionMode
        confidence=0.85,                             # 固定值，仅供前端展示
        reason=reason,
    )

class UnifiedChatRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    message:    str = Field(..., min_length=1, max_length=2000, description="用户输入")  # 非空、限长


def _sse(data: dict) -> dict:
    """把 dict 包成 sse_starlette 要的格式：{"data": "<JSON字符串>"}。ensure_ascii=False 保留中文。"""
    return {"data": json.dumps(data, ensure_ascii=False)}

@router.post("/stream")
async def unified_chat_stream(
    req: UnifiedChatRequest,                          # 请求体：session_id + message
    current_user: dict = Depends(get_current_user),   # 认证依赖（3.6）
):
    """
    统一 AI 助手流式接口（SSE）。

    请求：{session_id, message}
    响应：text/event-stream，事件序列随路由结果不同而不同

    流程：
        1. 规则前置拦截（五类社交/元场景，零 Token 直接返回）
        2. LLM 路由判断（_llm_route，DeepSeek 直接分类，无本地模型）
        3. 推送 routing_decision 事件（前端显示路由卡片）
        4a. qa 路由                    → 流式执行导购问答 Agent
        4b. service/review/guide 路由  → 推送引导卡（跳转对应页面）
        4c. clarify                    → 推送追问提示
    """

    async def event_generator():                      # 异步生成器：逐个 yield SSE 事件
        # ── Step 0：规则前置拦截（零 Token，五类模板回复）──────────
        pre_reply = _pre_filter(req.message)          # 命中则返回模板字符串，否则 None
        if pre_reply is not None:
            yield _sse({"type": "token", "content": pre_reply})  # 模板内容当作一个 token 事件推出
            yield _sse({"type": "done"})              # 直接结束
            return                                    # 不再走路由（省 LLM）

        # ── Step 1：LLM 路由判断 ────────────────────────────
        decision = await _llm_route(req.message)      # 得到 _RouteResult（label/agent_type/mode/...）

        # ── Step 2：推送路由决策卡片（前端显示"已转接到 XX"）──────
        yield _sse({
            "type":           "routing_decision",
            "agent_type":     decision.agent_type.value,
            "agent_display":  _LABEL_DISPLAY.get(decision.label, ""),  # 以 label 为键的中文名
            "confidence":     round(decision.confidence, 4),
            "reason":         decision.reason,
            "execution_mode": decision.execution_mode.value,
        })

        # ── Step 3：按路由结果分发处理 ──────────────────────
        label = decision.label                        # 用 label 决定走哪条分支

        # ── 3a：qa → 流式执行 QA Agent ──────────────────────
        if label == "qa":
            async for event in _stream_qa_agent(req, current_user):  # 把 QA 的流式事件透传出去
                yield event

        # ── 3b：service / review / guide → 引导卡 ─
        elif label in ("service", "review", "guide"):
            guidance = _GUIDANCE_BY_LABEL[label]
            yield _sse({
                "type":         "guidance",
                "message":      guidance["message"],
                "action_label": guidance["action_label"],
                "action_url":   guidance["action_url"],
            })

        # ── 3c：clarify → 追问提示 ───────────────────────────
        else:
            yield _sse({
                "type":    "guidance",
                "message": "您的需求我还不太确定，能否再具体一些？"
                           "例如：想咨询某个商品、查询退货物流，还是让我帮您挑选商品？",
                "action_label": "",
                "action_url":   "",
            })

        yield _sse({"type": "done"})                  # 所有分支最终都推一个 done 收尾

    return EventSourceResponse(event_generator())     # 用 SSE 响应包装生成器


async def _stream_qa_agent(req: UnifiedChatRequest, current_user: dict):
    """
    在统一入口中流式执行 QA Agent，复用 qa.py 的 astream_events 逻辑。

    读取：req.message / req.session_id、current_user
    yield：progress / token / meta / error 四类 SSE 事件
    """
    from backend.core.orchestrator import get_orchestrator   # 懒加载取编排器单例

    orchestrator = get_orchestrator()
    graph = orchestrator._get_agent_graph(AgentType.QA)       # 复用编排器缓存的 QA 图（不重复 build）

    thread_id = build_thread_id(current_user["user_id"], req.session_id)  # 拼检查点 key
    initial_state = {                                         # 构造 QA 图输入 State
        "messages":   [HumanMessage(content=req.message)],
        "student_id": current_user["user_id"],
        "tenant_id":  current_user["tenant_id"],
        "session_id": req.session_id,
        "product_id": None,
        "query_type": "PRECISE",                             # QA 的查询类型（见第 5 章）
    }
    config = {"configurable": {"thread_id": thread_id}}

    answer_mode = None
    confidence  = 0.0
    sources: list[str] = []                                 # 引用来源

    try:
        # astream_events 流式跑 QA 图，逐事件处理
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            evt  = event["event"]                            # 事件类型
            node = event.get("metadata", {}).get("langgraph_node", "")  # 来自哪个节点

            # ① 节点开始且在进度表里 → 推 progress（"检索知识库..."等）
            if evt == "on_chain_start" and node in _PROGRESS_LABELS:
                yield _sse({"type": "progress", "stage": _PROGRESS_LABELS[node]})

            # ② 生成节点的 token 流 → 推 token（答案逐字）
            elif evt == "on_chat_model_stream" and node in _GENERATE_NODES:
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    yield _sse({"type": "token", "content": chunk.content})

            # ③ 生成节点结束 → 回填 answer_mode / sources / confidence（供最后 meta 用）
            elif evt == "on_chain_end" and node in _GENERATE_NODES:
                output = event["data"].get("output", {})
                # 仅在值非空时更新，防止后续 on_chain_end 覆盖已捕获的 "rag" 值
                if output.get("answer_mode"):
                    answer_mode = output["answer_mode"]
                if output.get("sources"):
                    sources = output["sources"]
                confidence = (output.get("structured_output") or {}).get("confidence", confidence)

    except Exception as e:                                   # QA 执行异常 → 推 error 并结束
        logger.error("unified_chat.qa_stream_error", error=str(e), exc_info=True)
        yield _sse({"type": "error", "message": "问答服务异常，请稍后重试"})
        return

    # ④ QA 答完 → 推 meta（答案模式 / 来源 / 置信度），前端据此显示"引用了 N 篇"
    if answer_mode:
        yield _sse({"type": "meta", "answer_mode": answer_mode, "confidence": confidence, "sources": sources})


if __name__ == '__main__':
    print(_pre_filter(text="你好."))