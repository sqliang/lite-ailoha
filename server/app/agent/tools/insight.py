"""
Insight tools — generate_insight。

通过共享变量传递完整上下文（不被 LLM 截断），
工具内部调 LLM 生成结构化 JSON，解析验证后返回。
"""
import json
import logging
from langchain_core.tools import tool
from app.agent.llm_factory import get_text_llm

logger = logging.getLogger(__name__)

# 共享变量：set_insight_context() 写入，generate_insight() 读取
_insight_context: dict = {}


def set_insight_context(
    card_id: str = "",
    card_type: str = "",
    card_summary: str = "",
    structured: str = "",
    confirmed: list | None = None,
    cancelled: list | None = None,
    server_contacts: list | None = None,
    server_calendar: list | None = None,
    device_contacts: list | None = None,
    device_events: list | None = None,
    device_reminders: list | None = None,
):
    """在 Agent 运行前设置当前洞察请求的完整上下文。"""
    global _insight_context
    _insight_context = {
        "card_id": card_id,
        "card_type": card_type,
        "card_summary": card_summary,
        "structured": structured,
        "confirmed": confirmed or [],
        "cancelled": cancelled or [],
        "server_contacts": server_contacts or [],
        "server_calendar": server_calendar or [],
        "device_contacts": device_contacts or [],
        "device_events": device_events or [],
        "device_reminders": device_reminders or [],
    }
    logger.info("[insight] set_context card_id=%s contacts(s=%d,d=%d) calendar(s=%d,d=%d) reminders=%d",
                card_id, len(server_contacts or []), len(device_contacts or []),
                len(server_calendar or []), len(device_events or []), len(device_reminders or []))


# ── Prompt ───────────────────────────────────────────────────────

def _build_insight_llm_prompt(ctx: dict) -> str:
    parts = ["你是一个智能助理。用户确认了一张操作卡片，请只针对这张卡片分析可行性。\n"]
    parts.append(f"## 当前卡片（只分析这张）\n类型: {ctx.get('card_type')}\n摘要: {ctx.get('card_summary')}\n")

    if ctx.get("structured"):
        parts.append(f"## 原始对话上下文\n```json\n{ctx['structured']}\n```\n")

    confirmed = ctx.get("confirmed", [])
    if confirmed:
        parts.append("## 用户已确认的操作\n")
        for c in confirmed:
            parts.append(f"- [{c.get('type','')}] {c.get('summary','')}\n")

    cancelled = ctx.get("cancelled", [])
    if cancelled:
        parts.append("## 用户已取消的操作\n")
        for c in cancelled:
            parts.append(f"- [{c.get('type','')}] {c.get('summary','')}\n")

    sc = ctx.get("server_contacts", [])
    if sc:
        parts.append(f"\n## 已有联系人 - 服务端（共 {len(sc)} 人）\n")
        for ct in sc[:20]:
            parts.append(f"- {ct.get('name','?')} | {ct.get('title','')} | {ct.get('company','')} | 电话:{ct.get('phone','')} | 会面:{ct.get('meeting_count',0)}次\n")

    dc = ctx.get("device_contacts", [])
    if dc:
        parts.append(f"\n## 已有联系人 - iOS 设备（共 {len(dc)} 人）\n")
        for ct in dc[:20]:
            parts.append(f"- {ct.get('name','?')} | {ct.get('title','')} | {ct.get('company','')} | 电话:{ct.get('phones',[])} | 邮箱:{ct.get('emails',[])}\n")

    scal = ctx.get("server_calendar", [])
    if scal:
        parts.append("\n## 已有日历 - 服务端\n")
        for ev in scal:
            parts.append(f"- {ev.get('datetime','')} | {ev.get('title','')} | 参与人:{ev.get('participants',[])}\n")

    dcal = ctx.get("device_events", [])
    if dcal:
        parts.append(f"\n## 已有日历 - iOS 设备（共 {len(dcal)} 条）\n")
        for ev in dcal:
            parts.append(f"- {ev.get('start','')}~{ev.get('end','')} | {ev.get('title','')} | 地点:{ev.get('location','')}\n")

    dr = ctx.get("device_reminders", [])
    if dr:
        parts.append(f"\n## iOS 设备提醒（共 {len(dr)} 条）\n")
        for r in dr:
            parts.append(f"- {r.get('title','')} | 截止:{r.get('dueDate','')} | 优先级:{r.get('priority',0)}\n")

    parts.append("""
## 输出要求
返回严格 JSON（只输出 JSON，不要任何额外文字）:
{"card_id":"卡片ID","verdict":"approved|conflict|unnecessary","title":"一句话判断","analysis":"2-3句洞察分析（解释你看到了什么、发现了什么）","recommendation":"1-2句操作建议（告诉用户接下来该做什么）","actions":[{"label":"按钮文案","type":"execute|dismiss"}]}

verdict 标准: approved=无冲突可执行; conflict=有冲突需调整; unnecessary=无需操作
actions type: execute=执行操作, dismiss=关闭
""")
    return "".join(parts)


