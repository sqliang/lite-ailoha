"""
SQLite 数据库设置（aiosqlite 异步驱动 + WAL 模式）。

数据库中存储三张核心表:
1. contacts           — 联系人信息（MVP mock 数据）
2. confirmed_actions  — 用户已确认的动作卡片
3. analyze_sessions   — 每次分析会话的完整数据
                        用于事后质量评估: 对比结构化对话 → 动作卡片 → 洞察

数据写入时机:
- analyze_sessions: POST /api/v1/analyze SSE 流完成后写入
- confirmed_actions: 用户在 iOS 端点击「确认」按钮时写入
- contacts: 通过 contact_service 创建/更新联系人时写入
"""
import aiosqlite
from app.config import settings

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """获取或初始化 SQLite 数据库连接（WAL 模式）。"""
    global _db
    if _db is None:
        # 从 connection string 中提取文件路径
        # 例如 "sqlite+aiosqlite:///./lite_ailoha.db" → "./lite_ailoha.db"
        db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
        _db = await aiosqlite.connect(db_path)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")   # Write-Ahead Logging，提升并发读性能
        await _init_schema(_db)
    return _db


async def _init_schema(db: aiosqlite.Connection):
    """
    创建数据库表（如果不存在）。

    表结构说明:

    contacts — 联系人信息
      - id: 自增主键
      - name: 联系人姓名（必填）
      - phone/email/company/title/notes: 联系人详细字段
      - meeting_count: 与该联系人的会议计数（用于洞察生成）
      - created_at/updated_at: 时间戳

    confirmed_actions — 用户确认的动作卡片（iOS 端点击「确认」后写入）
      - id: 卡片 ID（与 SSE 流中的 ActionCard.id 一致）
      - type: 动作类型（create_meeting / create_contact / update_contact / create_reminder）
      - summary: 中文摘要
      - status: 固定为 'confirmed'
      - created_at: 确认时间

    analyze_sessions — 每次分析的完整会话记录（用于质量评估）
      - session_id: UUID 格式的会话唯一标识
      - structured_conversation: VISION_MODEL 解析的结构化对话 JSON
         格式: {"participants": [...], "messages": [{"time": "...", "speaker": "...", "content": "..."}]}
      - cards: Agent 识别出的所有动作卡片 JSON 数组
         格式: [{"id": "...", "type": "...", "summary": "..."}]
      - insight: AI 生成的洞察文本
      - created_at: 会话创建时间（ISO 8601）
    """
    await db.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            company TEXT DEFAULT '',
            title TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            meeting_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS confirmed_actions (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            summary TEXT NOT NULL,
            status TEXT DEFAULT 'confirmed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # =========================================================================
    # analyze_sessions — 核心质量评估表
    # 存储每次分析的结构化对话 + 卡片 + 洞察，支持事后对照原始截图复盘
    # =========================================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS analyze_sessions (
            -- 会话唯一标识（UUID），与 SSE 流中的 session 关联
            session_id TEXT PRIMARY KEY,
            -- 结构化对话 JSON: {"participants":[...],"messages":[{"time":"...","speaker":"...","content":"..."}]}
            -- 由 VISION_MODEL (structure_conversation tool) 生成
            structured_conversation TEXT,
            -- 动作卡片 JSON 数组: [{"id":"...","type":"create_meeting","summary":"..."}]
            -- 由子 Agent (meeting/contact/reminder) 生成
            cards TEXT,
            -- AI 洞察文本
            -- 由 Coordinator (generate_insight tool) 生成
            insight TEXT,
            -- 会话创建时间（ISO 8601 格式）
            -- 会话状态（见 docs/DESIGN.md Session 状态机）
            -- PENDING → STRUCTURING → STRUCTURED → EXTRACTING → READY → GENERATING → COMPLETED
            session_state TEXT DEFAULT 'READY',
            -- 会话创建时间（ISO 8601 格式）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.commit()

    # 兼容旧数据库：新增 session_state 列
    try:
        await db.execute(
            "ALTER TABLE analyze_sessions ADD COLUMN session_state TEXT DEFAULT 'READY'"
        )
        await db.commit()
    except Exception:
        pass  # 列已存在，忽略

    # 兼容旧数据库：confirmed_actions 新增 fields 列
    try:
        await db.execute(
            "ALTER TABLE confirmed_actions ADD COLUMN fields TEXT DEFAULT '{}'"
        )
        await db.commit()
    except Exception:
        pass  # 列已存在，忽略


async def close_db():
    """关闭数据库连接（应用关闭时调用）。"""
    global _db
    if _db:
        await _db.close()
        _db = None
