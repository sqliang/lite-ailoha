"""
Lite Ailoha Deep Agent —— 双模型架构 + SSE 流式包装。

============================== 双模型架构 ==============================

  _vision_llm (VISION_MODEL)          _text_llm (LLM_MODEL)
       │                                      │
       ▼                                      ▼
  Coordinator Agent                    子 Agent (Meeting/Contact/Reminder)
  - 看图理解聊天截图                    - 从结构化 JSON 文本中提取信息
  - 调用 structure_conversation         - 不需要 vision 能力
  - 调用 generate_insight               - 可选用更便宜/更快的模型
  - 委派 task() 给子 Agent

============================== SSE 事件流 ==============================

  POST /api/v1/analyze (image + user_context)
       │
       ▼
  Coordinator 调用 structure_conversation
       │
       ▼ on_tool_end: structure_conversation
  SSE event:struct → 结构化对话 JSON
       │            → iOS 实时展示 + 写入 sessions 表
       ▼
  Coordinator 委派 task("meeting-agent", structured_text)
              task("contact-agent", structured_text)
              task("reminder-agent", structured_text)
       │
       ▼ on_tool_end: create_meeting / create_contact / ...
  SSE event:card × N
       │
       ▼
  Coordinator 调用 generate_insight
       │
       ▼ on_tool_end: generate_insight
  SSE event:insight
       │
       ▼
  SSE event:done

============================== 流事件解析 ==============================

  _parse_stream_event() 监听 LangGraph v2 astream_events 中的
  on_tool_end 事件，按 tool name 分派:

    structure_conversation → {"type": "struct", "data": {...}}
    create_meeting         → {"type": "card", "data": {...}}
    create_contact         → {"type": "card", "data": {...}}
    update_contact         → {"type": "card", "data": {...}}
    create_reminder        → {"type": "card", "data": {...}}
    generate_insight       → {"type": "insight", "data": "..."}

References:
    https://docs.langchain.com/oss/python/deepagents/overview
    https://docs.langchain.com/oss/python/deepagents/customization
"""
import logging
from typing import AsyncIterator

from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI

from app.config import settings
from app.agent.prompts import COORDINATOR_PROMPT
from app.agent.subagents import get_all_subagents
from app.agent.tools import STRUCTURE_TOOLS, INSIGHT_TOOLS

logger = logging.getLogger(__name__)

# =============================================================================
# Tool name → SSE event type 映射
# =============================================================================

# 这些 tool 的输出会被拦截并转换为 SSE card 事件
_CARD_TOOL_NAMES = {"create_meeting", "create_contact", "update_contact", "create_reminder"}

# Tool name → 标准 card type 映射
_TOOL_TO_CARD_TYPE = {
    "create_meeting":  "create_meeting",
    "create_contact":  "create_contact",
    "update_contact":  "update_contact",
    "create_reminder": "create_reminder",
}


