"""
POST /api/v1/actions/{action_id}/confirm|cancel — 用户确认/取消动作卡片。

============================== 端点 ==============================

  POST /api/v1/actions/{action_id}/confirm
    Body: {"session_id": "...", "type": "create_meeting", "summary": "..."}
    Response: {"action_id": "...", "status": "confirmed", "result": {...}}

  POST /api/v1/actions/{action_id}/cancel
    Body: {"session_id": "...", "type": "create_reminder", "summary": "..."}
    Response: {"action_id": "...", "status": "cancelled"}

============================== 数据流 ==============================

  iOS 用户点击"确认"或"取消":
    → POST /api/v1/actions/{id}/confirm|cancel
      → 写入 confirmed_actions 表（SQLite 持久化）
      → 返回 ActionResponse

============================== 与阶段二的关系 ==============================

  confirmed_actions 表记录是阶段二（洞察生成）的输入数据之一。
  阶段二根据用户确认/取消了哪些卡片来生成个性化洞察。
"""
from fastapi import APIRouter
from app.schemas.request import ActionRequest
from app.schemas.response import ActionResponse
from app.storage.database import get_db

router = APIRouter()


# =============================================================================
# POST /api/v1/actions/{action_id}/confirm — 确认动作卡片
# =============================================================================

@router.post("/api/v1/actions/{action_id}/confirm", response_model=ActionResponse)
async def confirm_action(action_id: str, body: ActionRequest):
    """用户确认一张动作卡片，持久化到 confirmed_actions 表。"""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO confirmed_actions (id, type, summary, status) "
        "VALUES (?, ?, ?, 'confirmed')",
        (action_id, body.type or "", body.summary or ""),
    )
    await db.commit()
    return ActionResponse(
        action_id=action_id,
        status="confirmed",
        result={"success": True, "message": "动作已确认"},
    )


# =============================================================================
# POST /api/v1/actions/{action_id}/cancel — 取消动作卡片
# =============================================================================

@router.post("/api/v1/actions/{action_id}/cancel", response_model=ActionResponse)
async def cancel_action(action_id: str, body: ActionRequest):
    """用户取消一张动作卡片，持久化取消状态。"""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO confirmed_actions (id, type, summary, status) "
        "VALUES (?, ?, ?, 'cancelled')",
        (action_id, body.type or "", body.summary or ""),
    )
    await db.commit()
    return ActionResponse(action_id=action_id, status="cancelled")
