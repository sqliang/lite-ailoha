"""
Insight tools — generate_insight.

Used by the Coordinator agent after all subagents have completed,
to generate cross-referenced insights.
"""
import json
from langchain_core.tools import tool


@tool
def generate_insight(context: str, confirmed_actions: str = "[]") -> str:
    """生成跨域洞察建议。

    在所有子 Agent（会议、联系人、提醒）完成分析后，
    由协调 Agent 调用此工具，基于全局上下文和已识别的动作
    生成一条简短的实用建议。

    典型洞察场景：
    - 发现同一联系人有多个待定会议 → 建议时间统筹
    - 新联系人与已有联系人相似 → 提醒避免重复创建
    - 会议时间与已有日程冲突 → 建议调整时间

    Args:
        context: 当前分析的聊天上下文摘要
        confirmed_actions: 已确认的动作 JSON 数组

    Returns:
        JSON 格式的洞察结果
    """
    actions = json.loads(confirmed_actions) if confirmed_actions else []
    return json.dumps({
        "action": "generate_insight",
        "context": context,
        "actions_count": len(actions),
        "status": "done",
    }, ensure_ascii=False)
