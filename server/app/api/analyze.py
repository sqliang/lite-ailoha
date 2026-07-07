"""
POST /api/v1/analyze — SSE 流式分析端点。

============================== 请求 ==============================
  POST /api/v1/analyze
  Content-Type: application/json
  Accept: text/event-stream
  {
    "image": "<base64 编码的聊天截图>",
    "user_context": "可选补充说明"
  }

============================== SSE 事件序列 ==============================

  1. event:struct  — VISION_MODEL 解析的结构化对话
     data: {"event":"struct","participants":["sqliang","张洪银"],
            "messages":[{"time":"...","speaker":"...","content":"..."}]}

  2. event:card × N — Agent 识别的动作卡片
     data: {"event":"card","card":{"id":"...","type":"create_meeting","summary":"..."}}

  3. event:insight  — AI 洞察建议
     data: {"event":"insight","insight":"张三已有2个待定会议..."}

  4. event:error    — 处理错误（可选）
     data: {"event":"error","code":"AGENT_ERROR","message":"错误描述"}

  5. event:done     — 流结束
     data: {"event":"done","data":{}}

============================== 数据持久化 ==============================

  SSE 流完成后，本次分析的结构化对话、卡片列表、洞察文本
  会写入 analyze_sessions 表，可通过 GET /api/v1/sessions/{id} 查询。

============================== 架构流程 ==============================

  iOS 发送截图 → Coordinator (VISION_MODEL) 看图
  → structure_conversation → SSE event:struct
  → task() 委派子 Agent (LLM_MODEL) → SSE event:card × N
  → generate_insight → SSE event:insight
  → SSE event:done
  → 写入 analyze_sessions 表
"""
import json
import uuid
import logging
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from app.schemas.request import AnalyzeRequest
from app.schemas.response import (
    StructEvent, CardEvent, InsightEvent, ErrorEvent, DoneEvent, ActionCard
)
from app.agent import LiteAilohaAgent
from app.storage.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# Singleton agent — 懒加载，首次请求时才创建（避免 import 时 API key 未配置报错）
_agent: LiteAilohaAgent | None = None


def _get_agent() -> LiteAilohaAgent:
    global _agent
    if _agent is None:
        _agent = LiteAilohaAgent()
    return _agent


