"""Wires the StateGraph.

    START -> intent_classifier
               |-(type_1)-> product_info_agent ------------------\
               \-(type_2)-> auth_agent                            |
                              |-(can_serve)-> data_retrieval_agent|
                              \-(else)---------------------------/
                                                                  \-> response_drafter -> END

The graph deliberately ENDS at response_drafter. The RM's accept / reject / edit decision is
handled by the Streamlit layer and written to `rm_responses`, not by a node — see README.
"""
from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from graph.nodes.auth_agent import auth_agent, route_by_auth
from graph.nodes.data_retrieval_agent import data_retrieval_agent
from graph.nodes.intent_classifier import intent_classifier, route_by_intent
from graph.nodes.product_info_agent import product_info_agent
from graph.nodes.response_drafter import response_drafter
from graph.state import RMState


def build_graph(checkpointer: PostgresSaver | None = None):
    graph = StateGraph(RMState)

    graph.add_node("intent_classifier", intent_classifier)
    graph.add_node("product_info_agent", product_info_agent)
    graph.add_node("auth_agent", auth_agent)
    graph.add_node("data_retrieval_agent", data_retrieval_agent)
    graph.add_node("response_drafter", response_drafter)

    graph.add_edge(START, "intent_classifier")
    graph.add_conditional_edges(
        "intent_classifier",
        route_by_intent,
        {"product_info": "product_info_agent", "authentication": "auth_agent"},
    )
    graph.add_conditional_edges(
        "auth_agent",
        route_by_auth,
        {"retrieve": "data_retrieval_agent", "draft": "response_drafter"},
    )
    graph.add_edge("product_info_agent", "response_drafter")
    graph.add_edge("data_retrieval_agent", "response_drafter")
    graph.add_edge("response_drafter", END)

    return graph.compile(checkpointer=checkpointer)
