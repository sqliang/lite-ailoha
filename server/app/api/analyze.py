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

============================== SSE 协议细节 ==============================

  每个事件包含三行：
    event: <事件类型>   — 客户端据此路由到不同的解析逻辑
    id: <递增整数>      — sse-starlette 要求 id 为字符串类型
    data: <JSON>        — 事件负载，格式因事件类型而异

  客户端（iOS AnalysisService.emit()）使用两层策略解析 data 行：
    1. 用 StreamPayload 通用容器解码，根据 event 字段分发
    2. 失败时根据 SSE event: header 直接解码对应类型

============================== 数据持久化 ==============================

  SSE 流完成后，本次分析的结构化对话、卡片列表、洞察文本
  会写入 analyze_sessions 表，可通过 GET /api/v1/sessions/{id} 查询。

  持久化发生在流结束后（不阻塞 SSE 推送），原因：
  - cards 列表在流式过程中逐步收集
  - insight 文本在流末尾才完整
  - 流中异常不会影响已推送的事件

============================== 架构流程 ==============================

  iOS 发送截图 → Coordinator (VISION_MODEL) 看图
  → structure_conversation → SSE event:struct
  → task() 委派子 Agent (LLM_MODEL) → SSE event:card × N
  → generate_insight → SSE event:insight
  → SSE event:done
  → 写入 analyze_sessions 表

============================== 错误处理 ==============================

  两层错误捕获：
  1. 输入验证层（analyze 函数）：image 和 user_context 均为空时，
     返回一个单事件的 error SSE 流（不进入 Agent 管道）
  2. Agent 异常层（event_stream 内部）：Agent 管道中任何异常被
     try/except 捕获，yield 一个 error 事件后流结束
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

# 取消标记 — 被 cancel 端点写入，SSE generator 读取
_cancelled_sessions: set[str] = set()

# =============================================================================
# Agent 单例 — 懒加载，避免 import 时 API key 未配置或网络不通导致启动失败
# =============================================================================

# 首次调用 analyze 端点时才创建 LiteAilohaAgent 实例
# 创建过程会初始化 VISION_MODEL + LLM_MODEL 两个 ChatOpenAI 实例
_agent: LiteAilohaAgent | None = None


def _get_agent() -> LiteAilohaAgent:
    """
    获取 Agent 单例，首次调用时懒初始化。

    懒加载原因：
    - Agent 初始化会调用 ChatOpenAI，需要验证 API key 和网络连通性
    - 如果放在模块级别 import，无网络或 key 失效时服务直接无法启动
    - 懒加载允许 health endpoint 等其他路由正常工作，仅 analyze 请求时才报错

    线程安全：FastAPI 的 async event loop 是单线程模型，
    _agent 赋值是原子操作，竞态条件风险极低。
    """
    global _agent
    if _agent is None:
        _agent = LiteAilohaAgent()
    return _agent


# =============================================================================
# POST /api/v1/analyze — 主分析端点
# =============================================================================

