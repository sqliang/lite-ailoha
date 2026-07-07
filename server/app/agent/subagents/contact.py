"""
contact-agent — 从结构化对话中识别联系人创建/更新需求。

============================== 职责 ==============================

接收 Coordinator 提供的结构化对话 JSON，识别联系人创建和更新需求，
先查询已有联系人避免重复，然后调用 create_contact 或 update_contact 工具。

============================== 工具 ==============================

- create_contact: 创建新联系人提议
- update_contact: 更新已有联系人信息
- query_contacts: 查询已有联系人（去重）
"""
from app.agent.prompts import CONTACT_SUBAGENT_PROMPT
from app.agent.tools import CONTACT_TOOLS

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
