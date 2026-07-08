"""
POST /api/v1/actions/{action_id}/confirm|cancel — 用户确认/取消动作卡片。
"""
import logging
import json
from fastapi import APIRouter, HTTPException
from app.schemas.request import ActionRequest
from app.schemas.response import ActionResponse
from app.storage.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

CANONICAL_TYPES = {"create_meeting", "create_contact", "update_contact", "create_reminder"}


@router.post("/api/v1/actions/{action_id}/confirm", response_model=ActionResponse)
async def confirm_action(action_id: str, body: ActionRequest):
    """用户确认一张动作卡片。"""
    # 校验 type
    if body.type and body.type not in CANONICAL_TYPES:
        raise HTTPException(status_code=400, detail={"code": "INVALID_TYPE", "message": f"不支持的卡片类型: {body.type}"})
    # 校验 summary
    if not body.summary or not body.summary.strip():
        raise HTTPException(status_code=400, detail={"code": "EMPTY_SUMMARY", "message": "卡片摘要不能为空"})

    try:
        db = await get_db()
        await db.execute(
            "INSERT OR REPLACE INTO confirmed_actions (id, type, summary, fields, status) VALUES (?, ?, ?, ?, 'confirmed')",
            (action_id, body.type or "", body.summary or "", json.dumps(body.fields, ensure_ascii=False)),
        )
        await db.commit()
    except Exception:
        logger.exception("持久化失败 action_id=%s", action_id)
        raise HTTPException(status_code=500, detail={"code": "DB_ERROR", "message": "持久化失败"})

    logger.info("[确认] action_id=%s type=%s summary=%.80s", action_id, body.type, body.summary or "")
    return ActionResponse(action_id=action_id, status="confirmed",
                          result={"success": True, "message": "动作已确认"})


@router.post("/api/v1/actions/{action_id}/cancel", response_model=ActionResponse)
async def cancel_action(action_id: str, body: ActionRequest):
    """用户取消一张动作卡片。"""
    if body.type and body.type not in CANONICAL_TYPES:
        raise HTTPException(status_code=400, detail={"code": "INVALID_TYPE", "message": f"不支持的卡片类型: {body.type}"})

    try:
        db = await get_db()
        await db.execute(
            "INSERT OR REPLACE INTO confirmed_actions (id, type, summary, fields, status) VALUES (?, ?, ?, ?, 'cancelled')",
            (action_id, body.type or "", body.summary or "", json.dumps(body.fields, ensure_ascii=False)),
        )
        await db.commit()
    except Exception:
        logger.exception("持久化失败 action_id=%s", action_id)
        raise HTTPException(status_code=500, detail={"code": "DB_ERROR", "message": "持久化失败"})

    logger.info("[取消] action_id=%s type=%s", action_id, body.type)
    return ActionResponse(action_id=action_id, status="cancelled")


@router.post("/api/v1/actions/{action_id}/execute")
async def execute_action(action_id: str):
    """标记动作已执行（用户点击洞察中的执行按钮）。"""
    logger.info("[执行] 收到请求 action_id=%s", action_id)
    try:
        db = await get_db()
        await db.execute(
            "UPDATE confirmed_actions SET status='executed' WHERE id=?",
            (action_id,),
        )
        await db.commit()
        logger.info("[执行] 持久化成功 action_id=%s", action_id)
    except Exception:
        logger.exception("[执行] 持久化失败 action_id=%s", action_id)
        raise HTTPException(status_code=500, detail={"code": "DB_ERROR", "message": "执行状态持久化失败"})
    return {"action_id": action_id, "status": "executed"}
