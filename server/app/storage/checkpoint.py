"""
LangGraph checkpoint setup using SQLite.

The checkpointer persists agent state across multi-turn conversations,
enabling session resumption and task continuation.
"""
from langgraph.checkpoint.sqlite import SqliteSaver
from app.config import settings


def create_checkpointer() -> SqliteSaver:
    """Create a LangGraph SqliteSaver checkpointer.

    The checkpointer stores agent state (messages, tool calls, intermediate steps)
    in the same SQLite database used for contacts and actions.

    Returns:
        A SqliteSaver instance ready to be passed to a LangGraph agent.
    """
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    return SqliteSaver.from_conn_string(db_path)
