# backend/agents/guide/graph.py
# 多轮导购图（M5a：平移自 Interview 拓扑）——条件边只分流「继续/生成报告」
from langgraph.graph import StateGraph, START, END

from backend.agents.guide.state import GuideState, GuideStage
from backend.agents.guide.nodes import (
    load_context_node,
    check_stage,
    generate_response_node,
    generate_report_node,
    save_report_node,
    save_memory_node,
)
from backend.core.memory import get_memory_saver


def _route_after_check_stage(state):
    if state.get("current_stage") == GuideStage.FINISHED:
        return "generate_report"
    return "generate_response"


def build_guide_graph():
    builder = StateGraph(GuideState)

    builder.add_node("load_context",      load_context_node)
    builder.add_node("check_stage",       check_stage)
    builder.add_node("generate_response", generate_response_node)
    builder.add_node("generate_report",   generate_report_node)
    builder.add_node("save_report",       save_report_node)
    builder.add_node("save_memory",       save_memory_node)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "check_stage")
    builder.add_conditional_edges(
        "check_stage",
        _route_after_check_stage,
        {"generate_report": "generate_report", "generate_response": "generate_response"},
    )
    builder.add_edge("generate_response", "save_memory")
    builder.add_edge("generate_report",   "save_report")
    builder.add_edge("save_report",       "save_memory")
    builder.add_edge("save_memory", END)

    return builder.compile(checkpointer=get_memory_saver("guide"))
