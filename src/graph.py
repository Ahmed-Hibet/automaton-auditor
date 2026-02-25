from langgraph.graph import StateGraph
from src.state import AgentState


def build_graph():
    builder = StateGraph(AgentState)
    return builder.compile()