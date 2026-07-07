"""
Agent module — Lite Ailoha DeepAgent architecture.

Exports:
    LiteAilohaAgent  — the primary deep agent (coordinator + 3 subagents)
    ALL_TOOLS        — flat tool list for single-agent fallback
    create_single_agent — simple non-deep agent for environments without deepagents
"""
from app.agent.deep_agent import LiteAilohaAgent
from app.agent.tools import ALL_TOOLS

__all__ = ["LiteAilohaAgent", "ALL_TOOLS"]
