"""
Calendar service — MVP mock implementation.

In production, this would integrate with Google Calendar API or
Apple Calendar (via CalDAV or EventKit on the iOS side).
"""


class CalendarService:
    """Mock calendar operations for MVP. Returns success confirmations."""

    async def create_event(
        self,
        title: str,
        participants: list[str],
        datetime: str = "",
        notes: str = "",
    ) -> dict:
        """Create a calendar event (mock)."""
        return {
            "success": True,
            "message": f"Mock: 会议「{title}」已创建",
            "event_id": f"mock-event-{hash(title)}",
        }

    async def list_events(self, participant: str = "") -> list[dict]:
        """List upcoming events for a participant (mock)."""
        return []  # 暂无数据，后续接入日历 API


calendar_service = CalendarService()
