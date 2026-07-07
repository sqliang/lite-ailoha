"""
structure_conversation 工具 —— 用 VISION_MODEL 解析聊天截图。

============================== 核心职责 ==============================

这是整个 Agent 管道的第一步，也是质量评估的基石:
  1. 接收聊天截图的 base64 编码
  2. 调用 VISION_MODEL（多模态 LLM）看图理解
  3. 输出结构化的对话 JSON: {participants, messages[{time, speaker, content}]}

============================== 数据契约 ==============================

输入:
  - screenshot_base64: 聊天截图的 base64 编码字符串（JPEG/PNG）
  - user_context: 用户可选的补充说明文字

输出 (JSON 字符串):
  {
    "participants": ["sqliang", "张洪银"],           // 对话参与者姓名列表
    "messages": [
      {
        "time": "2026-07-06T15:56:00",              // ISO 8601 时间戳
        "speaker": "sqliang",                        // 消息发送者
        "content": "老伙计，周五把相关资料..."         // 消息文本内容
      }
    ]
  }

============================== 数据流路径 ==============================

  该 tool 的输出会经过三条路径:
  1. SSE 流 → iOS 客户端 (event:struct)  — 实时展示结构化对话
  2. SQLite analyze_sessions 表            — 持久化，事后质量评估
  3. DeepAgent Coordinator                — 作为后续委派子 Agent 的输入

============================== 为什么是独立 tool？ ==============================

  将结构化提取作为一个显式的 tool（而非 Coordinator 的内部推理），原因:
  - 可观测: 结构化对话是 SSE 流的显式事件，debug 时可直接查看模型"看懂了什么"
  - 可评估: 存储在 sessions 表中，事后可对照原始截图评估 VISION_MODEL 的准确率
  - 可解耦: 结构化和后续的动作识别是两个独立步骤，各自由不同的模型处理
"""
import logging
from langchain_core.tools import tool
from app.agent.llm_factory import get_vision_llm

logger = logging.getLogger(__name__)


# =============================================================================
# 共享状态 — structure_conversation 不从 LLM 参数获取 base64
# （LLM 无法准确复制大量 base64 数据，会截断导致 1×1 像素错误）
# =============================================================================

_shared_image_b64: str = ""
_shared_user_context: str = ""


def set_shared_image(image_base64: str, user_context: str = ""):
    """在 Agent 运行前设置当前请求的图片数据。"""
    global _shared_image_b64, _shared_user_context
    _shared_image_b64 = image_base64
    _shared_user_context = user_context


# =============================================================================
# structure_conversation tool
# =============================================================================

@tool
def structure_conversation(user_context: str = "") -> str:
    """用多模态模型解析微信聊天截图，输出结构化对话 JSON。

    ============================== 调用时机 ==============================
    Coordinator 在收到用户请求后，第一个调用的 tool。在所有子 Agent
    （meeting/contact/reminder）之前执行。

    ============================== 输入参数 ==============================
    Args:
        user_context: 用户的可选补充说明，如"这是我和张三的聊天记录"

    ============================== 返回值 ==============================
    Returns:
        JSON 字符串，格式:
        {
            "participants": ["姓名1", "姓名2"],
            "messages": [
                {"time": "2026-07-06T15:56:00", "speaker": "姓名", "content": "消息内容"}
            ]
        }

    ============================== 结构化规则 ==============================
    模型被要求遵循以下规则:
    - 识别对话参与者（从聊天界面中的昵称/备注提取）
    - 按时间顺序排列消息（从早到晚）
    - 忽略 UI 界面文字（搜索框、标签栏、系统提示等）
    - 正确处理跨天对话
    - 语音消息标注为 "[语音消息]" 或 "[语音消息: 已取消]"
    - 截图引用标注为 "[截图: 简要描述]"
    - 消息内容保留原始文字，不做摘要或改写

    ============================== 图片来源 ==============================
    图片数据不从 LLM 参数获取（LLM 无法复制 base64），
    而是从 set_shared_image() 预先设置的共享变量中读取。
    """
    # 从共享变量读取图片（不是从 LLM 参数）
    screenshot_base64 = _shared_image_b64
    ctx = _shared_user_context
    if user_context and user_context != ctx:
        ctx = f"{ctx}; {user_context}"

    # 构建多模态消息: 文字提示 + 图片
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": _STRUCTURER_PROMPT + (
                        f"\n\n用户补充说明: {ctx}" if ctx else ""
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{screenshot_base64}",
                        # 不传 detail 参数，部分 API（如 Ark）不支持
                    },
                },
            ],
        }
    ]

    import json as _json
    from app.agent.validators import validate_json_output, StructConversationSchema

    def _retry(last_output: str, error: str) -> str:
        """重试: 用错误反馈追加到 messages，再次调用 VisionLLM。"""
        retry_msgs = messages + [
            {"role": "assistant", "content": str(last_output)[:2000]},
            {"role": "user", "content": f"输出格式错误: {error}\n请严格按 JSON 格式重新输出，不要包含额外文字。"},
        ]
        return get_vision_llm().invoke(retry_msgs).content

    raw_output = get_vision_llm().invoke(messages).content
    result = validate_json_output(
        output=raw_output,
        schema=StructConversationSchema,
        tool_name="structure_conversation",
        retry_fn=_retry,
    )
    logger.info("[structure.py] VisionLLM invoke完成 | valid=%s, len=%d",
                "error" not in result, len(_json.dumps(result, ensure_ascii=False)))
    return _json.dumps(result, ensure_ascii=False)


# =============================================================================
# Structurer Prompt — 指导 VISION_MODEL 如何结构化聊天截图
# =============================================================================

_STRUCTURER_PROMPT = """你是一个专业的聊天记录解析助手。请仔细查看这张微信聊天截图，提取其中的对话内容，按以下 JSON 格式输出：

{
  "participants": ["参与者1的昵称", "参与者2的昵称"],
  "messages": [
    {
      "time": "2026-07-06T15:56:00",
      "speaker": "消息发送者",
      "content": "消息内容"
    }
  ]
}

要求：
1. 从聊天界面中识别所有对话参与者（使用昵称或备注名）
2. 按时间顺序排列消息，从最早到最晚
3. 每一条消息都要准确归属到发言人
4. 保留消息的原始文字内容，不要改写或摘要
5. 时间戳使用 ISO 8601 格式（YYYY-MM-DDTHH:mm:ss）
6. 忽略界面 UI 元素（搜索框、标签栏、底部输入框、系统提示等）
7. 语音消息标注为 "[语音消息]"，被取消的标注为 "[语音消息: 已取消]"
8. 图片/文件消息标注为 "[图片]" 或 "[文件]"
9. 如果截图中有日期分隔线（如"2026年7月6日"），请注意消息所属的日期
10. 只输出 JSON，不要有任何额外的解释文字
"""
