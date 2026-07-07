"""
Pydantic 请求模型。

数据流:
  iOS 客户端 → POST /api/v1/analyze (JSON body)
  → AnalyzeRequest 校验 → api/analyze.py 处理 → Agent → SSE 流
"""
from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """分析请求 —— iOS 客户端发送聊天截图 + 可选补充文字。

    字段说明:
    - image: 聊天截图的 base64 编码字符串（必填）
             JPEG/PNG 格式，iOS 端已压缩至 max 1024px
    - user_context: 用户手动输入的补充说明（可选）
                    用于提供截图之外的额外上下文
    """
    image: str = Field(
        default="",
        description="聊天截图的 base64 编码（JPEG/PNG），iOS 端已压缩至 max 1024px"
    )
    user_context: str = Field(
        default="",
        description="用户手动输入的补充说明文字"
    )


class ActionRequest(BaseModel):
    """确认/取消动作请求。

    字段说明:
    - session_id: 关联的分析会话 ID
                  用于将用户的操作（确认/取消）关联到具体的分析会话
    """
    session_id: str = Field(default="", description="分析会话 ID，用于关联操作到具体会话")