class LiteAilohaAgent:
    """
    Lite Ailoha Deep Agent — 双模型 + DeepAgents 子 Agent 架构。

    使用方式:
        agent = LiteAilohaAgent()
        async for event in agent.stream_analyze(image_base64, user_context):
            # event 是 dict: {"type": "struct|card|insight|error|done", "data": ...}
    """

    def __init__(self):
        # LLM 实例懒创建，首次调用 stream_analyze() 时才初始化
        # 避免 import 时在没有 API key 或代理配置异常时报错
        self._vision_llm = None
        self._text_llm = None
        self._agent = None

    def _ensure_initialized(self):
        """懒初始化: 首次请求时才创建 LLM 实例和 Deep Agent。"""
        if self._agent is not None:
            return

        # =================================================================
        # VISION_MODEL — Coordinator 专用，看图理解聊天截图
        # =================================================================
        self._vision_llm = ChatOpenAI(
            model=settings.vision_model,
            api_key=settings.vision_api_key or settings.llm_api_key or None,
            base_url=settings.vision_base_url or settings.llm_base_url or None,
            temperature=0.3,
        )

        # =================================================================
        # LLM_MODEL — 子 Agent 专用，纯文本处理结构化对话 JSON
        # =================================================================
        self._text_llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key or settings.vision_api_key or None,
            base_url=settings.llm_base_url or settings.vision_base_url or None,
            temperature=0.3,
        )

        # =================================================================
        # 组装 Deep Agent
        # =================================================================
        self._agent = create_deep_agent(
            model=self._vision_llm,
            system_prompt=COORDINATOR_PROMPT,
            tools=STRUCTURE_TOOLS + INSIGHT_TOOLS,
            subagents=get_all_subagents(),
        )

    # =========================================================================
    # 流式分析 — SSE 端点的主入口
    # =========================================================================

    async def stream_analyze(
        self, image_base64: str, user_context: str = ""
    ) -> AsyncIterator[dict]:
        """
        分析聊天截图并以结构化事件流式返回。

        ============================== 参数 ==============================
        Args:
            image_base64: 聊天截图的 base64 编码（JPEG/PNG）
            user_context: 用户可选的补充说明文字

        ============================== 返回值 ==============================
        Yields:
            {"type": "struct",  "data": {"participants":[...], "messages":[...]}}
            {"type": "card",    "data": {"id":"...", "type":"create_meeting", "summary":"..."}}
            {"type": "insight", "data": "AI 洞察文本"}
            {"type": "error",   "data": {"code":"AGENT_ERROR", "message":"..."}}
            {"type": "done"}

        ============================== 数据流 ==============================
        所有事件的 type 和数据由 _parse_stream_event() 根据
        LangGraph v2 astream_events 中的 tool call 名称分派。
        """
        # 懒初始化: 首次请求时才创建 LLM 和 Agent
        self._ensure_initialized()

        # 构建多模态消息: 文字指令 + 截图
        prompt = _build_multimodal_prompt(image_base64, user_context)
        logger.info(
            "Starting deep agent analysis (image=%d chars, user_context=%d chars)",
            len(image_base64), len(user_context)
        )

        try:
            # =================================================================
            # astream_events(version="v2")
            # 会发出所有 tool call 事件——包括 Coordinator 自己的 tool call
            # 和子 Agent 内部的 tool call。每个 tool call 完成时触发
            # on_tool_end 事件，由 _parse_stream_event() 分派为 SSE 事件。
            # =================================================================
            async for event in self._agent.astream_events(
                {"messages": [{"role": "user", "content": prompt}]},
                version="v2",
            ):
                parsed = _parse_stream_event(event)
                if parsed is not None:
                    yield parsed

            yield {"type": "done"}

        except Exception:
            logger.exception("Agent streaming failed")
            yield {
                "type": "error",
                "data": {
                    "code": "AGENT_ERROR",
                    "message": "分析过程异常，请稍后重试",
                },
            }


# =============================================================================
# 内部函数
# =============================================================================

def _build_multimodal_prompt(image_base64: str, user_context: str) -> list[dict]:
    """
    构建多模态消息 —— 文字指令 + 截图图片。

    ============================== 消息结构 ==============================
    返回的 content 是一个 list:
      [{"type": "text", "text": "系统指令 + 用户补充"},
       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]

    Coordinator (GPT-4o 等多模态模型) 可以同时接收文字和图片，
    直接"看"截图来理解对话结构和内容。
    """
    text_prompt = COORDINATOR_PROMPT
    if user_context:
        text_prompt += f"\n\n用户补充说明: {user_context}"

    return [
        {
            "type": "text",
            "text": text_prompt,
        },
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_base64}",
                "detail": "high",
            },
        },
    ]


def _parse_stream_event(event: dict) -> dict | None:
    """
    将 LangGraph v2 流事件转换为 Lite Ailoha SSE 事件。

    ============================== 事件类型分派 ==============================

    监听 on_tool_end 事件（tool 执行完成的信号），按 tool name 分派:

      structure_conversation  → struct 事件
        输出 VISION_MODEL 解析的结构化对话 JSON
        包含 participants 和 messages 列表

      create_meeting          → card 事件
      create_contact          → card 事件
      update_contact          → card 事件
      create_reminder         → card 事件
        子 Agent 的 tool call 输出，每个 tool call 对应一张 ActionCard

      generate_insight        → insight 事件
        Coordinator 在所有子 Agent 完成后生成的跨域洞察
    """
    event_type = event.get("event", "")

    # -- Tool 执行完成（涵盖 Coordinator 和子 Agent 的 tool call）--
    if event_type == "on_tool_end":
        tool_name = event.get("name", "")
        tool_output = event.get("data", {}).get("output", "")

        # structure_conversation → struct 事件
        if tool_name == "structure_conversation":
            return _tool_output_to_struct_event(tool_output)

        # 四个 domain tool → card 事件
        if tool_name in _CARD_TOOL_NAMES:
            return _tool_output_to_card_event(tool_name, tool_output)

        # generate_insight → insight 事件
        if tool_name == "generate_insight":
            return _tool_output_to_insight_event(tool_output)

    # -- Chain 结束（fallback: 如果 generate_insight 没有被显式调用）--
    if event_type == "on_chain_end" and event.get("name") == "LangGraph":
        output = event.get("data", {}).get("output", {})
        messages = output.get("messages", [])
        if messages:
            last_msg = messages[-1]
            content = getattr(last_msg, "content", "")
            if content and isinstance(content, str) and len(content) > 10:
                return {"type": "insight", "data": content}

    return None


