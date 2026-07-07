"""
meeting-agent — 从结构化对话中识别会议安排。

============================== 职责 ==============================

接收 Coordinator 提供的结构化对话 JSON，识别会议安排需求，
调用 create_meeting 工具生成会议建议卡片。

============================== 工具 ==============================

- create_meeting: 创建会议提议
- query_contacts: 查询已有联系人（避免重复）
"""
from app.agent.prompts import MEETING_SUBAGENT_PROMPT
from app.agent.tools import MEETING_TOOLS

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
