"""
Contact service — MVP mock implementation.

In production, this would CRUD against a real database or integrate
with the iOS Contacts framework via CardDAV or a sync protocol.
"""


class ContactService:
    """Mock contact CRUD for MVP. Uses in-memory storage."""

    def __init__(self):
        self._contacts: list[dict] = [
            {"name": "张三", "phone": "13800001111", "email": "zhangsan@example.com", "company": "ABC科技"},
            {"name": "李四", "phone": "13900002222", "email": "lisi@example.com", "company": "XYZ集团"},
        ]

    async def create(self, name: str, phone: str = "", email: str = "",
                     company: str = "", title: str = "", notes: str = "") -> dict:
        """Create a new contact."""
        contact = {
            "name": name,
            "phone": phone,
            "email": email,
            "company": company,
            "title": title,
            "notes": notes,
        }
        self._contacts.append(contact)
        return {"success": True, "message": f"Mock: 联系人「{name}」已创建", "contact": contact}

    async def update(self, name: str, field: str, value: str) -> dict:
        """Update an existing contact's field."""
        for c in self._contacts:
            if c["name"] == name:
                c[field] = value
                return {"success": True, "message": f"Mock: 「{name}」的{field}已更新为「{value}」"}
        return {"success": False, "message": f"未找到联系人「{name}」"}

    async def query(self, name: str = "") -> list[dict]:
        """Query contacts by name (partial match)."""
        if not name:
            return self._contacts
        return [c for c in self._contacts if name in c.get("name", "")]

    async def list_all(self) -> list[dict]:
        """Return all contacts."""
        return self._contacts


contact_service = ContactService()
