"""
reminder-agent — 从结构化对话中识别待办和提醒事项。

============================== 职责 ==============================

接收 Coordinator 提供的结构化对话 JSON，识别待办和提醒事项，
调用 create_reminder 工具生成提醒建议卡片。

============================== 工具 ==============================

- create_reminder: 创建提醒提议

============================== 与 create_meeting 的区别 ==============================

- create_meeting: 多人参与的会议安排
- create_reminder: 个人待办/提醒事项
"""
from app.agent.prompts import REMINDER_SUBAGENT_PROMPT
from app.agent.tools import REMINDER_TOOLS

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
