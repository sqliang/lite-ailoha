"""
Lite Ailoha Deep Agent —— 双模型架构 + SSE 流式包装。

============================== 双模型架构 ==============================

  LLM_MODEL (DeepSeek) — Coordinator 大脑        VISION_MODEL (豆包) — 看图工具
       │                                                 │
       ▼                                                 ▼
  Coordinator Agent                              structure_conversation tool
  - 规划任务、分发子Agent                         - 内部调用 VISION_MODEL 看图
  - 合成结果                                     - 输出结构化对话 JSON
  - 不直接看图
       │
       ├── task("meeting-agent")  → LLM_MODEL
       ├── task("contact-agent")  → LLM_MODEL
       └── task("reminder-agent") → LLM_MODEL

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

from app.config import settings
from app.agent.prompts import COORDINATOR_PROMPT
from app.agent.subagents import get_all_subagents
from app.agent.tools import STRUCTURE_TOOLS, set_shared_image
from app.agent.llm_factory import get_text_llm

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
        # Agent 懒创建，首次调用 stream_analyze() 时才初始化
        self._agent = None

    def _ensure_initialized(self):
        """懒初始化: 首次请求时才创建 Deep Agent。"""
        if self._agent is not None:
            return

        # =================================================================
        # [1/4] 初始化Agent — 打印配置信息
        # =================================================================
        logger.info("[1/4] 初始化Agent | coordinator=%s@%s, vision=%s@%s",
                     settings.llm_model, settings.llm_base_url,
                     settings.vision_model, settings.vision_base_url)

        # =================================================================
        # [2/4] 组装 Deep Agent
        # Coordinator = LLM_MODEL (DeepSeek) — 大脑，规划 + 分发
        # structure_conversation 工具内部调 VISION_MODEL (豆包) — 看图
        # 子Agent 由 get_all_subagents() 注入 LLM_MODEL — 领域提取
        # =================================================================
        # 阶段一: tools 不含 generate_insight（洞察在阶段二生成）
        self._agent = create_deep_agent(
            model=get_text_llm(),
            system_prompt=COORDINATOR_PROMPT,
            tools=STRUCTURE_TOOLS,  # 只有 structure_conversation
            subagents=get_all_subagents(),
        )
        logger.info("[2/4] DeepAgent组装完成 | coordinator=%s, tools=%d, subagents=%d",
                     settings.llm_model,
                     len(STRUCTURE_TOOLS), 3)

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
        Yields (阶段一):
            {"type": "struct", "data": {"participants":[...], "messages":[...]}}
            {"type": "card",   "data": {"id":"...", "type":"create_meeting", "summary":"..."}}
            {"type": "error",  "data": {"code":"AGENT_ERROR", "message":"..."}}
            {"type": "done"}

        ============================== 数据流 ==============================
        所有事件的 type 和数据由 _parse_stream_event() 根据
        LangGraph v2 astream_events 中的 tool call 名称分派。
        """
        # 懒初始化: 首次请求时才创建 LLM 和 Agent
        self._ensure_initialized()

        # =================================================================
        # [3/4] 构建多模态消息: 文字指令 + 截图
        # =================================================================
        prompt = _build_coordinator_message(image_base64, user_context)
        logger.info("[3/4] 构建Coordinator消息 | image=%d chars, user_context=%d chars",
                     len(image_base64), len(user_context))

        try:
            # =================================================================
            # [4/4] 设置共享图片数据，开始 astream_events
            # 不从 LLM 参数获取 base64（LLM 无法复制 42KB+ base64 数据）
            # =================================================================
            set_shared_image(image_base64, user_context)
            logger.info("[4/4] 已设置共享图片，开始astream_events循环")
            async for event in self._agent.astream_events(
                {"messages": [{"role": "user", "content": prompt}]},
                version="v2",
                config={"recursion_limit": 100},
            ):
                parsed = _parse_stream_event(event)
                if parsed is not None:
                    yield parsed

            # 正常完成
            logger.info("Agent分析完成")
            yield {"type": "done"}

        except Exception:
            logger.exception("Agent streaming failed for image_len=%d", len(image_base64))
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

