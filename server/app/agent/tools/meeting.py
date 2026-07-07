"""
Meeting tools — create_meeting.

Used by the Meeting subagent to propose meeting creation actions.
"""
import json
from langchain_core.tools import tool


@tool
def create_meeting(
    title: str,
    participants: str = "",
    datetime: str = "待定",
    notes: str = "",
) -> str:
    """从聊天上下文中提取会议信息并创建会议提案。

    当聊天中明确提到以下内容时调用此工具：
    - 会议时间（"周四下午3点"、"下周一"）
    - 会议主题（"评审会"、"周会"）
    - 参与人（"叫上张三一起"）

    Args:
        title: 会议标题，如"产品评审"
        participants: 参与人，逗号分隔，如"张三,李四"
        datetime: 会议时间描述，如"周四 15:00"或 ISO 格式
        notes: 会议议程或备注信息

    Returns:
        JSON 格式的会议提案，含 status=proposed 表示待用户确认
    """
    participant_list = (
        [p.strip() for p in participants.split(",") if p.strip()]
        if participants else []
    )
    return json.dumps({
        "action": "create_meeting",
        "title": title,
        "participants": participant_list,
        "datetime": datetime,
        "notes": notes,
        "status": "proposed",
    }, ensure_ascii=False)
