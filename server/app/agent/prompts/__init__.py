"""
System Prompts — 多模型 Agent 架构的指令体系。

============================== Prompt 分层 ==============================

COORDINATOR_PROMPT           — 协调者: VISION_MODEL 看图 → 结构化 → 委派子 Agent
MEETING_SUBAGENT_PROMPT      — 会议子 Agent: LLM_MODEL 纯文本提取会议
CONTACT_SUBAGENT_PROMPT      — 联系人子 Agent: LLM_MODEL 纯文本提取联系人
REMINDER_SUBAGENT_PROMPT     — 提醒子 Agent: LLM_MODEL 纯文本提取提醒

============================== 目录结构 ==============================

prompts/
├── __init__.py       — 统一导出，保持向后兼容
├── coordinator.py    — COORDINATOR_PROMPT
├── meeting.py        — MEETING_SUBAGENT_PROMPT
├── contact.py        — CONTACT_SUBAGENT_PROMPT
└── reminder.py       — REMINDER_SUBAGENT_PROMPT

============================== 工作流 ==============================

Coordinator (vision model):
  1. 看到聊天截图 → 理解对话结构
  2. 调用 structure_conversation tool → 输出结构化 JSON
  3. 基于结构化 JSON → task() 委派三个子 Agent
  4. 收集子 Agent 结果 → generate_insight

子 Agent (text model):
  接收结构化 JSON 文本 → 领域提取 → 调用对应 tool
"""
from app.agent.prompts.coordinator import COORDINATOR_PROMPT
from app.agent.prompts.meeting import MEETING_SUBAGENT_PROMPT
from app.agent.prompts.contact import CONTACT_SUBAGENT_PROMPT
from app.agent.prompts.reminder import REMINDER_SUBAGENT_PROMPT

__all__ = [
    "COORDINATOR_PROMPT",
    "MEETING_SUBAGENT_PROMPT",
    "CONTACT_SUBAGENT_PROMPT",
    "REMINDER_SUBAGENT_PROMPT",
]
