# backend/agents/service/graph.py
# 售后客服图：load_order → route_by_type →(条件边) 三轨之一 → aggregate → save_ticket
# 一次性任务：无 checkpointer（审批走 DB 轻量 HitL，不使用 interrupt/resume）
from langgraph.graph import StateGraph, START, END

from backend.agents.service.state import ServiceState
from backend.agents.service.nodes import (
    load_order_node,
    route_by_type,
    logistics_track_node,
    refund_track_node,
    exchange_track_node,
    aggregate_node,
    save_ticket_node,
)


def build_service_graph():
    builder = StateGraph(ServiceState)

    builder.add_node("load_order",  load_order_node)
    builder.add_node("logistics",   logistics_track_node)
    builder.add_node("refund",      refund_track_node)
    builder.add_node("exchange",    exchange_track_node)
    builder.add_node("aggregate",   aggregate_node)
    builder.add_node("save_ticket", save_ticket_node)

    builder.add_edge(START, "load_order")
    builder.add_conditional_edges(
        "load_order",
        route_by_type,
        {"logistics": "logistics", "refund": "refund", "exchange": "exchange"},
    )
    builder.add_edge("logistics",   "aggregate")
    builder.add_edge("refund",      "aggregate")
    builder.add_edge("exchange",    "aggregate")
    builder.add_edge("aggregate",   "save_ticket")
    builder.add_edge("save_ticket", END)
    return builder.compile()
