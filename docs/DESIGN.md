# Lite Ailoha 架构设计方案 v2

> 本文档基于 v1 架构的实际运行问题和需求重新设计，替代 `docs/ARCHITECTURE.md` 作为当前设计参考。

## 目录

1. [需求回顾](#1-需求回顾)
2. [v1 架构问题分析](#2-v1-架构问题分析)
3. [总体设计](#3-总体设计)
4. [DeepAgent 设计](#4-deepagent-设计)
5. [Session 状态机](#5-session-状态机)
6. [API 设计](#6-api-设计)
7. [LLM 多模型管理](#7-llm-多模型管理)
8. [数据持久化](#8-数据持久化)
9. [服务端目录结构](#9-服务端目录结构)
10. [代码变更清单](#10-代码变更清单)
11. [实施顺序建议](#11-实施顺序建议)

---

## 1. 需求回顾

### 1.1 产品目标

Lite Ailoha 是一个 AI 驱动的聊天截图分析工具。用户上传聊天截图 → 系统识别可执行行动 → 用户确认 → 生成洞察 + 执行系统操作。

### 1.2 处理管道

```
聊天截图 + 可选补充文字
  → VISION_MODEL（多模态）看图 → 结构化对话 JSON
  → LLM_MODEL 从结构化 JSON 中提取会议/联系人/提醒
  → 生成 Action Cards
  → 用户在客户端确认/取消
  → 基于用户决策生成洞察建议
```

### 1.3 关键特征

**人在回路**：识别结果出来后用户需要决策（确认/取消每张卡片），后续洞察应基于用户的决策生成，而非在用户看到卡片之前就盲猜。

---

## 2. v1 架构问题分析

### 2.1 闭合式管道，人在回路不存在

```
v1 实际流程: /analyze → [struct → cards → insight → done] 一次性完成
正确流程:    /analyze → [struct → cards → done] → 用户交互 → 洞察生成
```

Coordinator 在所有子 Agent 完成后立即调用 `generate_insight`，用户还没有看到卡片，洞察就已经生成了。洞察与用户实际决策完全脱节。

### 2.2 Coordinator 模型选择不当

v1 中 Coordinator 使用 VISION_MODEL（豆包）。但 Coordinator 的职责是**任务规划与分发**，不直接看图。这应该是 LLM_MODEL（DeepSeek）的强项。

```
v1:  Coordinator = VISION_MODEL（豆包）  → 用视觉模型做逻辑规划
v2:  Coordinator = LLM_MODEL（DeepSeek）  → 用推理模型做逻辑规划
```

### 2.3 死代码

- `deep_agent.py` 中 `self._text_llm` 创建了但从未使用（子 Agent 的 LLM 在 `subagents.py` 中独立创建）
- `deep_agent.py` 和 `structure.py` 各创建了一份 VISION_MODEL 实例

### 2.4 状态管理缺失

当前没有任何会话状态概念。客户端收到 SSE 事件后无法区分"正在处理中"和"等待用户操作"。

---

## 3. 总体设计

### 3.1 两阶段人在回路

```
┌──────────────────────────────────────────────────────────────┐
│  阶段一: POST /api/v1/analyze                                │
│                                                              │
│  DeepAgent Coordinator (DeepSeek)                             │
│    ├── 调用 structure_conversation 工具（内部调豆包看图）       │
│    │     → 结构化对话 JSON                                    │
│    │     → SSE: event:struct                                 │
│    │                                                          │
│    ├── 委派三个子 Agent（并行，各用 DeepSeek）                  │
│    │   ├── meeting-agent   → create_meeting tool              │
│    │   ├── contact-agent   → create_contact/update_contact   │
│    │   └── reminder-agent  → create_reminder tool             │
│    │     → SSE: event:card × N                                │
│    │                                                          │
│    └── SSE: event:done                                        │
│  状态: PENDING → STRUCTURING → EXTRACTING → READY             │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  用户交互（iOS 端）                                           │
│                                                              │
│  - 展示结构化对话（可折叠） + 动作卡片                          │
│  - 确认/取消每张卡片                                          │
│  - 确认的卡片调用系统 API 执行                                │
│  状态: READY → CONFIRMING                                    │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  阶段二: POST /api/v1/sessions/{id}/insight                   │
│                                                              │
│  输入: session_id                                            │
│        → 从 DB 查询结构化对话 + 卡片 + 用户确认状态              │
│        → 查询已有联系人/日历数据                               │
│                                                              │
│  DeepAgent Coordinator (DeepSeek，同一 Agent 的第二轮)         │
│    └── 调用 generate_insight 工具                             │
│          → 基于确认结果 + 上下文 → 洞察建议                     │
│          → SSE: event:insight                                 │
│          → SSE: event:done                                    │
│  状态: GENERATING → COMPLETED                                 │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 为什么是两轮对话而非两阶段

一个 DeepAgent 实例，两轮对话：

- **第一轮**：用户发图片 + 文字 → Agent 返回 struct + cards
- **第二轮**：用户（通过 API 传入）确认结果 → Agent 返回 insight

LiteAilohaDeepAgent 是单例，LangGraph 的 SqliteSaver 负责跨轮持久化对话状态。但考虑到 iOS 客户端需要独立发起阶段二请求，且阶段之间可能间隔较长时间，阶段二的请求是独立的 HTTP 调用，在服务端通过 session_id 获取上下文后，构造一条新的用户消息送入 Agent。

---

## 4. DeepAgent 设计

### 4.1 整体结构

```
LiteAilohaDeepAgent（单实例）

  create_deep_agent(
    model = LLM_MODEL (DeepSeek),        ← Coordinator: 规划 + 分发
    
    tools = [
      structure_conversation,             ← 看图工具（内部调用 VISION_MODEL）
      generate_insight,                   ← 洞察工具
    ],
    
    subagents = [
      meeting_agent,                      ← 领域: 会议提取
      contact_agent,                      ← 领域: 联系人提取
      reminder_agent,                     ← 领域: 提醒提取
    ],
  )
```

### 4.2 为什么 tool 和 subagent 这样划分

| 组件 | 类型 | 为什么 | 模型 |
|------|------|--------|------|
| `structure_conversation` | tool | 一次性任务：看图 → 输出 JSON。不需要多步推理 | 内部调 VISION_MODEL（豆包） |
| `generate_insight` | tool | 一次性任务：基于上下文 → 输出洞察 | Coordinator 调，用 LLM_MODEL |
| `meeting-agent` | subagent | 需要领域推理：判断语义、查已有数据、决定创建什么 | LLM_MODEL（DeepSeek） |
| `contact-agent` | subagent | 同上，且有 create_contact 和 update_contact 两种操作 | LLM_MODEL（DeepSeek） |
| `reminder-agent` | subagent | 同上 | LLM_MODEL（DeepSeek） |

**tool 和 subagent 的本职区别**：

- **tool**：单一动作，一次 LLM 调用即可完成。Coordinator 直接调用，结果直接返回。
- **subagent**：需要独立推理空间。有自己独立的 system_prompt、独立的工具集。Coordinator 委派任务给它，它在自己的上下文中完成推理后返回结果。

### 4.3 Coordinator 设计（DeepSeek）

```
Coordinator
  模型: DeepSeek (LLM_MODEL)
  系统提示词: COORDINATOR_PROMPT
  
  职责:
    1. 理解用户意图（分析截图 → 提取行动）
    2. 调用 structure_conversation 获取结构化 JSON
    3. 基于结构化 JSON，并行委派三个领域子 Agent
    4. 收集子 Agent 结果，输出阶段一总结
    5. （阶段二）基于用户确认结果，调用 generate_insight
```

### 4.4 子 Agent 设计

```python
# meeting_agent
{
    "name": "meeting-agent",
    "description": "从结构化对话 JSON 中识别会议安排",
    "system_prompt": MEETING_SUBAGENT_PROMPT,
    "tools": [create_meeting, query_contacts],
    "model": get_text_llm(),   # LLM_MODEL (DeepSeek)
}

# contact_agent
{
    "name": "contact-agent",
    "description": "从结构化对话 JSON 中识别联系人创建/更新需求",
    "system_prompt": CONTACT_SUBAGENT_PROMPT,
    "tools": [create_contact, update_contact, query_contacts],
    "model": get_text_llm(),
}

# reminder_agent
{
    "name": "reminder-agent",
    "description": "从结构化对话 JSON 中识别提醒事项",
    "system_prompt": REMINDER_SUBAGENT_PROMPT,
    "tools": [create_reminder],
    "model": get_text_llm(),
}
```

### 4.5 structure_conversation 工具

```
structure_conversation（tool）
  输入: 无参数（图片从共享变量读取，不走 LLM 参数）
  内部: 调用 VISION_MODEL（豆包）看图
  输出: {participants: [...], messages: [{time, speaker, content}]}
  
  为什么图片走共享变量:
    Coordinator 是 LLM，它生成 tool call 参数时无法准确复制
    42KB+ 的 base64 数据，会截断导致视觉模型解析出 1×1 像素错误。
```

### 4.6 阶段二：同一 Agent 的继续对话

```
POST /api/v1/sessions/{id}/insight

服务端处理:
  1. 从 analyze_sessions 表查出:
     - structured_conversation
     - cards 列表
     - confirmed_actions 中每张卡片的确认/取消状态
  
  2. 从 contacts/calendar 服务查出已有数据
  
  3. 构造用户消息:
     "用户已查看分析结果并做出决策。请基于以下信息调用 generate_insight：
      
      结构化对话: {JSON}
      用户确认的卡片:
        - [create_reminder] 周二前投递简历
        - [create_meeting] 和张三的产品评审会
      用户取消的卡片:
        - [create_contact] 添加李四
      
      已有联系人: [...]
      已有日历: [...]"
  
  4. Agent.astream_events(消息, version="v2")
  
  5. 监听 on_tool_end: generate_insight → yield SSE event:insight
  
  6. yield SSE event:done
```

---

## 5. Session 状态机

### 5.1 状态定义

| 状态 | 触发条件 | 说明 |
|------|---------|------|
| `PENDING` | 请求到达，session 创建 | 等待处理开始 |
| `STRUCTURING` | 开始调用 structure_conversation | VISION_MODEL 看图中 |
| `STRUCTURED` | structure_conversation 完成 | 结构化对话已获取 |
| `STRUCTURE_FAILED` | structure_conversation 失败 | 看图失败，终止流程 |
| `EXTRACTING` | 开始委派子 Agent | LLM_MODEL 提取卡片中 |
| `EXTRACTED` | 全部子 Agent 完成且有卡片 | 提取完成 |
| `PARTIAL` | 部分子 Agent 完成 | 至少有一张卡片，但非全部成功 |
| `NO_CARDS` | 全部完成但无卡片 | 聊天中无可执行动作 |
| `READY` | 阶段一 SSE done | 等待用户交互 |
| `CONFIRMING` | 用户开始确认/取消 | 用户操作中 |
| `GENERATING` | 阶段二开始 | InsightAgent 生成中 |
| `COMPLETED` | 阶段二完成 | 全部完成 |
| `INSIGHT_FAILED` | 阶段二失败 | 洞察失败，但阶段一数据仍可用 |

### 5.2 状态机图

```
PENDING
  │
  ▼
STRUCTURING ──❌──→ STRUCTURE_FAILED (终止)
  │
  ▼
STRUCTURED
  │
  ▼
EXTRACTING
  ├── ✅ ──→ EXTRACTED
  ├── ⚠️ ──→ PARTIAL
  └── ⚠️ ──→ NO_CARDS
  │
  ▼
READY
  │
  ▼
CONFIRMING
  │
  ▼
GENERATING
  ├── ✅ ──→ COMPLETED
  └── ❌ ──→ INSIGHT_FAILED
```

### 5.3 状态传递方式

**方式一：SSE 事件中携带**

每个 SSE 事件的 `data:` JSON 中包含 `session_state` 字段。客户端收到事件时同步更新 UI 状态。

**方式二：GET /api/v1/sessions/{id} 查询**

返回 `session_state` 字段，客户端可随时轮询或刷新。

### 5.4 iOS 端状态驱动的 UI

| session_state | UI 展示 |
|--------------|---------|
| `PENDING` | — |
| `STRUCTURING` | 进度指示器 + "正在理解聊天内容..." |
| `STRUCTURED` | 可折叠结构化对话区域出现（参与人数、消息数） |
| `EXTRACTING` | "正在识别待办事项..." + 卡片区域 skeleton |
| `EXTRACTED` | 全部卡片渲染完成，确认/取消按钮可点击 |
| `PARTIAL` | 卡片列表 + "部分内容未能识别" 提示 |
| `NO_CARDS` | 结构化对话 + "聊天中未发现待办事项" |
| `READY` | 所有卡片可交互 |
| `GENERATING` | "正在基于你的选择生成建议..." |
| `COMPLETED` | 洞察卡片出现，全流程结束 |
| `STRUCTURE_FAILED` | 错误提示 + 重试按钮 |
| `INSIGHT_FAILED` | 洞察区域显示失败提示，卡片仍可查看 |

---

## 6. API 设计

### 6.1 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/analyze` | **阶段一**：SSE: struct → card × N → done |
| `POST` | `/api/v1/actions/{id}/confirm` | 确认卡片 + 持久化 + 调用系统 API |
| `POST` | `/api/v1/actions/{id}/cancel` | 取消卡片 + 持久化 |
| `POST` | `/api/v1/sessions/{id}/insight` | **阶段二**：SSE: insight → done（新端点） |
| `GET` | `/api/v1/sessions/{id}` | 查询完整会话（含 session_state） |
| `GET` | `/health` | 健康检查 |

### 6.2 阶段一 SSE 事件格式

```
event:struct
id:1
data:{"session_state":"STRUCTURED","participants":["张三","李四"],"messages":[...]}

event:card
id:2
data:{"session_state":"EXTRACTING","card":{"id":"create_reminder-abc","type":"create_reminder","summary":"..."}}

event:done
id:3
data:{"session_state":"READY","event":"done"}
```

### 6.3 阶段二：POST /api/v1/sessions/{id}/insight

```
请求:
  POST /api/v1/sessions/abc-123/insight
  Body: 无需传参（服务端从 DB 获取上下文）

响应 (SSE):
  event:insight
  id:1
  data:{"session_state":"GENERATING","insight":"..."}
  
  event:done
  id:2
  data:{"session_state":"COMPLETED","event":"done"}
```

**前置条件**：
- session 存在且 session_state 不为 `STRUCTURE_FAILED`
- 至少有一张卡片被确认
- 不满足 → 400 + 错误说明

**失败处理**：
- 阶段二失败不影响阶段一的结果
- `INSIGHT_FAILED` 状态下，struct + cards 仍然可通过 GET API 查询

### 6.4 阶段一失败处理

| 失败节点 | session_state | 行为 |
|---------|:--:|------|
| 输入为空 | — | SSE error，不创建 session |
| VISION_MODEL 失败 | `STRUCTURE_FAILED` | SSE error，session 保留但标记失败 |
| LLM_MODEL 全部失败 | `STRUCTURED` | SSE error，struct 可查看 |
| LLM_MODEL 部分失败 | `PARTIAL` | 成功的卡片正常推送 |

### 6.5 阶段一和阶段二的衔接

阶段二客户端只传 `session_id`。服务端：

```python
# 1. 查询阶段一的结果
session = await db.query("SELECT * FROM analyze_sessions WHERE session_id = ?", session_id)

# 2. 查询用户对每张卡片的决策
cards = json.loads(session["cards"])
confirmed = await db.query(
    "SELECT * FROM confirmed_actions WHERE id IN (?)", 
    [c["id"] for c in cards]
)

# 3. 查询已有数据
contacts = await contact_service.list_all()
calendar = await calendar_service.list_events()

# 4. 构造消息 → 送入 Agent 的第二轮对话
message = build_insight_message(
    structured=session["structured_conversation"],
    cards=cards,
    confirmed=confirmed,
    contacts=contacts,
    calendar=calendar,
)
```

---

## 7. LLM 多模型管理

### 7.1 模型分工

| 角色 | 模型 | 原因 |
|------|------|------|
| **Coordinator**（大脑） | DeepSeek (LLM_MODEL) | 规划分发、逻辑推理、结果合成 |
| **structure_conversation**（看图） | 豆包 (VISION_MODEL) | 多模态，需要理解图片内容 |
| **meeting-agent**（执行） | DeepSeek (LLM_MODEL) | 纯文本领域推理 |
| **contact-agent**（执行） | DeepSeek (LLM_MODEL) | 纯文本领域推理 |
| **reminder-agent**（执行） | DeepSeek (LLM_MODEL) | 纯文本领域推理 |
| **generate_insight**（洞察） | DeepSeek (LLM_MODEL) | 纯文本推理 |

### 7.2 实例管理：llm_factory.py 统一单例

```python
# llm_factory.py

_vision_llm = None   # VISION_MODEL（豆包）：只有 structure_conversation 内部用
_text_llm = None     # LLM_MODEL（DeepSeek）：Coordinator + 子 Agent + 洞察都用

def get_vision_llm() -> ChatOpenAI:
    """VISION_MODEL 单例 — 仅在 structure_conversation 工具内部使用"""
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = create_chat_openai(
            model=settings.vision_model,
            api_key=settings.vision_api_key,
            base_url=settings.vision_base_url,
        )
    return _vision_llm

def get_text_llm() -> ChatOpenAI:
    """LLM_MODEL 单例 — Coordinator、子 Agent、洞察生成共用"""
    global _text_llm
    if _text_llm is None:
        _text_llm = create_chat_openai(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    return _text_llm
```

### 7.3 DeepAgent 如何拿到正确的模型

```python
# deep_agent.py — 创建 Agent 时

agent = create_deep_agent(
    model=get_text_llm(),    # Coordinator 用 DeepSeek（大脑）
    tools=[
        structure_conversation,   # 内部自己调 get_vision_llm()（豆包）
        generate_insight,         # Coordinator 调用，走 DeepSeek
    ],
    subagents=[
        {**meeting_agent,   "model": get_text_llm()},
        {**contact_agent,   "model": get_text_llm()},
        {**reminder_agent,  "model": get_text_llm()},
    ],
)
```

**关键**：`create_deep_agent(model=...)` 的 model 决定 Coordinator 用什么模型。子 Agent 的 model 通过各自 dict 的 `"model"` 字段指定。structure_conversation 是 tool，它内部自己获取 VISION_MODEL，不依赖 Coordinator。

---

## 8. 数据持久化

### 8.1 analyze_sessions 表

```sql
CREATE TABLE analyze_sessions (
    session_id              TEXT PRIMARY KEY,           -- UUID
    session_state           TEXT DEFAULT 'PENDING',     -- 状态机状态
    structured_conversation TEXT,                        -- JSON: VISION_MODEL 输出
    cards                   TEXT,                        -- JSON: ActionCard 数组
    insight                 TEXT,                        -- AI 洞察文本
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);
```

### 8.2 confirmed_actions 表（已有，启用）

```sql
CREATE TABLE confirmed_actions (
    id         TEXT PRIMARY KEY,    -- card.id
    type       TEXT,                -- create_meeting / create_contact / ...
    summary    TEXT,                -- 卡片摘要
    status     TEXT,                -- confirmed | cancelled
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 8.3 写入时机

| 时机 | 写入内容 | 表 |
|------|---------|-----|
| 请求到达 | session_id + `PENDING` | analyze_sessions |
| struct 推送后 | structured_conversation + session_state=`STRUCTURED` | analyze_sessions |
| 所有 card 推送后 | cards JSON + session_state=`EXTRACTED` 等 | analyze_sessions |
| 用户确认/取消 | card 记录 + status | confirmed_actions |
| insight 推送后 | insight 文本 + session_state=`COMPLETED` | analyze_sessions |

### 8.4 注意

`session_state` 字段 v1 数据库中**不存在**，需要 ALTER TABLE 新增，或渐进兼容（无此字段时客户端不展示状态信息）。

---

## 9. 服务端目录结构

### 9.1 设计原则

- **按职责分层，不是按技术分层**：`api/` 管 HTTP，`agent/` 管 AI，`services/` 管业务，`storage/` 管持久化
- **agent/ 是核心**：所有 AI 相关的代码都在这里，与 DeepAgents 的架构概念一一对应
- **每个模块有明确的单一职责**：一个文件管一件事，不交叉

### 9.2 目录树

```
server/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI 入口： lifespan、CORS、路由注册、日志、LangSmith
│   ├── config.py                        # 配置（从 .env 加载）
│   │
│   ├── api/                             # HTTP 层：只做参数校验、SSE 包装、状态转换
│   │   ├── __init__.py
│   │   ├── analyze.py                   # POST /api/v1/analyze — 阶段一
│   │   ├── actions.py                   # POST /api/v1/actions/{id}/confirm|cancel
│   │   ├── sessions.py                  # GET /sessions/{id} + POST /sessions/{id}/insight
│   │   └── health.py                    # GET /health
│   │
│   ├── agent/                           # AI 核心：DeepAgent 的所有组件
│   │   ├── __init__.py                  # 导出 LiteAilohaAgent
│   │   ├── deep_agent.py                # LiteAilohaAgent：create_deep_agent + stream_analyze
│   │   ├── llm_factory.py               # LLM 实例工厂：get_vision_llm() / get_text_llm()
│   │   │
│   │   ├── prompts/                     # 系统提示词（一个 Agent 一个文件）
│   │   │   ├── __init__.py
│   │   │   ├── coordinator.py           # Coordinator 提示词
│   │   │   ├── meeting.py               # 会议子 Agent 提示词
│   │   │   ├── contact.py               # 联系人子 Agent 提示词
│   │   │   └── reminder.py              # 提醒子 Agent 提示词
│   │   │
│   │   ├── subagents/                   # 子 Agent 定义（一个领域一个文件）
│   │   │   ├── __init__.py              # 统一导出 get_all_subagents()
│   │   │   ├── meeting.py               # meeting-agent：name, description, prompt, tools, model
│   │   │   ├── contact.py               # contact-agent：create + update
│   │   │   └── reminder.py              # reminder-agent
│   │   │
│   │   └── tools/                       # Agent 可调用的工具函数
│   │       ├── __init__.py              # 工具分组注册
│   │       ├── structure.py             # structure_conversation：看图 → 结构化 JSON
│   │       ├── meeting.py               # create_meeting
│   │       ├── contact.py               # create_contact / update_contact / query_contacts
│   │       ├── reminder.py              # create_reminder
│   │       └── insight.py               # generate_insight
│   │
│   ├── services/                        # 业务服务层：工具背后的实际逻辑
│   │   ├── __init__.py
│   │   ├── calendar.py                  # 日历操作（当前为 Mock）
│   │   ├── contact.py                   # 联系人操作（当前为 Mock）
│   │   └── insight.py                   # 洞察生成（当前为 Mock）
│   │
│   ├── storage/                         # 持久化层
│   │   ├── __init__.py
│   │   ├── database.py                  # SQLite 初始化 + get_db()
│   │   └── checkpoint.py                # LangGraph SqliteSaver
│   │
│   └── schemas/                         # Pydantic 数据模型
│       ├── __init__.py
│       ├── request.py                   # AnalyzeRequest / ActionRequest
│       └── response.py                  # SSE 事件模型 / ActionCard / SessionResponse
│
├── requirements.txt
└── README.md
```

### 9.3 模块职责与依赖

```
┌─────────────────────────────────────────────────────────────────┐
│  api/          HTTP 层                                          │
│  依赖: agent/, schemas/, storage/                               │
│  职责: 参数校验、SSE 事件包装、session_state 更新、异步生成器      │
│  不负责: 任何 AI 逻辑、业务逻辑                                   │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  agent/        AI 核心                                          │
│  依赖: config.py, services/, prompts/, tools/, llm_factory.py   │
│  职责: DeepAgent 创建与管理、流式事件解析、工具调用路由             │
│                                                                  │
│  内部结构:                                                       │
│    deep_agent.py   ← 编排层: 创建 Agent, stream_analyze()       │
│    subagents.py    ← 子Agent定义: meeting/contact/reminder      │
│    tools/          ← 工具函数: 被 Coordinator 或子Agent 调用     │
│    prompts/        ← 提示词: 每个 Agent 的 system_prompt         │
│    llm_factory.py  ← LLM 实例: 单例管理 VISION_MODEL/LLM_MODEL  │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  services/     业务服务层                                        │
│  依赖: storage/                                                 │
│  职责: 工具背后的实际业务逻辑（日历、联系人、洞察）                 │
│  现状: MVP Mock，后续对接真实 API                                 │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  storage/      持久化层                                          │
│  依赖: config.py                                                │
│  职责: SQLite 连接管理、表创建、LangGraph checkpoint              │
└─────────────────────────────────────────────────────────────────┘
```

### 9.4 agent/ 核心目录详解

这是整个服务端的核心。按 DeepAgents 的概念组织：

| 文件 | 对应 DeepAgents 概念 | 职责 |
|------|---------------------|------|
| `deep_agent.py` | `create_deep_agent()` | 组装 Agent：Coordinator + tools + subagents |
| `subagents/` | `subagents` 参数 | 子 Agent 定义目录，一个领域一个文件 |
| `subagents/__init__.py` | — | 统一导出 `get_all_subagents()` |
| `subagents/meeting.py` | meeting-agent | name, description, system_prompt, tools, model |
| `subagents/contact.py` | contact-agent | name, description, system_prompt, tools, model |
| `subagents/reminder.py` | reminder-agent | name, description, system_prompt, tools, model |
| `prompts/` | `system_prompt` | 每个 Agent 的系统提示词 |
| `tools/` | `tools` 参数 | 可被调用的工具函数 |
| `llm_factory.py` | `model` 参数 | 提供 LLM 实例 |

**数据流**：

```
deep_agent.py
  │
  ├── 从 llm_factory.py 获取 get_text_llm() → Coordinator 大脑
  ├── 从 subagents/    获取三个子 Agent 定义（meeting/contact/reminder）
  ├── 从 tools/        获取工具列表（structure, meeting, contact, reminder, insight）
  ├── 从 prompts/      获取系统提示词（coordinator + 三个子 agent）
  │
  └── create_deep_agent(...) → 可被 analyze.py 和 sessions.py 调用
        │
        ├── stream_analyze()        → 被 api/analyze.py 的阶段一调用
        └── stream_insight()        → 被 api/sessions.py 的阶段二调用
```

### 9.5 api/ 与 agent/ 的边界

```
api/analyze.py:
  - 收到 HTTP 请求
  - 校验参数
  - 生成 session_id
  - 初始化 session_state = PENDING
  - 调用 agent.stream_analyze(image_b64, user_context)
  - 消费 AsyncIterator，包装为 SSE 格式 yield
  - 每个 SSE 事件携带 session_state
  - 调用 storage 持久化

  ✗ 不知道 DeepAgent 内部有几个 tool
  ✗ 不知道哪个模型在处理
  ✗ 不知道 on_tool_end 是什么意思

agent/deep_agent.py:
  - 接收 image_b64 + user_context
  - 构建多模态消息
  - 调用 Agent.astream_events()
  - 解析 on_tool_end → {"type": "struct|card|insight|done", "data": ...}
  - yield 给上游

  ✗ 不知道 HTTP 协议
  ✗ 不知道 SSE 格式
  ✗ 不知道 session_id 是什么
```

---

## 10. 代码变更清单

### 10.1 新建

| 文件 | 内容 |
|------|------|
| `docs/DESIGN.md` | 本文档 |
| `server/app/agent/llm_factory.py` | 统一 LLM 单例管理（已存在，需重构） |

| 文件 | 内容 |
|------|------|
| `docs/DESIGN.md` | 本文档 |

### 10.2 修改

| 文件 | 变更 |
|------|------|
| `server/app/agent/llm_factory.py` | 统一 `get_vision_llm()` / `get_text_llm()` 单例 |
| `server/app/agent/deep_agent.py` | Coordinator 改用 `get_text_llm()`；删除 `_text_llm`；不生成 insight |
| `server/app/agent/subagents.py` | 拆分为 `subagents/` 目录（meeting.py / contact.py / reminder.py），统一改用 `llm_factory.get_text_llm()` |
| `server/app/agent/tools/structure.py` | 改用 `llm_factory.get_vision_llm()`；删独立 LLM 实例 |
| `server/app/agent/__init__.py` | 调整导出 |
| `server/app/api/analyze.py` | SSE 事件加 `session_state`；去掉 insight；加状态更新 |
| `server/app/api/actions.py` | 持久化到 `confirmed_actions` 表 |
| `server/app/api/sessions.py` | 新增 `POST /{id}/insight`；GET 返回加 `session_state` |
| `server/app/schemas/response.py` | SSE 事件模型加 `session_state` 字段 |
| `server/app/storage/database.py` | `analyze_sessions` 加 `session_state` 列 |

### 10.3 不变

| 文件 | 原因 |
|------|------|
| `config.py` | 配置不变 |
| `prompts/` | Prompt 内容不变（只可能微调 COORDINATOR_PROMPT） |
| `services/` | Mock 保留 |
| `tools/meeting.py` | tool 函数保留 |
| `tools/contact.py` | tool 函数保留 |
| `tools/reminder.py` | tool 函数保留 |
| `tools/insight.py` | tool 函数保留 |
| `tools/__init__.py` | 工具注册保留 |

### 10.4 不需要删除

之前考虑的删除 `tools/` 目录等大型重构**不需要**。v1 的 tool 定义、subagent 定义都是正确的，问题只在 Coordinator 的模型选择和流程编排上。

---

## 11. 重构实施方案

> 分 4 个阶段执行，每阶段完成后可独立验证。修改原则：小步快走，每步可回滚。

### 阶段 A：LLM 实例统一（不影响功能）

#### A1. 重构 `llm_factory.py`

**目标**：提供 `get_vision_llm()` 和 `get_text_llm()` 两个模块级单例，统一管理所有 ChatOpenAI 实例。

**修改前**：
```python
def create_chat_openai(model, api_key, base_url, temperature=0.3):
    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url,
                      temperature=temperature,
                      http_async_client=_get_async_client())
```

**修改后**：
```python
_vision_llm = None
_text_llm = None

def get_vision_llm() -> ChatOpenAI:
    """VISION_MODEL 单例 — structure_conversation 工具内部使用"""
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = create_chat_openai(
            model=settings.vision_model,
            api_key=settings.vision_api_key,
            base_url=settings.vision_base_url,
        )
    return _vision_llm

def get_text_llm() -> ChatOpenAI:
    """LLM_MODEL 单例 — Coordinator + 子Agent + 洞察 共用"""
    global _text_llm
    if _text_llm is None:
        _text_llm = create_chat_openai(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    return _text_llm

# 保留 create_chat_openai 作为内部实现
def create_chat_openai(model, api_key, base_url, temperature=0.3):
    ...
```

#### A2. 重构 `tools/structure.py`

**目标**：删除独立 `_vision_llm`，改用 `get_vision_llm()`。

**修改前**：
```python
from langchain_openai import ChatOpenAI
from app.config import settings

_vision_llm = None

def _get_vision_llm():
    global _vision_llm
    if _vision_llm is None:
        _vision_llm = ChatOpenAI(model=settings.vision_model, ...)
    return _vision_llm
```

**修改后**：
```python
from app.agent.llm_factory import get_vision_llm
# 删除 _vision_llm 和 _get_vision_llm()，所有引用处改为 get_vision_llm()
```

**修改位置**：`structure_conversation` 函数中 `_get_vision_llm().invoke(messages)` → `get_vision_llm().invoke(messages)`

#### A3. 重构 `subagents/`

**目标**：拆分 `subagents.py` 为 `subagents/` 目录，统一用 `get_text_llm()`。

**第一步：创建目录结构**

```
subagents/
├── __init__.py     # 导出 get_all_subagents()
├── meeting.py      # meeting-agent 定义
├── contact.py      # contact-agent 定义
└── reminder.py     # reminder-agent 定义
```

**第二步：`subagents/__init__.py`**

```python
"""子 Agent 定义 — 一个领域一个文件"""
from app.agent.subagents.meeting import meeting_subagent
from app.agent.subagents.contact import contact_subagent
from app.agent.subagents.reminder import reminder_subagent
from app.agent.llm_factory import get_text_llm

def get_all_subagents() -> list[dict]:
    llm = get_text_llm()
    return [
        {**meeting_subagent, "model": llm},
        {**contact_subagent, "model": llm},
        {**reminder_subagent, "model": llm},
    ]

__all__ = ["get_all_subagents"]
```

**第三步：`subagents/meeting.py`**

```python
"""meeting-agent：从结构化对话中识别会议安排"""
from app.agent.tools import MEETING_TOOLS
from app.agent.prompts import MEETING_SUBAGENT_PROMPT

meeting_subagent = {
    "name": "meeting-agent",
    "description": (
        "专门从结构化对话 JSON 中识别会议安排。"
        "当需要判断对话中是否包含会议创建需求时使用此 Agent。"
    ),
    "system_prompt": MEETING_SUBAGENT_PROMPT,
    "tools": MEETING_TOOLS,
    # model 由 get_all_subagents() 统一注入
}
```

**第四步**：`contact.py` 和 `reminder.py` 同理。

**第五步**：删除旧的 `subagents.py`。

#### A4. 重构 `deep_agent.py`

**目标**：改用 `get_vision_llm()` / `get_text_llm()`；删除 `_text_llm`；Coordinator 改用 LLM_MODEL。

**修改前**：
```python
from app.agent.llm_factory import create_chat_openai

def _ensure_initialized(self):
    self._vision_llm = create_chat_openai(
        model=settings.vision_model, ...)
    self._text_llm = create_chat_openai(       # ← 死代码
        model=settings.llm_model, ...)
    self._agent = create_deep_agent(
        model=self._vision_llm, ...)           # ← Coordinator 用 VISION_MODEL
```

**修改后**：
```python
from app.agent.llm_factory import get_text_llm

def _ensure_initialized(self):
    self._agent = create_deep_agent(
        model=get_text_llm(),                  # Coordinator 用 LLM_MODEL
        system_prompt=COORDINATOR_PROMPT,
        tools=STRUCTURE_TOOLS + INSIGHT_TOOLS,
        subagents=get_all_subagents(),
    )
```

**关键变化**：
- 删除 `self._vision_llm` 和 `self._text_llm` 的定义
- `create_deep_agent(model=...)` 从 VISION_MODEL 改为 LLM_MODEL
- `get_all_subagents()` 内部已通过 `get_text_llm()` 为子 Agent 注入模型
- structure_conversation 工具内部通过 `get_vision_llm()` 获取视觉模型

**验证**：`make run` + curl 测试，确认管道正常运行。

---

### 阶段 B：Session 状态机（新增概念，不影响现有流程）

#### B1. 数据库迁移

```sql
-- 新增 session_state 列
ALTER TABLE analyze_sessions ADD COLUMN session_state TEXT DEFAULT 'READY';

-- 已有记录默认标记为 READY（兼容旧数据）
UPDATE analyze_sessions SET session_state = 'READY' WHERE session_state IS NULL;
```

**实现方式**：在 `database.py` 的 `_init_schema()` 中增加 ALTER TABLE 逻辑，用 `try/except` 处理列已存在的情况。

#### B2. 更新 `schemas/response.py`

每个 SSE 事件模型加 `session_state` 字段：

```python
class StructEvent(BaseModel):
    event: str = "struct"
    session_state: str = "STRUCTURED"      # 新增
    participants: list[str]
    messages: list[dict]

class CardEvent(BaseModel):
    event: str = "card"
    session_state: str = "EXTRACTING"      # 新增
    card: ActionCard

class InsightEvent(BaseModel):
    event: str = "insight"
    session_state: str = "GENERATING"      # 新增
    insight: str

class DoneEvent(BaseModel):
    event: str = "done"
    session_state: str = "READY"           # 新增（阶段一）/ "COMPLETED"（阶段二）
```

#### B3. 更新 `analyze.py` SSE 事件

每个 yield 的 data JSON 中加入 `session_state`：

```python
# struct 事件
yield {
    "event": "struct",
    "id": str(event_id),
    "data": struct_event.model_dump_json(),  # 已含 session_state
}

# 持久化时也更新 session_state
await db.execute(
    "UPDATE analyze_sessions SET session_state = ? WHERE session_id = ?",
    ("STRUCTURED", session_id),
)
```

**验证**：SSE 输出的 data 中确认出现 `session_state` 字段。

---

### 阶段 C：两阶段拆分（功能变更）

#### C1. `analyze.py` — 去掉 insight 生成

**修改前**：Coordinator 的 prompt 驱动它在所有子 Agent 完成后调用 `generate_insight`

**修改后**：Coordinator 在阶段一**不调用** `generate_insight`。

**实现方式**：修改 `COORDINATOR_PROMPT`，去掉第三步"生成洞察"，改为：
```
### 第三步: 输出总结
在所有子 Agent 返回结果后，输出总结信息，告知用户请查看卡片并确认。
```

同时从 `stream_analyze()` 中删除对 `generate_insight` on_tool_end 的监听（或保留但不触发）。

#### C2. `actions.py` — 持久化用户决策

```python
@router.post("/api/v1/actions/{action_id}/confirm")
async def confirm_action(action_id: str, _body: ActionRequest):
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO confirmed_actions (id, type, summary, status) "
        "VALUES (?, ?, ?, ?)",
        (action_id, _body.type or "", _body.summary or "", "confirmed"),
    )
    await db.commit()
    return ActionResponse(action_id=action_id, status="confirmed", ...)
```

#### C3. `sessions.py` — 新增阶段二端点

```python
@router.post("/api/v1/sessions/{session_id}/insight")
async def generate_insight(session_id: str):
    # 1. 查询阶段一数据
    session = await _get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["session_state"] in ("PENDING", "STRUCTURING", "STRUCTURE_FAILED"):
        raise HTTPException(400, "阶段一未完成，无法生成洞察")
    
    # 2. 查询用户确认的卡片
    cards = json.loads(session["cards"] or "[]")
    confirmed = await _get_confirmed_actions([c["id"] for c in cards])
    
    # 3. 构造阶段二消息
    message = _build_insight_message(session, confirmed)
    
    # 4. 送入同一个 Agent，继续 astream_events
    async def event_stream():
        yield {"event": "session_state", "data": json.dumps({"state": "GENERATING"})}
        async for event in _get_agent().stream_analyze(message):
            if event["type"] == "insight":
                yield {"event": "insight", "id": ..., "data": ...}
        yield {"event": "done", ...}
    
    return EventSourceResponse(event_stream())
```

**验证**：阶段一完成后，用 curl 调用阶段二端点，确认返回 insight。

---

### 阶段 D：清理与测试

#### D1. 清理

- 删除旧的 `subagents.py`（已拆分为 `subagents/`）
- 删除 `deep_agent.py` 中无用的 `self._vision_llm`、`self._text_llm`
- 删除 `tools/structure.py` 中独立 `_vision_llm`

#### D2. 全链路测试

```bash
# 步骤 1: 启动服务端
make run

# 步骤 2: 阶段一 — 上传图片
curl -X POST http://localhost:8080/api/v1/analyze \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"image":"<base64>","user_context":"测试"}' --no-buffer

# 预期 SSE:
#   event:struct (session_state=STRUCTURED)
#   event:card × N (session_state=EXTRACTING)
#   event:done (session_state=READY)

# 步骤 3: 查看 session 状态
curl http://localhost:8080/api/v1/sessions/{session_id}
# 预期: session_state=READY

# 步骤 4: 用户确认/取消
curl -X POST http://localhost:8080/api/v1/actions/{card_id}/confirm \
  -H "Content-Type: application/json" -d '{}'

# 步骤 5: 阶段二 — 生成洞察
curl -X POST http://localhost:8080/api/v1/sessions/{session_id}/insight \
  -H "Accept: text/event-stream" --no-buffer

# 预期 SSE:
#   event:insight (session_state=GENERATING)
#   event:done (session_state=COMPLETED)

# 步骤 6: 查看完整 session
curl http://localhost:8080/api/v1/sessions/{session_id}
# 预期: session_state=COMPLETED, insight 非空
```

---

## 12. 实施顺序总结

| 阶段 | 步骤 | 文件 | 内容 | 是否影响功能 |
|:--:|:--:|------|------|:--:|
| A | 1 | `llm_factory.py` | 加 `get_vision_llm()` / `get_text_llm()` | 否 |
| A | 2 | `tools/structure.py` | 改用 `get_vision_llm()` | 否 |
| A | 3 | `subagents/` | 拆分目录结构，改用 `get_text_llm()` | 否 |
| A | 4 | `deep_agent.py` | Coordinator 改用 `get_text_llm()`，删死代码 | 否* |
| B | 5 | `database.py` | ALTER TABLE 加 `session_state` | 否 |
| B | 6 | `schemas/response.py` | SSE 模型加 `session_state` | 否 |
| B | 7 | `analyze.py` | SSE 事件加 `session_state` | 否 |
| C | 8 | `analyze.py` | 去掉阶段一的 insight 生成 | **是** |
| C | 9 | `actions.py` | 持久化用户决策到 confirmed_actions | **是** |
| C | 10 | `sessions.py` | 新增阶段二 insight 端点 | **是** |
| D | 11 | 清理 | 删除旧 `subagents.py` 等 | 否 |
| D | 12 | 全链路测试 | 6 步 curl 测试 | — |

> *A4 从 VISION_MODEL 改为 LLM_MODEL 做 Coordinator，不影响功能但可能改变行为。需测试验证。