@router.post("/api/v1/analyze")
async def analyze(request: AnalyzeRequest):
    """
    分析聊天截图，流式返回结构化对话 + 动作卡片 + 洞察建议。

    入参:
      - image: 聊天截图的 base64 编码（iOS 端已压缩至 max 1024px）
      - user_context: 用户可选的补充文字

    出参 (SSE):
      event:struct → event:card × N → event:insight → event:done
    """
    image_b64 = (request.image or "").strip()
    user_context = (request.user_context or "").strip()

    # =========================================================================
    # [1/7] 收到分析请求 — 打印请求摘要
    # =========================================================================
    logger.info("[1/7] 收到分析请求 | image=%dKB, user_context=%dchars",
                 len(image_b64) // 1024, len(user_context))

    # =========================================================================
    # [2/7] 输入验证: image 和 user_context 至少一个非空
    # =========================================================================
    if not image_b64 and not user_context:
        logger.warning("[2/7] 输入验证失败 | 图片和文本均为空")
        async def error_stream():
            err = ErrorEvent(
                code="EMPTY_INPUT",
                message="请选择一张聊天截图，或输入文字说明",
            )
            yield {"event": "error", "id": str(1), "data": err.model_dump_json()}
        return EventSourceResponse(error_stream())
    logger.info("[2/7] 输入验证通过")

    # =========================================================================
    # [3/7] 生成会话 ID — 用于后续 GET /api/v1/sessions/{id} 查询
    # =========================================================================
    session_id = str(uuid.uuid4())
    logger.info("[3/7] 生成会话ID | session_id=%s", session_id)

    async def event_stream():
        event_id = 0
        # =====================================================================
        # 累积器 — SSE 流式过程中收集结构化对话和卡片数据
        # 流完成后一起写入 analyze_sessions 表
        # =====================================================================
        structured: dict | None = None
        cards: list[dict] = []
        insight_text: str = ""

        try:
            # =================================================================
            # [4/7] 开始 SSE 流式分析
            # =================================================================
            logger.info("[4/7] 开始SSE流式分析 | session_id=%s", session_id)
            async for event in _get_agent().stream_analyze(image_b64, user_context):
                event_id += 1
                event_type = event["type"]

                match event_type:
                    # --- 结构化对话 (VISION_MODEL 解析结果) ---
                    case "struct":
                        structured = event["data"]
                        struct_event = StructEvent(
                            participants=structured.get("participants", []),
                            messages=structured.get("messages", []),
                        )
                        yield {
                            "event": "struct",
                            "id": str(event_id),
                            "data": struct_event.model_dump_json(),
                        }
                        logger.info("[5/7] SSE事件→struct | participants=%d, messages=%d",
                                     len(structured.get("participants", [])),
                                     len(structured.get("messages", [])))

                    # --- 动作卡片 (子 Agent tool call 结果) ---
                    case "card":
                        card_data = event["data"]
                        card = ActionCard(
                            id=card_data["id"],
                            type=card_data["type"],
                            summary=card_data["summary"],
                        )
                        cards.append(card.model_dump())
                        card_event = CardEvent(card=card)
                        yield {
                            "event": "card",
                            "id": str(event_id),
                            "data": card_event.model_dump_json(),
                        }
                        logger.info("[5/7] SSE事件→card | type=%s, summary=%s",
                                     card_data["type"], card_data["summary"][:50])

                    # --- AI 洞察 (generate_insight tool 结果) ---
                    case "insight":
                        insight_text = event["data"]
                        insight_event = InsightEvent(insight=insight_text)
                        yield {
                            "event": "insight",
                            "id": str(event_id),
                            "data": insight_event.model_dump_json(),
                        }
                        logger.info("[5/7] SSE事件→insight | text_len=%dchars",
                                     len(insight_text))

                    # --- 错误事件 ---
                    case "error":
                        err = ErrorEvent(
                            code=event["data"].get("code", "INTERNAL_ERROR"),
                            message=event["data"].get("message", "未知错误"),
                        )
                        yield {
                            "event": "error",
                            "id": str(event_id),
                            "data": err.model_dump_json(),
                        }
                        logger.error("[5/7] SSE事件→error | code=%s, msg=%s",
                                      err.code, err.message)

                    # --- 流结束 ---
                    case "done":
                        done = DoneEvent()
                        yield {
                            "event": "done",
                            "id": str(event_id),
                            "data": done.model_dump_json(),
                        }
                        logger.info("[5/7] SSE事件→done | total_events=%d", event_id)

            # =================================================================
            # [6/7] SSE 流完成后，将本次分析的完整数据写入 analyze_sessions 表
            # 存储内容:
            #   - session_id: 唯一标识，可通过 GET /api/v1/sessions/{id} 查询
            #   - structured_conversation: VISION_MODEL 的结构化对话 JSON
            #   - cards: 所有 ActionCard 的 JSON 数组
            #   - insight: AI 洞察文本
            #   - created_at: 写入时间
            # =================================================================
            try:
                db = await get_db()
                await db.execute(
                    "INSERT INTO analyze_sessions (session_id, structured_conversation, cards, insight) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        session_id,
                        json.dumps(structured, ensure_ascii=False) if structured else None,
                        json.dumps(cards, ensure_ascii=False) if cards else "[]",
                        insight_text or None,
                    ),
                )
                await db.commit()
                logger.info("[6/7] 持久化完成 | session_id=%s, cards=%d, insight=%dchars",
                             session_id, len(cards), len(insight_text))
            except Exception as db_err:
                logger.error("[6/7] 持久化失败 | session_id=%s, error=%s", session_id, db_err)

        except Exception:
            logger.exception("[7/7] SSE流异常 | session_id=%s", session_id)
            event_id += 1
            err = ErrorEvent(code="INTERNAL_ERROR", message="服务端内部异常，请稍后重试")
            yield {
                "event": "error",
                "id": str(event_id),
                "data": err.model_dump_json(),
            }

    return EventSourceResponse(event_stream())
