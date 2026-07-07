"""
Insight service — generates cross-referenced insights post-confirmation.

Analyzes confirmed actions against the contact store to surface
useful patterns (e.g., "You have 3 pending meetings with Zhang San").
"""
from app.services.contact import contact_service
from app.services.calendar import calendar_service


class InsightService:
    """Generate cross-referenced insights after user confirms actions."""

    async def generate(self, confirmed_actions: list[dict]) -> list[str]:
        """
        Generate insights by cross-referencing confirmed actions
        with contact and calendar data.

        Args:
            confirmed_actions: List of confirmed action dicts with type and details.

        Returns:
            List of insight strings in Chinese.
        """
        insights = []

        # Count actions per contact
        contact_action_counts: dict[str, int] = {}
        for action in confirmed_actions:
            name = action.get("name", "")
            if name:
                contact_action_counts[name] = contact_action_counts.get(name, 0) + 1

        # Insight: frequent contact
        for name, count in contact_action_counts.items():
            if count >= 3:
                insights.append(f"「{name}」已有{count}个待处理的动作，建议统一跟进。")

        # Insight: potential duplicates
        contacts = await contact_service.list_all()
        for action in confirmed_actions:
            if action.get("type") == "create_contact":
                action_name = action.get("name", "")
                for existing in contacts:
                    if existing["name"] == action_name:
                        insights.append(
                            f"联系人「{action_name}」已存在（{existing.get('phone', '无电话')}），"
                            f"建议使用 update_contact 而非重复创建。"
                        )

        # Insight: meeting conflicts (mock)
        if any(a.get("type") == "create_meeting" for a in confirmed_actions):
            events = await calendar_service.list_events()
            if len(events) >= 2:
                insights.append(f"您近期已有{len(events)}个会议，请注意时间安排。")

        return insights if insights else ["暂无特别建议。"]


insight_service = InsightService()
