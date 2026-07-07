"""
Reminder tools — create_reminder.

Used by the Reminder subagent to propose task/reminder actions.
"""
import json
from langchain_core.tools import tool


@tool
def create_reminder(content: str, due_date: str = "", title: str = "") -> str:
    """创建提醒/待办事项提案。

    当聊天中出现以下内容时调用此工具：
    - 需要后续跟进的事项（"记得会前准备演示文稿"）
    - 有截止时间的任务（"下周一之前交报告"）
    - @提及的待办（"@张三 帮我确认一下时间"）

    注意：此工具用于创建「独立提醒」，与会议关联的提醒
    （如"会前30分钟提醒"）也属于此类。

    Args:
        content: 提醒内容，描述需要做什么
        due_date: 截止时间描述（可选），如"下周一"或 ISO 格式
        title: 提醒标题（可选），默认使用 content 作为标题

    Returns:
        JSON 格式的提醒提案，含 status=proposed 表示待用户确认
    """
    return json.dumps({
        "action": "create_reminder",
        "title": title or content,
        "content": content,
        "due_date": due_date,
        "status": "proposed",
    }, ensure_ascii=False)
