"""
structure_conversation 输出 Schema。
"""
from pydantic import BaseModel, Field


class StructMessageSchema(BaseModel):
    """单条聊天消息。"""
    time: str = Field(description="ISO 8601 时间戳")
    speaker: str = Field(description="消息发送者")
    content: str = Field(description="消息内容")


class StructConversationSchema(BaseModel):
    """结构化对话。"""
    participants: list[str] = Field(default_factory=list, description="参与人姓名列表")
    messages: list[StructMessageSchema] = Field(default_factory=list, description="消息列表")