@router.post("/api/v1/analyze")
async def analyze(request: AnalyzeRequest):
    """
    分析聊天截图，流式返回结构化对话 + 动作卡片 + 洞察建议。

    ============================== 处理流程（7 步） ==============================

    [1/7] 提取并清洗请求参数（image base64 + user_context）
    [2/7] 输入验证：二者至少有一个非空
    [3/7] 生成 session_id，用于后续质量评估查询
    [4/7] 进入 event_stream() 异步生成器，开启 SSE 推送
    [5/7] 逐事件消费 stream_analyze() 返回的 dict，转换为 SSE 格式 yield
    [6/7] 流完成后，写入 analyze_sessions 表持久化
    [7/7] 异常捕获：yield error 事件，记录 stack trace

    ============================== 入参 ==============================
    Args:
        request.image: 聊天截图的 base64 编码（iOS ImageProcessor 已压缩至 max 1024px）
        request.user_context: 用户可选的补充文字说明

    ============================== 出参（SSE 事件流） ==============================
    event:struct → event:card × N → event:insight → event:done
    """
    # [1/7] 提取请求参数
    image_b64 = (request.image or "").strip()
    user_context = (request.user_context or "").strip()

    logger.info("[1/7] 收到分析请求 | image=%dKB, user_context=%dchars",
                 len(image_b64) // 1024, len(user_context))

    # =========================================================================
    # [2/7] 输入验证：image 和 user_context 至少一个非空
    # 空输入时返回一个单事件 error SSE 流，不进入 Agent 管道
    # =========================================================================
    if not image_b64 and not user_context:
        logger.warning("[2/7] 输入验证失败 | 图片和文本均为空")

        async def error_stream():
            """空输入时的错误 SSE 流：仅包含一个 error 事件。"""
            err = ErrorEvent(
                code="EMPTY_INPUT",
                message="请选择一张聊天截图，或输入文字说明",
            )
            # id 必须为字符串（sse-starlette 要求）
            yield {"event": "error", "id": str(1), "data": err.model_dump_json()}

        return EventSourceResponse(error_stream())

    logger.info("[2/7] 输入验证通过")

    # =========================================================================
    # [3/7] 生成会话 ID，创建数据库记录（PENDING 状态）
    # =========================================================================
    session_id = str(uuid.uuid4())
    logger.info("[3/7] 生成会话ID | session_id=%s", session_id)
    db = await get_db()
    await db.execute(
        "INSERT INTO analyze_sessions (session_id, session_state) VALUES (?, 'PENDING')",
        (session_id,),
    )
    await db.commit()

    # =========================================================================
    # event_stream — 核心 SSE 异步生成器
    #
    # 这是一个嵌套的 async generator，原因：
    # - EventSourceResponse 需要一个 async generator 作为参数
    # - generator 内部调用 Agent 的 stream_analyze()，消费其 AsyncIterator
    # - 每收到一个事件，立即通过 yield 推送给 iOS 客户端
    #
    # 累积器（structured / cards / insight_text）的作用：
    # - SSE 是单向推送，无法回溯
    # - 流完成后需要一次性写入数据库
    # - 累积器在流式过程中收集完整数据，流结束后统一写入
    # =========================================================================

    async def event_stream():
        event_id = 0

        # --- 累积器：流式过程中收集数据，流完成后统一写入数据库 ---
        structured: dict | None = None  # 结构化对话（struct 事件数据）
        cards: list[dict] = []          # 所有 ActionCard 的 dict 列表

        try:
            logger.info("[4/7] 开始SSE流式分析 | session_id=%s", session_id)

            # 第一个事件：session_id，让 iOS 知道后续要关联的会话
            yield {"event": "meta", "id": "0",
                   "data": json.dumps({"session_id": session_id})}

            # 显式推送第一步 status（不依赖 LangGraph 事件）
            yield {"event": "status", "id": str(1),
                   "data": json.dumps({"step": "structuring", "message": "正在理解聊天内容…"}, ensure_ascii=False)}

            # =================================================================
            # [4/7] 消费 Agent 管道的事件流
            # stream_analyze() 返回 AsyncIterator[dict]，每个 dict 包含:
            #   {"type": "struct|card|insight|error|done", "data": ...}
            # =================================================================
            async for event in _get_agent().stream_analyze(image_b64, user_context):
                # 检查是否被取消
                if session_id in _cancelled_sessions:
                    _cancelled_sessions.discard(session_id)
                    yield {"event": "cancelled", "id": str(event_id + 1), "data": json.dumps({"session_state": "CANCELLED"})}
                    await db.execute(
                        "UPDATE analyze_sessions SET session_state='CANCELLED' WHERE session_id=?",
                        (session_id,),
                    )
                    await db.commit()
                    logger.info("Session %s cancelled by user", session_id)
                    return
                event_id += 1
                event_type = event["type"]

                # =============================================================
                # [5/7] 事件分发表 — 将 Agent 事件转换为 SSE 格式
                # 每种事件类型对应不同的 Schema 实例化和 yield 格式
                # =============================================================
                match event_type:
                    # --- 结构化对话 ---
                    case "struct":
                        structured = event["data"]
                        struct_event = StructEvent(
                            session_state="STRUCTURED",
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
                        # 结构化完成，推送提取阶段 status
                        yield {"event": "status", "id": str(event_id),
                               "data": json.dumps({"step": "extracting", "message": "正在识别待办事项…"}, ensure_ascii=False)}

                    # --- 动作卡片 ---
                    case "card":
                        card_data = event["data"]
                        card = ActionCard(
                            id=card_data["id"],
                            type=card_data["type"],
                            summary=card_data["summary"],
                            fields=card_data.get("fields", {}),
                        )
                        # ActionCard.model_dump() 序列化为 dict，存入累计器
                        cards.append(card.model_dump())
                        card_event = CardEvent(card=card)
                        yield {
                            "event": "card",
                            "id": str(event_id),
                            "data": card_event.model_dump_json(),
                        }
                        logger.info("[5/7] SSE事件→card | type=%s, summary=%s",
                                     card_data["type"], card_data["summary"][:50])

                    # --- AI 洞察（阶段一不再生成，保留兼容旧事件） ---
                    case "insight":
                        insight_event = InsightEvent(insight=str(event["data"]))
                        yield {
                            "event": "insight",
                            "id": str(event_id),
                            "data": insight_event.model_dump_json(),
                        }
                        logger.info("[5/7] SSE事件→insight | text_len=%dchars",
                                     len(str(event["data"])))

                    # --- 错误事件 ---
                    # Agent 内部错误（LLM 调用失败、tool 执行异常等）
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
            # [6/7] SSE 流完成 → 统一 UPDATE 所有累积数据到 analyze_sessions
            # =================================================================
            try:
                _write_db = await get_db()
                state = "EXTRACTED" if cards else "NO_CARDS"
                await _write_db.execute(
                    "UPDATE analyze_sessions SET structured_conversation=?, cards=?, session_state=? WHERE session_id=?",
                    (json.dumps(structured, ensure_ascii=False) if structured else None,
                     json.dumps(cards, ensure_ascii=False) if cards else "[]",
                     state, session_id),
                )
                await _write_db.commit()
                logger.info("[6/7] 持久化完成 | session_id=%s, cards=%d, state=%s",
                             session_id, len(cards), state)
            except Exception as db_err:
                logger.error("[6/7] 持久化失败 | session_id=%s, error=%s", session_id, db_err)

        except Exception:
            # =================================================================
            # [7/7] 管道异常捕获 — Agent 或 SSE 推送过程中的任何未处理异常
            # 记录完整 stack trace，向客户端推送最后一个 error 事件
            # =================================================================
            logger.exception("[7/7] SSE流异常 | session_id=%s", session_id)
            event_id += 1
            err = ErrorEvent(code="INTERNAL_ERROR", message="服务端内部异常，请稍后重试")
            yield {
                "event": "error",
                "id": str(event_id),
                "data": err.model_dump_json(),
            }

    # FastAPI 会自动检测 EventSourceResponse 并设置正确的 Content-Type 头
    return EventSourceResponse(event_stream())
