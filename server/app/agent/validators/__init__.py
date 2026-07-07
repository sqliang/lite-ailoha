"""
JSON 输出校验 + 重试机制。

============================== 设计 ==============================

LLM 返回的结构化 JSON 可能不合法（缺字段、格式错误、非 JSON 文本）。
本模块提供可复用的校验+重试通用函数，各工具只需传入自己的 Schema。

============================== 使用方式 ==============================

    from app.agent.validators import validate_json_output
    result = validate_json_output(
        output=response.content,
        schema=StructConversationSchema,
        tool_name="structure_conversation",
        retry_fn=lambda last, err: some_llm.invoke(...).content,
    )

============================== 重试策略 ==============================

- 最多 2 次重试
- 每次重试前会将错误信息反馈给 LLM
- 最终仍失败 → 返回 {"raw": ..., "error": ...}，不阻塞管道
"""
import json
import logging
from typing import Callable

from pydantic import BaseModel, ValidationError

from app.agent.validators.struct_schema import StructConversationSchema, StructMessageSchema
from app.agent.validators.meeting_schema import MeetingSchema
from app.agent.validators.contact_schema import ContactCreateSchema, ContactUpdateSchema
from app.agent.validators.reminder_schema import ReminderSchema

logger = logging.getLogger(__name__)

__all__ = [
    "validate_json_output",
    "build_retry_messages",
    "StructConversationSchema",
    "StructMessageSchema",
    "MeetingSchema",
    "ContactCreateSchema",
    "ContactUpdateSchema",
    "ReminderSchema",
]


def validate_json_output(
    output: str,
    schema: type[BaseModel],
    tool_name: str,
    retry_fn: Callable[[str, str], str] | None = None,
    max_retries: int = 2,
) -> dict:
    """
    校验 LLM 输出的 JSON 是否匹配预期 Schema。失败时自动重试。

    Args:
        output: LLM 原始输出文本
        schema: Pydantic BaseModel 子类，用于校验结构
        tool_name: 工具名（日志用）
        retry_fn: 重试函数，签名为 (last_output: str, error_msg: str) -> str
        max_retries: 最大重试次数（默认 2）

    Returns:
        校验通过 → schema.model_dump() 的 dict
        校验失败 → {"raw": output, "error": "..."}

    流程:
        1. JSON 解析
        2. Pydantic Schema 校验
        3. 失败 → 调用 retry_fn(last_output, error_msg)
        4. 重复直到成功或达到 max_retries
        5. 最终仍失败 → 返回 raw fallback
    """
    last_output = output

    for attempt in range(max_retries + 1):
        # 第一层: JSON 解析
        try:
            parsed = json.loads(last_output) if isinstance(last_output, str) else last_output
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("[%s] JSON解析失败 (attempt %d/%d): %s",
                           tool_name, attempt + 1, max_retries + 1, e)
            if attempt < max_retries and retry_fn:
                last_output = retry_fn(last_output, f"输出不是合法 JSON: {e}")
                continue
            return {"raw": str(output), "error": f"JSON解析失败: {e}"}

        # 第二层: Schema 校验
        try:
            validated = schema(**parsed)
            if attempt > 0:
                logger.info("[%s] 第 %d 次重试后校验通过", tool_name, attempt)
            return validated.model_dump()
        except ValidationError as e:
            logger.warning("[%s] Schema校验失败 (attempt %d/%d): %s",
                           tool_name, attempt + 1, max_retries + 1,
                           str(e.errors())[:200])
            if attempt < max_retries and retry_fn:
                error_detail = _format_validation_errors(e)
                last_output = retry_fn(last_output, error_detail)
                continue
            return {"raw": str(output), "error": f"Schema校验失败: {e}"}

    # 不应该到达这里，但防御性编程
    return {"raw": str(output), "error": "未知校验错误"}


def build_retry_messages(last_output: str, error: str, system_prompt: str) -> list[dict]:
    """
    构建重试用的消息列表。

    结构: system_prompt → 上次输出 → 错误反馈
    LLM 看到这个序列后会理解自己的错误并重新生成。
    """
    return [
        {"role": "user", "content": system_prompt},
        {"role": "assistant", "content": str(last_output)[:2000]},
        {"role": "user", "content": (
            f"你的输出格式有误，具体问题: {error}\n\n"
            "请严格按照 JSON 格式重新输出，不要包含任何额外解释文字。"
        )},
    ]


def _format_validation_errors(e: ValidationError) -> str:
    """将 Pydantic ValidationError 格式化为人类可读的错误信息。"""
    errors = []
    for err in e.errors():
        field = ".".join(str(loc) for loc in err["loc"])
        msg = err["msg"]
        errors.append(f"  字段 '{field}': {msg}")
    return "JSON 结构不符合要求:\n" + "\n".join(errors)
