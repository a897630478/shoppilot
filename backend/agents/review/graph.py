# backend/agents/review/graph.py
# 一次性线性图（无 checkpointer）——build_review_graph 必须保持为函数，
# 不要写成 build_review_graph = build_review_graph()（resume/graph.py 的历史坑）
from langgraph.graph import StateGraph, START, END

from backend.agents.review.state import ReviewState
from backend.agents.review.nodes import (
    load_reviews_node,
    run_dimensions_node,
    mine_pros_cons_node,
    generate_summary_node,
    save_results_node,
)


def build_review_graph():
    builder = StateGraph(ReviewState)

    builder.add_node("load_reviews",     load_reviews_node)
    builder.add_node("run_dimensions",   run_dimensions_node)
    builder.add_node("mine_pros_cons",   mine_pros_cons_node)
    builder.add_node("generate_summary", generate_summary_node)
    builder.add_node("save_results",     save_results_node)

    builder.add_edge(START, "load_reviews")
    builder.add_edge("load_reviews", "run_dimensions")
    builder.add_edge("run_dimensions", "mine_pros_cons")
    builder.add_edge("mine_pros_cons", "generate_summary")
    builder.add_edge("generate_summary", "save_results")
    builder.add_edge("save_results", END)
    return builder.compile()
