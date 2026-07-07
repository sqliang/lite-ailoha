"""
create_contact / update_contact 工具输出 Schema。
"""
from pydantic import BaseModel, Field


class ContactCreateSchema(BaseModel):
    """创建联系人。"""
    name: str = Field(description="姓名", min_length=1)
    phone: str = Field(default="", description="电话")
    email: str = Field(default="", description="邮箱")
    company: str = Field(default="", description="公司")
    title: str = Field(default="", description="职位")
    notes: str = Field(default="", description="备注")
    status: str = Field(default="proposed", description="状态")


class ContactUpdateSchema(BaseModel):
    """更新联系人。"""
    name: str = Field(description="姓名", min_length=1)
    field: str = Field(description="变更字段")
    value: str = Field(description="新值")
    status: str = Field(default="proposed", description="状态")
