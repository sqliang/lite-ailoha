"""
POST /api/v1/actions/{action_id}/confirm|cancel

Handles user confirmation or cancellation of proposed action cards.
"""
from fastapi import APIRouter
from app.schemas.request import ActionRequest
from app.schemas.response import ActionResponse

router = APIRouter()


# In-memory action store for MVP (migrate to SQLite in production)
_action_store: dict[str, str] = {}


@router.post("/api/v1/actions/{action_id}/confirm", response_model=ActionResponse)
async def confirm_action(action_id: str, _body: ActionRequest):
    """Confirm a proposed action for execution."""
    _action_store[action_id] = "confirmed"
    return ActionResponse(
        action_id=action_id,
        status="confirmed",
        result={"success": True, "message": "动作已确认，将在后续版本中执行"},
    )


@router.post("/api/v1/actions/{action_id}/cancel", response_model=ActionResponse)
async def cancel_action(action_id: str, _body: ActionRequest):
    """Cancel a proposed action without execution."""
    _action_store[action_id] = "cancelled"
    return ActionResponse(action_id=action_id, status="cancelled")
