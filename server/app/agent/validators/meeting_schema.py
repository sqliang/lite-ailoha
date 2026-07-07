"""
create_meeting 工具输出 Schema。
"""
from pydantic import BaseModel, Field


class MeetingSchema(BaseModel):
    """会议安排。"""
    title: str = Field(description="会议标题")
    participants: list = Field(default_factory=list, description="参与人列表")
    datetime: str = Field(default="待定", description="会议时间描述")
    notes: str = Field(default="", description="会议备注")
    status: str = Field(default="proposed", description="状态")