# =============================================================================
# Tool 输出 → SSE 事件 转换函数
# =============================================================================

def _tool_output_to_struct_event(output: str) -> dict | None:
    """
    将 structure_conversation tool 的输出转换为 struct 事件。

    ============================== 输入 ==============================
    output: VISION_MODEL 返回的 JSON 字符串
            格式: {"participants": [...], "messages": [{time, speaker, content}]}

    ============================== 输出 ==============================
    {"type": "struct", "data": {"participants": [...], "messages": [...]}}
    这个数据会:
      1. 作为 SSE event:struct 流到 iOS 客户端
      2. 写入 analyze_sessions.structured_conversation 字段
    """
    import json as _json
    try:
        result = _json.loads(output) if isinstance(output, str) else output
    except (_json.JSONDecodeError, TypeError):
        # JSON 解析失败: VISION_MODEL 可能返回了非 JSON 文本
        # 返回原始文本作为 fallback
        return {"type": "struct", "data": {"raw": str(output)}}

    return {
        "type": "struct",
        "data": {
            "participants": result.get("participants", []),
            "messages": result.get("messages", []),
        },
    }


def _tool_output_to_card_event(tool_name: str, output: str) -> dict | None:
    """
    将子 Agent 的 domain tool 输出转换为 card 事件。

    ============================== 输入 ==============================
    tool_name: create_meeting / create_contact / update_contact / create_reminder
    output: tool 返回的 JSON 字符串，包含 action 详情

    ============================== 输出 ==============================
    {"type": "card", "data": {"id": "uuid", "type": "create_meeting", "summary": "..."}}
    这个数据会:
      1. 作为 SSE event:card 流到 iOS 客户端
      2. 写入 analyze_sessions.cards JSON 数组
    """
    import json as _json
    try:
        result = _json.loads(output) if isinstance(output, str) else output
    except (_json.JSONDecodeError, TypeError):
        return None

    card_type = _TOOL_TO_CARD_TYPE.get(tool_name)
    if not card_type:
        return None

    summary = _build_summary(card_type, result)

    return {
        "type": "card",
        "data": {
            "id": f"{card_type}-{hash(summary) & 0x7FFFFFFF:08x}",
            "type": card_type,
            "summary": summary,
        },
    }


def _tool_output_to_insight_event(output: str) -> dict | None:
    """
    将 generate_insight tool 的输出转换为 insight 事件。

    ============================== 输入 ==============================
    output: generate_insight tool 返回的 JSON 字符串或纯文本

    ============================== 输出 ==============================
    {"type": "insight", "data": "AI 洞察文本"}
    这个数据会:
      1. 作为 SSE event:insight 流到 iOS 客户端
      2. 写入 analyze_sessions.insight 字段
    """
    import json as _json
    try:
        result = _json.loads(output) if isinstance(output, str) else output
    except (_json.JSONDecodeError, TypeError):
        return {"type": "insight", "data": str(output)} if output else None

    if isinstance(result, dict):
        insight_text = result.get("context", "") or _json.dumps(result, ensure_ascii=False)
    else:
        insight_text = str(result)

    return {"type": "insight", "data": insight_text} if insight_text else None


def _build_summary(card_type: str, args: dict) -> str:
    """根据 card type 和 tool 参数构建中文摘要文案。"""
    match card_type:
        case "create_meeting":
            title = args.get("title", "未命名会议")
            participants = args.get("participants", [])
            dt = args.get("datetime", "待定")
            ppl = "、".join(participants) if participants else "待定参与人"
            return f"为{ppl}创建会议「{title}」，时间 {dt}"
        case "create_contact":
            name = args.get("name", "未知")
            title_val = args.get("title", "")
            phone = args.get("phone", "")
            detail = title_val or phone or ""
            return f"添加联系人：{name}" + (f"（{detail}）" if detail else "")
        case "update_contact":
            name = args.get("name", "未知")
            field = args.get("field", "")
            value = args.get("value", "")
            return f"更新联系人「{name}」的{field}为「{value}」"
        case "create_reminder":
            content = args.get("content", args.get("title", "未命名提醒"))
            due = args.get("due_date", "")
            return f"创建提醒：{content}" + (f"（截止：{due}）" if due else "")
    return "未知动作"
