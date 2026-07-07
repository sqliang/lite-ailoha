"""
Contact tools — create_contact, update_contact, query_contacts.

Used by the Contact subagent to manage contact-related actions.
"""
import json
from langchain_core.tools import tool


@tool
def create_contact(
    name: str,
    phone: str = "",
    email: str = "",
    company: str = "",
    title: str = "",
    notes: str = "",
) -> str:
    """创建新联系人提案。

    当聊天中出现以下信息时调用此工具：
    - 新的人名及联系方式（"这是张三，产品经理，电话138xxxx"）
    - 分享的名片信息（"张三，ABC科技，zhangsan@example.com"）

    Args:
        name: 联系人姓名（必填）
        phone: 电话号码
        email: 邮箱地址
        company: 公司/组织名称
        title: 职位/头衔
        notes: 备注信息

    Returns:
        JSON 格式的联系人创建提案，含 status=proposed 表示待用户确认
    """
    return json.dumps({
        "action": "create_contact",
        "name": name,
        "phone": phone,
        "email": email,
        "company": company,
        "title": title,
        "notes": notes,
        "status": "proposed",
    }, ensure_ascii=False)


@tool
def update_contact(name: str, field: str, value: str) -> str:
    """更新已有联系人信息。

    当聊天中提到联系人信息变更时调用此工具：
    - "张三换部门了，现在在产品部"
    - "李四的新号码是139xxxx"

    调用前应先使用 query_contacts 确认联系人已存在。

    Args:
        name: 要更新的联系人姓名
        field: 变更的字段名（phone/email/company/title/notes）
        value: 新的字段值

    Returns:
        JSON 格式的联系人更新提案
    """
    return json.dumps({
        "action": "update_contact",
        "name": name,
        "field": field,
        "value": value,
        "status": "proposed",
    }, ensure_ascii=False)


@tool
def query_contacts(name: str = "") -> str:
    """查询已有联系人，避免重复创建。

    在创建新联系人前必须调用此工具检查是否已存在。
    支持按姓名模糊匹配。

    Args:
        name: 联系人姓名（支持部分匹配），留空返回全部联系人

    Returns:
        JSON 数组格式的匹配联系人列表
    """
    # MVP: mock 数据，后续接入真实数据库
    mock_contacts = [
        {"name": "张三", "phone": "13800001111", "email": "zhangsan@example.com", "company": "ABC科技", "title": "工程师"},
        {"name": "李四", "phone": "13900002222", "email": "lisi@example.com", "company": "XYZ集团", "title": "产品经理"},
        {"name": "王五", "phone": "13700003333", "email": "wangwu@example.com", "company": "DEF公司", "title": "设计师"},
    ]
    if name:
        filtered = [c for c in mock_contacts if name in c["name"]]
    else:
        filtered = mock_contacts
    return json.dumps(filtered, ensure_ascii=False)
