"""
子 Agent 定义 — 一个领域一个文件。

============================== 架构 ==============================

  Coordinator (LLM_MODEL / DeepSeek) — 大脑，规划 + 分发
      │
      ├── task("meeting-agent",  structured_json)  → LLM_MODEL
      ├── task("contact-agent",  structured_json)  → LLM_MODEL
      └── task("reminder-agent", structured_json)  → LLM_MODEL

============================== 目录结构 ==============================

subagents/
├── __init__.py     — 统一导出 get_all_subagents()
├── meeting.py      — meeting-agent 定义（会议提取）
├── contact.py      — contact-agent 定义（联系人创建/更新）
└── reminder.py     — reminder-agent 定义（提醒提取）

============================== 使用方式 ==============================

    from app.agent.subagents import get_all_subagents
    subagents = get_all_subagents()
"""
from app.agent.subagents.meeting import meeting_subagent
from app.agent.subagents.contact import contact_subagent
from app.agent.subagents.reminder import reminder_subagent
from app.agent.llm_factory import get_text_llm


def get_all_subagents() -> list[dict]:
    """获取所有子 Agent 定义，统一注入 LLM_MODEL 实例。

    不在模块 import 时创建 LLM 实例，避免没有 API key
    或网络代理配置时 import 失败。
    """
    llm = get_text_llm()
    return [
        {**meeting_subagent, "model": llm},
        {**contact_subagent, "model": llm},
        {**reminder_subagent, "model": llm},
    ]


__all__ = ["get_all_subagents"]