# ── 验证 ─────────────────────────────────────────────────────────

REQUIRED_KEYS = ["card_id", "verdict", "title", "analysis", "recommendation", "actions"]
VALID_VERDICTS = {"approved", "approved_with_note", "conflict", "unnecessary"}


def _validate_insight_output(result: dict):
    for key in REQUIRED_KEYS:
        if key not in result:
            raise ValueError(f"缺少必填字段: {key}")
    if result["verdict"] not in VALID_VERDICTS:
        raise ValueError(f"无效 verdict: {result['verdict']}")
    if not isinstance(result["actions"], list):
        raise ValueError("actions 必须是数组")
    for action in result["actions"]:
        if "label" not in action or "type" not in action:
            raise ValueError(f"action 缺少必填字段: {action}")


# ── Tool 函数 ─────────────────────────────────────────────────────

@tool
def generate_insight(user_instruction: str = "") -> str:
    """分析用户确认的操作卡片，生成结构化洞察。

    从共享变量读取完整上下文（不被 LLM 截断），
    内部调用 LLM 生成 JSON，解析验证后返回。
    """
    ctx = _insight_context
    if not ctx:
        return json.dumps({
            "card_id": "", "verdict": "approved_with_note",
            "title": "无可用的上下文数据", "analysis": "无", "recommendation": "无法生成洞察",
            "actions": [{"label": "关闭", "type": "dismiss"}],
        }, ensure_ascii=False)

    prompt = _build_insight_llm_prompt(ctx)
    logger.info("[insight] 调用LLM card_id=%s prompt_len=%d contacts(s=%d,d=%d) events=%d reminders=%d",
                ctx.get("card_id"), len(prompt),
                len(ctx.get("server_contacts", [])), len(ctx.get("device_contacts", [])),
                len(ctx.get("device_events", [])), len(ctx.get("device_reminders", [])))

    llm = get_text_llm()
    response = llm.invoke(prompt)
    raw = response.content.strip()
    logger.info("[insight] LLM返回 raw_len=%d preview=%.200s", len(raw), raw)

    # 尝试提取 JSON（LLM 可能在 JSON 前后加了说明文字）
    try:
        # 尝试直接解析
        logger.info("[insight] 尝试直接解析JSON...")
        result = json.loads(raw)
        _validate_insight_output(result)
        logger.info("[insight] validate=OK verdict=%s", result.get("verdict"))
        return json.dumps(result, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError) as e:
        # 尝试从文本中提取 JSON 块
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                _validate_insight_output(result)
                logger.info("[insight] validate=OK (extracted) verdict=%s", result.get("verdict"))
                return json.dumps(result, ensure_ascii=False)
            except Exception:
                pass

        logger.warning("[insight] 解析失败: %s raw=%s", e, raw[:300])
        logger.warning("[insight] 解析失败使用 fallback")
        return json.dumps({
            "card_id": ctx.get("card_id", ""),
            "verdict": "approved_with_note",
            "title": "洞察生成完成",
            "analysis": "无法解析 Agent 输出",
            "recommendation": raw[:300] if raw else "无法生成洞察",
            "actions": [{"label": "关闭", "type": "dismiss"}],
        }, ensure_ascii=False)
