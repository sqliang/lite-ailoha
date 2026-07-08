"""
GET /api/v1/sessions/{id} — 查询分析会话
POST /api/v1/sessions/{id}/insight — 阶段二: 生成洞察
POST /api/v1/sessions/{id}/cancel — 中断分析
"""
import json
import logging
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from deepagents import create_deep_agent
from app.storage.database import get_db
from app.schemas.response import SessionResponse, InsightEvent, ErrorEvent, DoneEvent
from app.agent.llm_factory import get_text_llm
from app.agent.tools import INSIGHT_TOOLS
from app.agent.tools.insight import set_insight_context
from app.api.analyze import _cancelled_sessions
from app.services.contact import contact_service
from app.services.calendar import calendar_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/v1/sessions/{session_id}/cancel")
async def cancel_session(session_id: str):
    """中断正在进行的分析。"""
    _cancelled_sessions.add(session_id)
    logger.info("Session %s marked for cancellation", session_id)
    return {"session_id": session_id, "status": "cancelled"}

# 阶段二 insight agent 单例（懒初始化，避免每次请求重新创建）
_insight_agent = None


def _get_insight_agent():
    global _insight_agent
    if _insight_agent is None:
        _insight_agent = create_deep_agent(
            model=get_text_llm(),
            system_prompt=(
                "你是一个智能助理。当用户确认了一张操作卡片后，"
                "立即调用 generate_insight 工具来生成分析结果。"
            ),
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
async def generate_insight(session_id: str, request: Request):
    """阶段二: 基于用户确认结果生成洞察。"""
    db = await get_db()

    # 解析 iOS POST body
    try:
        body = await request.json()
    except Exception:
        body = {}
    card_id = body.get("card_id", "")
    card_type = body.get("card_type", "")
    card_summary = body.get("card_summary", "")
    device_contacts = body.get("device_contacts", [])
    device_events = body.get("device_events", [])
    device_reminders = body.get("device_reminders", [])

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
    if not cards:
        raise HTTPException(status_code=400, detail={"code": "NO_CARDS", "message": "该会话没有卡片可确认"})
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

    if not confirmed:
        raise HTTPException(status_code=400, detail={"code": "NO_CONFIRMED_CARDS", "message": "请先确认至少一张卡片"})

    logger.info("[洞察] 请求 session_id=%s card_count=%d confirmed=%d", session_id, len(cards), len(confirmed))

    # 查询服务端数据
    contacts = await contact_service.list_all() if contact_service else []
    calendar = await calendar_service.list_events() if calendar_service else []

    # 设置共享变量（数据不从 LLM 参数过）
    set_insight_context(
        card_id=card_id, card_type=card_type, card_summary=card_summary,
        structured=row["structured_conversation"],
        confirmed=confirmed, cancelled=cancelled,
        server_contacts=contacts, server_calendar=calendar,
        device_contacts=device_contacts, device_events=device_events, device_reminders=device_reminders,
    )

    # 更新状态为 GENERATING
    await db.execute(
        "UPDATE analyze_sessions SET session_state='GENERATING' WHERE session_id=?",
        (session_id,),
    )
    await db.commit()

    async def event_stream():
        event_id = 0
        insight_text = ""
        try:
            async for event in _get_insight_agent().astream_events(
                {"messages": [{"role": "user", "content": "请调用 generate_insight 工具，分析用户确认的操作卡片。"}]},
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
                logger.info("[洞察] 完成 session_id=%s insight_len=%d", session_id, len(insight_text))

            event_id += 1
            done = DoneEvent(session_state="COMPLETED")
            yield {"event": "done", "id": str(event_id), "data": done.model_dump_json()}

        except Exception:
            logger.exception("Insight generation failed for session %s", session_id)
            event_id += 1
            err = ErrorEvent(code="INSIGHT_ERROR", message="洞察生成失败")
            yield {"event": "error", "id": str(event_id), "data": err.model_dump_json()}

    return EventSourceResponse(event_stream())


def _build_insight_message(
    structured: str | None,
    confirmed: list[dict],
    cancelled: list[dict],
    contacts: list[dict] | None = None,
    calendar: list[dict] | None = None,
    device_contacts: list[dict] | None = None,
    device_events: list[dict] | None = None,
    device_reminders: list[dict] | None = None,
) -> str:
    """构造阶段二的 Coordinator 消息，整合服务端 + 设备端数据。"""
    msg = """## 任务：基于用户决策生成洞察建议

针对用户当前确认的这张卡片，分析其可行性和潜在冲突。

"""
    if structured:
        msg += f"### 原始对话上下文\n```json\n{structured}\n```\n\n"

    msg += "### 用户确认的卡片\n"
    if confirmed:
        for c in confirmed:
            msg += f"- [{c['type']}] {c['summary']}\n"
    else:
        msg += "- (无)\n"

    msg += "\n### 用户取消的卡片\n"
    if cancelled:
        for c in cancelled:
            msg += f"- [{c['type']}] {c['summary']}\n"
    else:
        msg += "- (无)\n"

    if contacts:
        msg += f"\n### 已有联系人（服务端，共 {len(contacts)} 人）\n"
        for ct in contacts[:20]:
            msg += f"- {ct.get('name','?')} | {ct.get('title','')} | {ct.get('company','')} | 电话:{ct.get('phone','')} | 邮箱:{ct.get('email','')} | 会面:{ct.get('meeting_count',0)}次\n"

    if device_contacts:
        msg += f"\n### 设备端联系人（iOS 通讯录，共 {len(device_contacts)} 人）\n"
        for dc in device_contacts[:20]:
            msg += f"- {dc.get('name','?')} | {dc.get('title','')} | {dc.get('company','')} | 电话:{dc.get('phones',[])} | 邮箱:{dc.get('emails',[])}\n"

    if calendar or device_events:
        msg += "\n### 已有日历事件\n"
        for ev in (calendar or []):
            msg += f"- {ev.get('datetime','')} | {ev.get('title','')} | 参与人: {ev.get('participants',[])}\n"
        for ev in (device_events or []):
            msg += f"- {ev.get('start','')}~{ev.get('end','')} | {ev.get('title','')} | 地点:{ev.get('location','')}\n"

    if device_reminders:
        msg += f"\n### 设备端提醒（共 {len(device_reminders)} 条）\n"
        for dr in device_reminders[:20]:
            msg += f"- {dr.get('title','')} | 截止:{dr.get('dueDate','')} | 优先级:{dr.get('priority',0)}\n"

    msg += """
请调用 generate_insight 工具。输出 JSON 包含：
- action: "generate_insight"
- card_id: 卡片 ID
- verdict: approved | approved_with_note | conflict | unnecessary
- conflicts: [冲突描述...]
- suggestion: 调整建议
- adjusted_action: 调整后的动作（仅 verdict=conflict 时）
- next_steps: [后续步骤...]

输出中文。
"""
    return msg
