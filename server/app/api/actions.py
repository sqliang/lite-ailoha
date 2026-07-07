"""
POST /api/v1/actions/{action_id}/confirm|cancel — 用户确认/取消动作卡片。

============================== 端点 ==============================

  POST /api/v1/actions/{action_id}/confirm
    Body: {"session_id": "..."}（预留，目前未使用）
    Response: {"action_id": "...", "status": "confirmed", "result": {...}}

  POST /api/v1/actions/{action_id}/cancel
    Body: {"session_id": "..."}（预留，目前未使用）
    Response: {"action_id": "...", "status": "cancelled"}

============================== 数据流 ==============================

  iOS 用户点击"确认"或"取消"按钮：
    AnalysisViewModel.confirm(card) / cancel(card)
      → AnalysisService.confirmAction(cardId) / cancelAction(cardId)
        → POST /api/v1/actions/{id}/confirm|cancel
          → 本模块处理请求

  当前（MVP）：
    - 写入内存 dict _action_store（进程重启后丢失）
    - 返回 ActionResponse JSON

  后续（正式版）：
    - 写入 confirmed_actions 表（SQLite）
    - 确认时触发实际系统调用（日历 API、通讯录 API 等）
    - 取消时清理待处理任务

============================== MVP 限制 ==============================

  当前使用内存 dict 存储，原因：
  1. MVP 阶段不依赖外部 API（日历、通讯录均为 Mock）
  2. 动作执行由 iOS 端 Core Data 本地持久化
  3. 简化部署，无需数据库迁移

  生产环境需迁移到 SQLite confirmed_actions 表（schema 已在 database.py 中定义）。
"""
from fastapi import APIRouter
from app.schemas.request import ActionRequest
from app.schemas.response import ActionResponse

router = APIRouter()

# =============================================================================
# 内存存储 — MVP 阶段使用，生产环境迁移到 SQLite confirmed_actions 表
# =============================================================================

# 格式: {action_id: status}
# status 可能值: "confirmed" | "cancelled"
# 进程重启后丢失，客户端依赖 Core Data 本地持久化
_action_store: dict[str, str] = {}


# =============================================================================
# POST /api/v1/actions/{action_id}/confirm — 确认动作卡片
# =============================================================================

@router.post("/api/v1/actions/{action_id}/confirm", response_model=ActionResponse)
async def confirm_action(action_id: str, _body: ActionRequest):
    """用户确认一张动作卡片，标记为待执行。

    ============================== 参数 ==============================
    Args:
        action_id: 动作卡片的唯一 ID（如 "create_meeting-abc123"）
        _body: 请求体（包含 session_id，MVP 阶段未使用，预留）

    ============================== 返回值 ==============================
    ActionResponse:
        {
            "action_id": "create_meeting-abc123",
            "status": "confirmed",
            "result": {
                "success": true,
                "message": "动作已确认，将在后续版本中执行"
            }
        }

    ============================== 后续规划 ==============================
    1. 根据 action_id 前缀（create_meeting / create_contact 等）路由到对应 Service
    2. 调用 CalendarService / ContactService / ReminderService 执行实际操作
    3. 写入 confirmed_actions 表持久化确认记录
    4. 返回执行结果（成功/失败 + 详细信息）
    """
    _action_store[action_id] = "confirmed"
    return ActionResponse(
        action_id=action_id,
        status="confirmed",
        result={"success": True, "message": "动作已确认，将在后续版本中执行"},
    )


# =============================================================================
# POST /api/v1/actions/{action_id}/cancel — 取消动作卡片
# =============================================================================

@router.post("/api/v1/actions/{action_id}/cancel", response_model=ActionResponse)
async def cancel_action(action_id: str, _body: ActionRequest):
    """用户取消一张动作卡片，不执行任何操作。

    ============================== 参数 ==============================
    Args:
        action_id: 动作卡片的唯一 ID
        _body: 请求体（包含 session_id，MVP 阶段未使用，预留）

    ============================== 返回值 ==============================
    ActionResponse:
        {
            "action_id": "create_meeting-abc123",
            "status": "cancelled"
        }

    ============================== 与 confirm 的区别 ==============================
    1. 不执行任何系统调用
    2. 不持久化（MVP 阶段确认也不持久化，但这是有意设计差异）
    3. 客户端只更新本地状态（CardStatus → .cancelled）
    """
    _action_store[action_id] = "cancelled"
    return ActionResponse(action_id=action_id, status="cancelled")
