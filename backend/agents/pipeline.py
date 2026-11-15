"""
Briefing pipeline: a fixed-DAG LangGraph StateGraph.

ARCHITECTURE_DECISIONS.md section 1: company research and interviewer research run
in parallel, then RAG retrieval, then synthesis. Fixed edges, no supervisor.
"""

from langgraph.graph import END, START, StateGraph

from agents.company import company_research_node
from agents.interviewer import interviewer_research_node
from agents.rag import rag_retrieval_node
from agents.state import PipelineState
from agents.synthesis import synthesis_node


def build_graph():
    """Compile the fixed-DAG briefing graph."""
    graph = StateGraph(PipelineState)
    graph.add_node("company_research", company_research_node)
    graph.add_node("interviewer_research", interviewer_research_node)
    graph.add_node("rag_retrieval", rag_retrieval_node)
    graph.add_node("synthesis", synthesis_node)

    graph.add_edge(START, "company_research")
    graph.add_edge(START, "interviewer_research")
    graph.add_edge(["company_research", "interviewer_research"], "rag_retrieval")
    graph.add_edge("rag_retrieval", "synthesis")
    graph.add_edge("synthesis", END)
    return graph.compile()
