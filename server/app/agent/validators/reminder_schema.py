"""
create_reminder 工具输出 Schema。
"""
from pydantic import BaseModel, Field


class ReminderSchema(BaseModel):
    """提醒事项。"""
    content: str = Field(description="提醒内容", min_length=1)
    due_date: str = Field(default="", description="截止时间")
    title: str = Field(default="", description="提醒标题")
    status: str = Field(default="proposed", description="状态")
