"""
GET /api/v1/sessions/{session_id} — 查询分析会话的完整数据。

用途: 事后质量评估
  1. 获取 VISION_MODEL 产出的结构化对话（structured_conversation）
  2. 获取 Agent 产出的动作卡片列表（cards）
  3. 获取 AI 洞察（insight）
  4. 将以上数据与原始截图对照，评估各环节质量

数据来源: analyze_sessions 表（POST /api/v1/analyze SSE 流完成后写入）
"""
import json
from fastapi import APIRouter, HTTPException
from app.storage.database import get_db
from app.schemas.response import SessionResponse

router = APIRouter()


@router.get("/api/v1/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """
    根据 session_id 获取一次分析会话的完整数据。

    Returns:
        SessionResponse:
        - session_id: 会话 ID
        - structured_conversation: VISION_MODEL 解析的结构化对话
          格式: {"participants": [...], "messages": [{time, speaker, content}]}
        - cards: Agent 识别的动作卡片列表
          格式: [{"id": "...", "type": "create_meeting", "summary": "..."}]
        - insight: AI 洞察文本
        - created_at: 创建时间

    Raises:
        404: 指定的 session_id 不存在
    """
    db = await get_db()

    # 查询 analyze_sessions 表
    cursor = await db.execute(
        "SELECT session_id, structured_conversation, cards, insight, created_at "
        "FROM analyze_sessions WHERE session_id = ?",
        (session_id,)
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # 将存储的 JSON 字符串解析为 Python 对象
    structured = json.loads(row["structured_conversation"]) if row["structured_conversation"] else None
    cards = json.loads(row["cards"]) if row["cards"] else []

    return SessionResponse(
        session_id=row["session_id"],
        structured_conversation=structured,
        cards=cards,
        insight=row["insight"],
        created_at=row["created_at"],
    )
