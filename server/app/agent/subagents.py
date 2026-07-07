"""
子 Agent 定义 —— Coordinator 通过内置 task() 工具动态委派。

============================== 架构 ==============================

  Coordinator (VISION_MODEL) — 看图 + 结构化
      │
      ├── task("meeting-agent",  structured_json)  → LLM_MODEL
      ├── task("contact-agent",  structured_json)  → LLM_MODEL
      └── task("reminder-agent", structured_json)  → LLM_MODEL

每个子 Agent 使用独立的 LLM_MODEL 实例（纯文本，不需要 vision）。

============================== 子 Agent 说明 ==============================

每个 SubAgent 定义包含:
  - name: Coordinator 通过 task() 调用时的标识符
  - description: 告诉 Coordinator 何时委派给此 Agent
  - system_prompt: 领域专用指令（接收结构化对话 JSON，输出 tool call）
  - tools: 该 Agent 可调用的工具函数
  - model: LLM_MODEL 实例（纯文本模型，独立于 Coordinator 的 VISION_MODEL）

============================== 数据流 ==============================

  Coordinator 调用 task("meeting-agent", "请分析以下结构化对话...")
    → Meeting Subagent 被创建（isolated context）
    → Subagent 读取结构化对话 JSON
    → 调用 create_meeting tool
    → tool call 结果通过 on_tool_end 冒泡到 SSE 流
    → Subagent 返回结果给 Coordinator
    → Coordinator 收集所有子 Agent 结果
    → 调用 generate_insight

Reference:
    https://docs.langchain.com/oss/python/deepagents/customization
"""
from langchain_openai import ChatOpenAI
from app.config import settings
from app.agent.prompts import (
    MEETING_SUBAGENT_PROMPT,
    CONTACT_SUBAGENT_PROMPT,
    REMINDER_SUBAGENT_PROMPT,
)
from app.agent.tools import MEETING_TOOLS, CONTACT_TOOLS, REMINDER_TOOLS

# =============================================================================
# LLM_MODEL — 子 Agent 共用，纯文本推理（不需要 vision）
# 懒加载: 首次创建子 Agent 时才创建实例
# =============================================================================

_text_llm = None


def _get_text_llm():
    global _text_llm
    if _text_llm is None:
        _text_llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key or settings.vision_api_key or None,
            base_url=settings.llm_base_url or settings.vision_base_url or None,
            temperature=0.3,
        )
    return _text_llm

# =============================================================================
# Meeting Subagent — 从结构化对话中识别会议安排
# =============================================================================

meeting_subagent = {
    "name": "meeting-agent",
    "description": (
        "专门从结构化对话 JSON 中识别会议安排。"
        "当需要判断对话中是否包含会议创建需求时使用此 Agent。"
        "它会提取会议标题、参与人、时间和备注信息。"
    ),
    "system_prompt": MEETING_SUBAGENT_PROMPT,
    "tools": MEETING_TOOLS,
    # model 由 get_all_subagents() 统一注入
}

# =============================================================================
# Contact Subagent — 从结构化对话中识别联系人信息
# =============================================================================

contact_subagent = {
    "name": "contact-agent",
    "description": (
        "专门从结构化对话 JSON 中识别联系人创建和更新需求。"
        "当需要判断对话中是否包含新联系人或联系人信息变更时使用此 Agent。"
        "它会先查询已有联系人避免重复，然后创建或更新联系人。"
    ),
    "system_prompt": CONTACT_SUBAGENT_PROMPT,
    "tools": CONTACT_TOOLS,
    # model 由 get_all_subagents() 统一注入
}

# =============================================================================
# Reminder Subagent — 从结构化对话中识别提醒事项
# =============================================================================

reminder_subagent = {
    "name": "reminder-agent",
    "description": (
        "专门从结构化对话 JSON 中识别待办和提醒事项。"
        "当需要判断对话中是否包含需要设置提醒的内容时使用此 Agent。"
        "它会提取提醒内容和可选的截止时间。"
    ),
    "system_prompt": REMINDER_SUBAGENT_PROMPT,
    "tools": REMINDER_TOOLS,
    # model 由 get_all_subagents() 统一注入
}

# =============================================================================
# ALL_SUBAGENTS — 传入 create_deep_agent() 的完整子 Agent 列表
# =============================================================================

def get_all_subagents() -> list[dict]:
    """创建子 Agent 列表（懒加载 text LLM）。

    不在模块 import 时创建 LLM 实例，避免在没有 API key
    或网络代理配置时 import 失败。
    """
    llm = _get_text_llm()
    return [
        {**meeting_subagent, "model": llm},
        {**contact_subagent, "model": llm},
        {**reminder_subagent, "model": llm},
    ]
