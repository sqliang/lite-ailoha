"""
GET /api/v1/sessions/{id} — 查询分析会话
POST /api/v1/sessions/{id}/insight — 阶段二: 生成洞察
"""
import json
import logging
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from deepagents import create_deep_agent
from app.storage.database import get_db
from app.schemas.response import SessionResponse, InsightEvent, ErrorEvent, DoneEvent
from app.agent.llm_factory import get_text_llm
from app.agent.tools import INSIGHT_TOOLS

logger = logging.getLogger(__name__)
router = APIRouter()

# 阶段二 insight agent 单例（懒初始化，避免每次请求重新创建）
_insight_agent = None


def _get_insight_agent():
    global _insight_agent
    if _insight_agent is None:
        _insight_agent = create_deep_agent(
            model=get_text_llm(),
            system_prompt="你是一个智能助理。当用户要求生成洞察时，调用 generate_insight 工具。",
            tools=INSIGHT_TOOLS,
            subagents=[],
        )
    return _insight_agent


@router.get("/api/v1/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """查询一次分析会话的完整数据。"""
    db = await get_db()
    cursor = await db.execute(
        "SELECT session_id, session_state, structured_conversation, cards, insight, created_at "
        "FROM analyze_sessions WHERE session_id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionResponse(
        session_id=row["session_id"],
        session_state=row["session_state"] or "READY",
        structured_conversation=json.loads(row["structured_conversation"]) if row["structured_conversation"] else None,
        cards=json.loads(row["cards"]) if row["cards"] else [],
        insight=row["insight"],
        created_at=row["created_at"],
    )


@router.post("/api/v1/sessions/{session_id}/insight")
async def generate_insight(session_id: str):
    """阶段二: 基于用户确认结果生成洞察。"""
    db = await get_db()

    # 查询 session
    cursor = await db.execute(
        "SELECT session_id, session_state, structured_conversation, cards "
        "FROM analyze_sessions WHERE session_id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row["session_state"] in ("PENDING", "STRUCTURING", "STRUCTURE_FAILED"):
        raise HTTPException(status_code=400, detail="阶段一未完成")

    # 查询用户确认/取消记录
    cards = json.loads(row["cards"]) if row["cards"] else []
    confirmed_ids = [c["id"] for c in cards]
    confirmed = []
    cancelled = []

    if confirmed_ids:
        placeholders = ",".join("?" for _ in confirmed_ids)
        confirmed_cursor = await db.execute(
            f"SELECT id, type, summary, status FROM confirmed_actions WHERE id IN ({placeholders})",
            confirmed_ids,
        )
        async for cr in confirmed_cursor:
            if cr["status"] == "confirmed":
                confirmed.append(dict(cr))
            else:
                cancelled.append(dict(cr))

    # 更新状态为 GENERATING
    await db.execute(
        "UPDATE analyze_sessions SET session_state='GENERATING' WHERE session_id=?",
        (session_id,),
    )
    await db.commit()

    message = _build_insight_message(
        structured=row["structured_conversation"],
        confirmed=confirmed,
        cancelled=cancelled,
    )

    async def event_stream():
        event_id = 0
        insight_text = ""
        try:
            async for event in _get_insight_agent().astream_events(
                {"messages": [{"role": "user", "content": message}]},
                version="v2",
            ):
                if event.get("event") == "on_tool_end" and event.get("name") == "generate_insight":
                    event_id += 1
                    output = event.get("data", {}).get("output", "")
                    if hasattr(output, "content"):
                        output = output.content
                    insight_text = str(output) if output else ""

                    insight_event = InsightEvent(
                        session_state="GENERATING",
                        insight=insight_text,
                    )
                    yield {"event": "insight", "id": str(event_id), "data": insight_event.model_dump_json()}

            # SSE 流结束后持久化 insight
            if insight_text:
                db2 = await get_db()
                await db2.execute(
                    "UPDATE analyze_sessions SET insight=?, session_state='COMPLETED' WHERE session_id=?",
                    (insight_text, session_id),
                )
                await db2.commit()
                logger.info("Insight persisted for session %s", session_id)

            event_id += 1
            done = DoneEvent(session_state="COMPLETED")
            yield {"event": "done", "id": str(event_id), "data": done.model_dump_json()}

        except Exception:
            logger.exception("Insight generation failed for session %s", session_id)
            event_id += 1
            err = ErrorEvent(code="INSIGHT_ERROR", message="洞察生成失败")
            yield {"event": "error", "id": str(event_id), "data": err.model_dump_json()}

    return EventSourceResponse(event_stream())


def _build_insight_message(structured: str | None, confirmed: list[dict], cancelled: list[dict]) -> str:
    """构造阶段二的 Coordinator 消息。"""
    msg = """## 任务: 基于用户决策生成洞察建议

你之前已经完成了聊天截图的结构化分析和卡片提取。现在用户已经查看了卡片并做出了决策。

"""
    if structured:
        msg += f"### 结构化对话\n```json\n{structured}\n```\n\n"

    msg += "### 用户已确认的卡片\n"
    if confirmed:
        for c in confirmed:
            msg += f"- [{c['type']}] {c['summary']}\n"
    else:
        msg += "- (无)\n"

    msg += "\n### 用户已取消的卡片\n"
    if cancelled:
        for c in cancelled:
            msg += f"- [{c['type']}] {c['summary']}\n"
    else:
        msg += "- (无)\n"

    msg += """
请调用 generate_insight 工具，基于:
1. 用户确认了哪些卡片
2. 用户取消了哪些卡片
3. 原始结构化对话上下文

生成有帮助的洞察和建议。输出中文。
"""
    return msg
