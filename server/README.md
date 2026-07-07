# Lite Ailoha Server

## 目录结构

```
server/
├── requirements.txt                # Python 依赖
└── app/
    ├── main.py                     # FastAPI 入口、CORS、生命周期、路由注册
    ├── config.py                   # 双模型配置（VISION_MODEL + LLM_MODEL）
    │
    ├── api/
    │   ├── analyze.py              # POST /api/v1/analyze (SSE: struct→card→insight→done)
    │   ├── actions.py              # POST /api/v1/actions/{id}/confirm|cancel
    │   ├── sessions.py             # GET /api/v1/sessions/{id} (质量评估查询)
    │   └── health.py               # GET /health
    │
    ├── schemas/
    │   ├── request.py              # AnalyzeRequest (image + user_context)
    │   └── response.py             # StructEvent, CardEvent, InsightEvent, ErrorEvent,
    │                               #   DoneEvent, SessionResponse, ActionResponse
    │
    ├── agent/
    │   ├── __init__.py             # LiteAilohaAgent 导出
    │   ├── deep_agent.py           # 双模型 Agent 组装 + SSE 流式包装
    │   ├── subagents.py            # 3 个子 Agent (使用 LLM_MODEL)
    │   ├── prompts.py              # 5 套 Prompt (Coordinator vision + 3 子 Agent + structurer)
    │   └── tools/
    │       ├── __init__.py         # 工具分组: STRUCTURE / MEETING / CONTACT / REMINDER / INSIGHT
    │       ├── structure.py        # structure_conversation — VISION_MODEL 看图结构化
    │       ├── meeting.py          # create_meeting
    │       ├── contact.py          # create_contact, update_contact, query_contacts
    │       ├── reminder.py         # create_reminder
    │       └── insight.py          # generate_insight
    │
    ├── services/
    │   ├── calendar.py             # 日历操作（MVP mock）
    │   ├── contact.py              # 联系人 CRUD（MVP mock）
    │   └── insight.py              # 跨域洞察生成
    │
    └── storage/
        ├── database.py             # SQLite (WAL) — contacts + confirmed_actions + analyze_sessions
        └── checkpoint.py           # LangGraph SqliteSaver
```

## 架构分层

```
┌─────────────────────────────────────────────────────────┐
│  api/         路由层 — HTTP → SSE / JSON 响应            │
├─────────────────────────────────────────────────────────┤
│  schemas/     Pydantic 契约层 — 请求/响应/SSE 事件格式    │
├─────────────────────────────────────────────────────────┤
│  agent/       Agent 智能层 — 多模型 + DeepAgents          │
│               Coordinator (VISION_MODEL) + 3 Subagents   │
├─────────────────────────────────────────────────────────┤
│  services/    业务服务层 — 日历/联系人/洞察 (MVP mock)     │
├─────────────────────────────────────────────────────────┤
│  storage/     持久化层 — SQLite + LangGraph checkpoint    │
└─────────────────────────────────────────────────────────┘
```

## 多模型架构

```
VISION_MODEL                          LLM_MODEL
(看图理解聊天截图)                     (纯文本推理)
      │                                     │
      ▼                                     ▼
Coordinator Agent                     子 Agent (Meeting/Contact/Reminder)
- structure_conversation              - 接收结构化对话 JSON
- generate_insight                    - 领域提取 + tool call
- 委派 task() 给子 Agent
```

两个模型通过 `.env` 独立配置：
```bash
# Coordinator 用（需要多模态）
VISION_MODEL=gpt-4o
VISION_API_KEY=sk-...
VISION_BASE_URL=https://api.openai.com/v1

# 子 Agent 用（纯文本即可）
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com/v1
```

## 请求流转路径

```
POST /api/v1/analyze {"image":"<base64>","user_context":"..."}
  │
  ▼ api/analyze.py — 验证 input → 生成 session_id
  │
  ▼ agent/deep_agent.py — LiteAilohaAgent.stream_analyze()
  _build_multimodal_prompt() — 文字指令 + 截图图片
  │
  ▼ create_deep_agent (Coordinator: VISION_MODEL)
  │
  ├─ 调用 structure_conversation tool
  │   └─ agent/tools/structure.py — VISION_MODEL 看图 → 结构化 JSON
  │      → SSE: event:struct
  │
  ├─ task("meeting-agent", structured_json)
  │   └─ tools/meeting.py — create_meeting()
  │      → SSE: event:card
  │
  ├─ task("contact-agent", structured_json)
  │   └─ tools/contact.py — create_contact / update_contact
  │      → SSE: event:card
  │
  ├─ task("reminder-agent", structured_json)
  │   └─ tools/reminder.py — create_reminder
  │      → SSE: event:card
  │
  └─ generate_insight
      └─ tools/insight.py
         → SSE: event:insight

  ▼ SSE 流完成 → 写入 analyze_sessions 表
  GET /api/v1/sessions/{id} → 完整会话数据（质量评估）
```

## SSE 协议

```
event: struct
id: 1
data: {"event":"struct","participants":["sqliang","张洪银"],"messages":[...]}

event: card
id: 2
data: {"event":"card","card":{"id":"...","type":"create_meeting","summary":"..."}}

event: insight
id: N
data: {"event":"insight","insight":"AI 洞察文本"}

event: done
id: N+1
data: {"event":"done","data":{}}
```

## 质量评估

每次分析完成后，完整会话数据存入 `analyze_sessions` 表：

```bash
# 查询某次分析的完整数据
curl http://localhost:8080/api/v1/sessions/{session_id}

# 返回:
{
  "session_id": "uuid",
  "structured_conversation": {"participants":[...], "messages":[...]},
  "cards": [{"id":"...","type":"create_meeting","summary":"..."}],
  "insight": "AI 洞察",
  "created_at": "2026-07-07T..."
}
```

对照原始截图、结构化对话、识别出的卡片三者，评估各环节质量。

## 开发命令

```bash
make install    # venv + pip install
make run        # uvicorn --reload :8080
make test       # pytest -v
make lint       # ruff check app/
make clean      # 清理缓存
```
