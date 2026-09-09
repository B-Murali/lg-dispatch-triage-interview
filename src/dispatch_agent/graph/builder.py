"""Graph assembly."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from dispatch_agent.graph import nodes
from dispatch_agent.graph.state import DispatchState


def build_graph() -> StateGraph:
    """Wire the dispatch triage graph."""
    graph = StateGraph(DispatchState)

    graph.add_node("validate", nodes.validate)
    graph.add_node("triage", nodes.triage)
    graph.add_node("capacity_check", nodes.capacity_check)
    graph.add_node("assign_technician", nodes.assign_technician)
    graph.add_node("queue_for_scheduling", nodes.queue_for_scheduling)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "validate")
    graph.add_edge("validate", "triage")

    graph.add_conditional_edges(
        "triage",
        nodes.route_after_triage,
        {
            "assess": "capacity_check",
            "reject": "finalize",
        },
    )

    graph.add_conditional_edges(
        "capacity_check",
        nodes.route_after_capacity,
        {
            "assign": "assign_technician",
            "queue": "queue_for_scheduling",
        },
    )

    graph.add_edge("assign_technician", END)
    graph.add_edge("queue_for_scheduling", "finalize")
    graph.add_edge("finalize", END)

    return graph
