"""
Tool 注册表 —— 按 Agent 角色分组的工具集合。

============================== 分组逻辑 ==============================

STRUCTURE_TOOLS  → Coordinator Agent
  职责: 调用 VISION_MODEL 解析聊天截图 → 输出结构化对话 JSON
  包含: structure_conversation
  注意: 这是管道的第一步，在所有子 Agent 之前执行

MEETING_TOOLS    → Meeting Subagent
  职责: 从结构化对话中识别会议安排
  包含: create_meeting, query_contacts

CONTACT_TOOLS    → Contact Subagent
  职责: 从结构化对话中识别联系人创建/更新需求
  包含: create_contact, update_contact, query_contacts

REMINDER_TOOLS   → Reminder Subagent
  职责: 从结构化对话中识别待办提醒
  包含: create_reminder

INSIGHT_TOOLS    → Coordinator Agent
  职责: 在所有子 Agent 完成后生成跨域洞察
  包含: generate_insight

ALL_TOOLS        → 平铺列表，供单 Agent 模式备选
"""
from app.agent.tools.structure import structure_conversation
from app.agent.tools.meeting import create_meeting
from app.agent.tools.contact import create_contact, update_contact, query_contacts
from app.agent.tools.reminder import create_reminder
from app.agent.tools.insight import generate_insight

# -- Coordinator Agent tools ---------------------------------------------------

STRUCTURE_TOOLS = [structure_conversation]
"""Coordinator 专用: structure_conversation 必须在委派子 Agent 之前调用"""

INSIGHT_TOOLS = [generate_insight]
"""Coordinator 专用: 子 Agent 完成后调用 generate_insight 生成综合建议"""

# -- Subagent tools（纯文本模型处理结构化对话）---------------------------------

MEETING_TOOLS = [create_meeting, query_contacts]
"""Meeting Subagent: 从结构化对话中提取会议信息"""

CONTACT_TOOLS = [create_contact, update_contact, query_contacts]
"""Contact Subagent: 从结构化对话中提取联系人信息"""

REMINDER_TOOLS = [create_reminder]
"""Reminder Subagent: 从结构化对话中提取提醒事项"""

# -- Flat list for single-agent fallback ---------------------------------------

ALL_TOOLS = [
    structure_conversation,
    create_meeting,
    create_contact,
    update_contact,
    create_reminder,
    query_contacts,
    generate_insight,
]