def _build_coordinator_message(image_base64: str, user_context: str) -> str:
    """
    构建发送给 Coordinator 的纯文本消息。

    Coordinator 使用 LLM_MODEL（DeepSeek），不支持 image_url 内容类型。
    图片数据已通过 set_shared_image() 存入共享变量，
    structure_conversation 工具会从共享变量读取图片并调用 VISION_MODEL。

    返回纯文本字符串（非多模态列表），避免 DeepSeek API 报 unknown variant `image_url`。
    """
    text = COORDINATOR_PROMPT
    if user_context:
        text += f"\n\n用户补充说明: {user_context}"

    text += (
        "\n\n[系统提示] 用户已上传一张聊天截图，"
        "图片数据已就绪。请立即调用 structure_conversation 工具来解析截图。"
    )

    return text


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
            result = _tool_output_to_struct_event(tool_output)
            if result:
                logger.info("  ↳ struct解析 | participants=%s",
                             result.get("data", {}).get("participants", []))
            return result

        # 四个 domain tool → card 事件
        if tool_name in _CARD_TOOL_NAMES:
            result = _tool_output_to_card_event(tool_name, tool_output)
            if result:
                logger.info("  ↳ card解析 | type=%s, id=%s",
                             result.get("data", {}).get("type"),
                             result.get("data", {}).get("id"))
            return result

        # generate_insight → insight 事件
        if tool_name == "generate_insight":
            result = _tool_output_to_insight_event(tool_output)
            if result:
                # 安全获取长度（ToolMessage 无 len）
                out_text = tool_output.content if hasattr(tool_output, 'content') else tool_output
                out_len = len(str(out_text)) if out_text else 0
                logger.info("  ↳ insight解析 | output_len=%d chars", out_len)
            return result

    # on_chain_end 不再转换为 insight（洞察在阶段二独立生成）
    return None


# =============================================================================
# Tool 输出 → SSE 事件 转换函数
# =============================================================================

def _tool_output_to_struct_event(output) -> dict | None:
    """
    将 structure_conversation tool 的输出转换为 struct 事件。

    ============================== 输入 ==============================
    output: VISION_MODEL 返回的 JSON 字符串或 ToolMessage 对象
            格式: {"participants": [...], "messages": [{time, speaker, content}]}

    ============================== 输出 ==============================
    {"type": "struct", "data": {"participants": [...], "messages": [...]}}
    这个数据会:
      1. 作为 SSE event:struct 流到 iOS 客户端
      2. 写入 analyze_sessions.structured_conversation 字段
    """
    import json as _json

    # LangGraph v2 可能返回 ToolMessage 对象，提取 content
    if hasattr(output, 'content'):
        output = output.content
    if not isinstance(output, str):
        output = str(output)

    try:
        result = _json.loads(output)
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


def _tool_output_to_card_event(tool_name: str, output) -> dict | None:
    """
    将子 Agent 的 domain tool 输出转换为 card 事件。

    ============================== 输入 ==============================
    tool_name: create_meeting / create_contact / update_contact / create_reminder
    output: tool 返回的 JSON 字符串或 ToolMessage，包含 action 详情

    ============================== 输出 ==============================
    {"type": "card", "data": {"id": "uuid", "type": "create_meeting", "summary": "..."}}
    这个数据会:
      1. 作为 SSE event:card 流到 iOS 客户端
      2. 写入 analyze_sessions.cards JSON 数组
    """
    import json as _json
    # LangGraph v2 可能返回 ToolMessage 对象，提取 content
    if hasattr(output, 'content'):
        output = output.content
    if not isinstance(output, str):
        output = str(output)
    try:
        result = _json.loads(output)
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


def _tool_output_to_insight_event(output) -> dict | None:
    """
    将 generate_insight tool 的输出转换为 insight 事件。

    ============================== 输入 ==============================
    output: generate_insight tool 返回的 JSON 字符串、ToolMessage 或纯文本

    ============================== 输出 ==============================
    {"type": "insight", "data": "AI 洞察文本"}
    这个数据会:
      1. 作为 SSE event:insight 流到 iOS 客户端
      2. 写入 analyze_sessions.insight 字段
    """
    import json as _json
    # LangGraph v2 可能返回 ToolMessage 对象，提取 content
    if hasattr(output, 'content'):
        output = output.content
    if not isinstance(output, str):
        output = str(output)
    try:
        result = _json.loads(output)
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
