"""
Pydantic 响应和 SSE 事件模型。

SSE 事件类型及对应的数据模型:
  event:struct  → StructEvent    — 结构化对话（参与者、时间线、消息列表）
  event:card    → CardEvent      — 动作卡片（会议/联系人/提醒）
  event:insight → InsightEvent   — AI 洞察建议
  event:error   → ErrorEvent     — 错误信息
  event:done    → DoneEvent      — 流结束标记

REST 响应:
  ActionResponse   — 确认/取消操作的结果
  SessionResponse  — GET /api/v1/sessions/{id} 的完整会话数据
  HealthResponse   — 健康检查
"""
from typing import Optional
from pydantic import BaseModel, Field

# -- 标准卡片类型（前后端统一）-----------------------------------------------

CANONICAL_TYPES = {"create_meeting", "create_contact", "update_contact", "create_reminder"}

# -- 动作卡片 ---------------------------------------------------------------

class ActionCard(BaseModel):
    """AI 识别出的一个可执行动作。

    字段说明:
    - id: 服务端生成的卡片唯一标识
    - type: 动作类型（create_meeting / create_contact / update_contact / create_reminder）
    - summary: 人类可读的中文摘要描述
    """
    id: str = Field(description="服务端生成的 UUID")
    type: str = Field(description="动作类型: create_meeting | create_contact | update_contact | create_reminder")
    summary: str = Field(description="中文摘要，如'为张三创建会议「产品评审」，时间 周四 15:00'")
    fields: dict = Field(default_factory=dict, description="结构化字段，透传 tool 返回的完整 JSON")

# -- SSE 事件负载 ------------------------------------------------------------

class StructEvent(BaseModel):
    """SSE 'struct' 事件 —— VISION_MODEL 解析出的结构化对话。

    这是整个 Agent 管道的第一个产出，也是质量评估的核心数据:
    - 参与者是否正确识别？
    - 消息时间线是否准确？
    - 消息内容归属是否对？

    字段说明:
    - event: 固定为 "struct"
    - participants: 对话参与者姓名列表，如 ["sqliang", "张洪银"]
    - messages: 消息列表，每条包含 time/speaker/content
    """
    event: str = "struct"
    session_state: str = Field(default="STRUCTURED", description="会话状态")
    participants: list[str] = Field(default_factory=list, description="对话参与者姓名列表")
    messages: list[dict] = Field(default_factory=list, description="消息列表 [{time, speaker, content}]")


class CardEvent(BaseModel):
    """SSE 'card' 事件 —— 一张待确认的动作卡片。

    字段说明:
    - event: 固定为 "card"
    - card: ActionCard 对象（id + type + summary）
    """
    event: str = "card"
    session_state: str = Field(default="EXTRACTING", description="会话状态")
    card: ActionCard


class InsightEvent(BaseModel):
    """SSE 'insight' 事件 —— AI 生成的跨域洞察建议。

    字段说明:
    - event: 固定为 "insight"
    - insight: 中文洞察文本
    """
    event: str = "insight"
    session_state: str = Field(default="GENERATING", description="会话状态")
    insight: str


class ErrorEvent(BaseModel):
    """SSE 'error' 事件 —— 处理过程中的错误。

    字段说明:
    - event: 固定为 "error"
    - code: 机器可读错误码（EMPTY_INPUT / AGENT_ERROR / INTERNAL_ERROR）
    - message: 人类可读的中文错误描述
    """
    event: str = "error"
    session_state: str = Field(default="", description="错误发生时的会话状态（可能为空）")
    code: str = Field(description="错误码: EMPTY_INPUT | AGENT_ERROR | INTERNAL_ERROR")
    message: str = Field(description="中文错误描述")


class DoneEvent(BaseModel):
    """SSE 'done' 事件 —— 流结束。

    字段说明:
    - event: 固定为 "done"
    - data: 空字典（预留扩展）
    """
    event: str = "done"
    session_state: str = Field(default="READY", description="会话状态: READY（阶段一完成）或 COMPLETED（阶段二完成）")
    data: dict = Field(default_factory=dict)

# -- REST 响应 ---------------------------------------------------------------

class ActionResponse(BaseModel):
    """确认/取消操作的响应。

    字段说明:
    - action_id: 操作的卡片 ID
    - status: "confirmed" | "cancelled" | "failed"
    - result: 执行结果（成功时包含 success 和 message）
    - error: 错误信息（失败时）
    """
    action_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None


class SessionResponse(BaseModel):
    """GET /api/v1/sessions/{id} 的完整会话数据。

    用于事后质量评估:
    - 对比 structured_conversation 和原始截图，验证 VISION_MODEL 的理解准确性
    - 对比 cards 和 structured_conversation，验证 Agent 的动作识别质量
    - 查看 insight 的质量

    字段说明:
    - session_id: 分析会话唯一标识
    - session_state: 会话当前状态（PENDING → ... → COMPLETED）
    - structured_conversation: VISION_MODEL 解析的结构化对话（JSON）
    - cards: Agent 识别出的所有动作卡片列表
    - insight: AI 生成的洞察建议
    - created_at: 会话创建时间（ISO 8601）
    """
    session_id: str
    session_state: str = "READY"
    structured_conversation: Optional[dict] = None
    cards: list[dict] = Field(default_factory=list)
    insight: Optional[str] = None
    created_at: Optional[str] = None


class HealthResponse(BaseModel):
    """健康检查响应。

    字段说明:
    - status: 固定为 "healthy"
    - version: API 版本号
    """
    status: str = "healthy"
    version: str = "0.1.0"
