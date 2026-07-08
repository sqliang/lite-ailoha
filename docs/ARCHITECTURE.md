# Lite Ailoha 架构设计

## 1. 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    iOS Client (SwiftUI + MVVM)                    │
│  图片选择/压缩 → SSE 消费 → ActionCard 渲染 → 确认/取消 → 执行     │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTP + SSE
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              Python Server (FastAPI + DeepAgents)                 │
│                                                                   │
│  api/analyze.py          api/actions.py        api/sessions.py   │
│  阶段一 SSE 流              确认/取消/执行         阶段二 洞察      │
│       │                         │                     │           │
│       ▼                         ▼                     ▼           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              LiteAilohaAgent (deep_agent.py)               │  │
│  │  create_deep_agent(                                        │  │
│  │    model = get_text_llm(),       ← Coordinator 大脑        │  │
│  │    tools = STRUCTURE_TOOLS,      ← structure_conversation  │  │
│  │    subagents = get_all_subagents() ← meeting/contact/reminder│ │
│  │  )                                                          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  storage/database.py          schemas/ (Pydantic models)          │
│  SQLite (WAL mode)            request.py / response.py            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Deep Agents 框架

### 2.1 框架选型

项目基于 [DeepAgents](https://github.com/langchain-ai/deepagents)（LangChain 生态中的多 Agent 框架）。核心概念：

| 概念 | 对应代码 | 说明 |
|------|---------|------|
| **Coordinator Agent** | `create_deep_agent(model=...)` 的顶层 agent | 任务规划与分发者，拥有自己的 system_prompt 和 tools |
| **Subagent** | `subagents` 参数传入的 dict 列表 | 领域专家，有独立的 system_prompt 和 tools，被 Coordinator 通过 `task()` 调用 |
| **Tool** | `tools` 参数传入的函数列表 | 可被 Coordinator 或其委派的 Subagent 直接调用的函数 |

**为什么用 DeepAgents 而不是单 Agent？**

单 Agent 模式下，所有 prompt 和 tool 混在一起，LLM 需要同时理解"看图"和"提取会议/联系人/提醒"三个领域，容易遗漏和混淆。DeepAgents 的分层设计让 Coordinator 专注规划分发，每个 Subagent 专注自己的领域，各司其职。

### 2.2 Agent 组装全景

```python
# deep_agent.py — LiteAilohaAgent._ensure_initialized()

self._agent = create_deep_agent(
    model=get_text_llm(),           # ← LLM_MODEL: Coordinator 的大脑
    system_prompt=COORDINATOR_PROMPT,
    tools=STRUCTURE_TOOLS,           # ← [structure_conversation]
    subagents=get_all_subagents(),   # ← [meeting-agent, contact-agent, reminder-agent]
)
```

```
create_deep_agent()
  │
  ├── model: ChatOpenAI(LLM_MODEL)
  │     └─ Coordinator 规划、分发、合成
  │
  ├── system_prompt: COORDINATOR_PROMPT
  │     └─ 告诉 Coordinator：先调 structure_conversation → 再委派三个子Agent → 输出总结
  │
  ├── tools: [structure_conversation]
  │     └─ structure_conversation 内部自己调 get_vision_llm()（VISION_MODEL 看图）
  │        与 Coordinator 模型无关
  │
  └── subagents: [
        {name: "meeting-agent",  description: "...", system_prompt: MEETING_SUBAGENT_PROMPT,
         tools: [create_meeting, query_contacts],     model: get_text_llm()},
        {name: "contact-agent",  description: "...", system_prompt: CONTACT_SUBAGENT_PROMPT,
         tools: [create_contact, update_contact, query_contacts], model: get_text_llm()},
        {name: "reminder-agent", description: "...", system_prompt: REMINDER_SUBAGENT_PROMPT,
         tools: [create_reminder],                    model: get_text_llm()},
      ]
```

**关键点**：
- Coordinator 的 model 和子 Agent 的 model 都是 `get_text_llm()`（同一个 LLM_MODEL 实例）
- `structure_conversation` 虽然是 tool，但它内部调用 `get_vision_llm()`，走 VISION_MODEL
- 子 Agent 的 model 由 `get_all_subagents()` 统一注入：`{**meeting_subagent, "model": llm}`

### 2.3 双模型分工

```
                  ┌─────────────────────────┐
                  │     get_text_llm()       │  LLM_MODEL（DeepSeek / GPT-4o 等）
                  │     纯文本推理模型        │
                  └──────────┬──────────────┘
                             │ 复用于:
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
    Coordinator        meeting-agent       contact-agent
    (规划/分发)         (提取会议)           (提取联系人)
                             │                  │
                             ▼                  ▼
                       reminder-agent      generate_insight
                       (提取提醒)           (洞察建议)


                  ┌─────────────────────────┐
                  │    get_vision_llm()     │  VISION_MODEL（豆包 / GPT-4o 等）
                  │    多模态模型（看图）     │
                  └──────────┬──────────────┘
                             │ 仅用于:
                             ▼
                   structure_conversation tool
                   (截图 → 结构化对话 JSON)
```

**使用边界**：
- `get_text_llm()`：Coordinator + 3 个子 Agent + generate_insight，全部是纯文本推理
- `get_vision_llm()`：**仅在** `structure_conversation` tool 内部，多模态看图

### 2.4 llm_factory 单例管理

`server/app/agent/llm_factory.py` 提供两个模块级单例：

```
llm_factory.py
  │
  ├── _vision_llm ── 惰性初始化，首次调用 get_vision_llm() 时创建
  │     使用者: tools/structure.py → structure_conversation()
  │
  ├── _text_llm ──── 惰性初始化，首次调用 get_text_llm() 时创建
  │     使用者: deep_agent.py (Coordinator)
  │             subagents/ (meeting/contact/reminder)
  │             api/sessions.py (阶段二 洞察)
  │
  └── create_chat_openai() ── 内部工厂，创建时注入 httpx.AsyncClient(proxy=None, trust_env=False)
        原因: 避免 ClashX/V2Ray 等系统代理干扰 LLM API 调用
```

### 2.5 共享图片变量

`structure_conversation` 工具不从 LLM 参数接收 base64 图片数据。原因是：Coordinator 是 LLM，它生成 tool call 参数时无法准确复制 42KB+ 的 base64 字符串，会截断为几个随机字符，导致视觉模型解析出 1×1 像素的错误。

**解决方式**：在进入 Agent 管道前，通过模块级共享变量传递图片：

```python
# deep_agent.py — stream_analyze()
set_shared_image(image_base64, user_context)   # 写入模块变量
async for event in self._agent.astream_events(...):
    ...

# tools/structure.py — structure_conversation()
screenshot_base64 = _shared_image_b64           # 从模块变量读取
```

---

## 3. Coordinator 工作机制

### 3.1 职责与流程

```
Coordinator (LLM_MODEL)
  │
  │  收到用户消息: "请分析这张聊天截图"
  │
  ├─[步骤1] 调用 structure_conversation tool
  │    tool 内部: get_vision_llm().invoke(图片 + Structurer Prompt)
  │    tool 返回: {"participants": [...], "messages": [...]}
  │    → SSE event:struct
  │
  ├─[步骤2] 基于结构化 JSON，并行委派三个子 Agent
  │    task("meeting-agent",  "请从以下结构化对话中提取会议安排\n{JSON}")
  │    task("contact-agent",  "请从以下结构化对话中提取联系人信息\n{JSON}")
  │    task("reminder-agent", "请从以下结构化对话中提取提醒事项\n{JSON}")
  │
  │    每个子 Agent 独立推理:
  │    ┌─ meeting-agent ──────────────────────────┐
  │    │  system_prompt: MEETING_SUBAGENT_PROMPT    │
  │    │  tools: [create_meeting, query_contacts]   │
  │    │  → 若有会议安排，调 create_meeting(tool)    │
  │    │  → tool 返回 JSON → on_tool_end 被拦截     │
  │    │    → SSE event:card                        │
  │    └────────────────────────────────────────────┘
  │    ┌─ contact-agent ──────────────────────────┐
  │    │  system_prompt: CONTACT_SUBAGENT_PROMPT    │
  │    │  tools: [create_contact, update_contact,   │
  │    │           query_contacts]                  │
  │    │  → SSE event:card × N                     │
  │    └────────────────────────────────────────────┘
  │    ┌─ reminder-agent ─────────────────────────┐
  │    │  system_prompt: REMINDER_SUBAGENT_PROMPT   │
  │    │  tools: [create_reminder]                  │
  │    │  → SSE event:card × N                     │
  │    └────────────────────────────────────────────┘
  │
  └─[步骤3] 收集所有子 Agent 结果，输出阶段一总结
       → SSE event:done
```

### 3.2 COORDINATOR_PROMPT 设计

`server/app/agent/prompts/coordinator.py` 中的 `COORDINATOR_PROMPT` 定义了 Coordinator 的行为规范：

- **第一步（强制）**：必须首先调用 `structure_conversation` 工具
- **第二步**：将结构化 JSON 作为输入，并行委派三个子 Agent
- **第三步**：收集结果，输出总结
- **重要规则**：不调用 `generate_insight`（洞察在阶段二独立生成）、每个领域只委派一次、某个领域无内容时子 Agent 返回空结果属正常

---

## 4. 子 Agent 设计

### 4.1 定义结构

每个子 Agent 是一个 dict，结构如下：

```python
# subagents/meeting.py
meeting_subagent = {
    "name": "meeting-agent",           # 唯一标识，Coordinator 用 task("meeting-agent", ...) 调用
    "description": "...",              # 告诉 Coordinator 什么时候该用这个 Agent
    "system_prompt": MEETING_SUBAGENT_PROMPT,  # Agent 的独立思维指令
    "tools": MEETING_TOOLS,            # 该 Agent 可调用的工具集
    # "model" 由 get_all_subagents() 统一注入 get_text_llm()
}
```

**description 的作用**：Coordinator 根据 description 判断什么时候委派哪个子 Agent。这是 DeepAgents 框架的路由机制。

### 4.2 三个子 Agent 对比

| | meeting-agent | contact-agent | reminder-agent |
|---|---|---|---|
| **文件** | `subagents/meeting.py` | `subagents/contact.py` | `subagents/reminder.py` |
| **Prompt** | `MEETING_SUBAGENT_PROMPT` | `CONTACT_SUBAGENT_PROMPT` | `REMINDER_SUBAGENT_PROMPT` |
| **工具** | `create_meeting`, `query_contacts` | `create_contact`, `update_contact`, `query_contacts` | `create_reminder` |
| **输入** | 结构化对话 JSON | 结构化对话 JSON | 结构化对话 JSON |
| **输出** | 调用 tool 产出的 JSON（SSE: card） | 调用 tool 产出的 JSON（SSE: card） | 调用 tool 产出的 JSON（SSE: card） |
| **无结果时** | 返回 "未发现会议安排" | 返回 "未发现联系人相关动作" | 返回 "未发现提醒事项" |

### 4.3 子 Agent 的 LLM 注入

`subagents/__init__.py` — `get_all_subagents()`:

```python
def get_all_subagents() -> list[dict]:
    llm = get_text_llm()                       # 所有子 Agent 共用一个文本 LLM 实例
    return [
        {**meeting_subagent,  "model": llm},   # 展开 dict，注入 model
        {**contact_subagent,  "model": llm},
        {**reminder_subagent, "model": llm},
    ]
```

**为什么不在每个子 Agent 文件里直接调 `get_text_llm()`？** 避免模块 import 时就创建 LLM 实例。`get_text_llm()` 需要网络连通性和 valid API key，若在模块级别调用会导致 import 失败，整个服务无法启动。延迟到 `get_all_subagents()` 被调用时（即首次 `stream_analyze()` 时）才初始化。

---

## 5. Tool 体系

### 5.1 分组逻辑

`tools/__init__.py` 按使用角色将 tool 分为五组：

```
TOOL GROUPS
  │
  ├── STRUCTURE_TOOLS  → Coordinator 专用
  │     [structure_conversation]         ← 看图 → 结构化 JSON
  │
  ├── MEETING_TOOLS    → meeting-agent 专用
  │     [create_meeting, query_contacts] ← 会议提取 + 联系人去重
  │
  ├── CONTACT_TOOLS    → contact-agent 专用
  │     [create_contact, update_contact, query_contacts] ← 联系人管理 + 去重
  │
  ├── REMINDER_TOOLS   → reminder-agent 专用
  │     [create_reminder]                ← 提醒提取
  │
  └── INSIGHT_TOOLS    → Coordinator 阶段二专用
        [generate_insight]               ← 跨域洞察建议
```

### 5.2 各 tool 的 I/O 契约

**structure_conversation**（`tools/structure.py`）:
```
输入: user_context (可选，实际图片从共享变量读取)
内部: get_vision_llm().invoke(图片 + Structurer Prompt)
      → validate_json_output() 校验 + 重试
输出: {"participants": [...], "messages": [{"time","speaker","content"}]}
```

**create_meeting**（`tools/meeting.py`）:
```
输入: title, participants (逗号分隔), datetime, notes
输出: {"action":"create_meeting", "title":"...", "participants":[...], "datetime":"...", "notes":"...", "status":"proposed"}
```

**create_contact**（`tools/contact.py`）:
```
输入: name (必填), phone, email, company, title, notes
输出: {"action":"create_contact", "name":"...", "phone":"...", "email":"...", "company":"...", "title":"...", "notes":"...", "status":"proposed"}
```

**update_contact**（`tools/contact.py`）:
```
输入: name, field (phone/email/company/title/notes), value
输出: {"action":"update_contact", "name":"...", "field":"...", "value":"...", "status":"proposed"}
```

**create_reminder**（`tools/reminder.py`）:
```
输入: content, due_date (可选), title (可选)
输出: {"action":"create_reminder", "title":"...", "content":"...", "due_date":"...", "status":"proposed"}
```

**query_contacts**（`tools/contact.py`）:
```
输入: name (支持部分匹配)
输出: [] （当前 MVP 阶段返回空列表，后续接入 contacts 表）
```

---

## 6. SSE 事件管道

### 6.1 概述

`deep_agent.py` 中的 `stream_analyze()` 调用 LangGraph v2 的 `astream_events()`，输出异步事件流。`_parse_stream_event()` 函数监听 `on_tool_end` 事件，按 tool name 分派为 SSE 事件类型。

```
LangGraph astream_events (v2)
  │  产生: on_chat_model_start, on_chat_model_end, on_tool_start, on_tool_end, ...
  │
  ▼
_parse_stream_event()
  │  过滤: 只关注 on_tool_end 事件
  │
  ├── tool_name == "structure_conversation" ──→ {"type": "struct", "data": {...}}
  │
  ├── tool_name == "create_meeting"         ──→ {"type": "card", "data": {...}}
  ├── tool_name == "create_contact"         ──→ {"type": "card", "data": {...}}
  ├── tool_name == "update_contact"         ──→ {"type": "card", "data": {...}}
  ├── tool_name == "create_reminder"        ──→ {"type": "card", "data": {...}}
  │
  └── tool_name == "generate_insight"       ──→ {"type": "insight", "data": "..."}
```

### 6.2 card 事件处理链路

card 事件经过 4 个函数依次处理，形成完整的处理链：

```
子 Agent 调用 create_meeting(...)
  │  tool 函数返回 JSON 字符串
  ▼
LangGraph on_tool_end 事件
  │  event["name"] = "create_meeting"
  │  event["data"]["output"] = ToolMessage(content=JSON字符串)
  ▼
_parse_stream_event()                         [deep_agent.py:226]
  │  判断: tool_name in _CARD_TOOL_NAMES
  │  调用: _tool_output_to_card_event(tool_name, output)
  ▼
_tool_output_to_card_event()                   [deep_agent.py:327]
  │  1. 提取 ToolMessage.content → json.loads() → result dict
  │  2. summary = _build_summary(card_type, result)  ← 生成中文摘要
  │  3. fields  = _clean_fields(card_type, result)   ← 清理 + 数组序列化
  │  返回: {"type":"card", "data":{"id","type","summary","fields"}}
  ▼
api/analyze.py event_stream()
  │  构造 ActionCard(id, type, summary, fields)
  │  包装为 CardEvent → model_dump_json()
  │  yield {"event": "card", "id": "...", "data": "..."}
  ▼
SSE → iOS
```

### 6.3 _clean_fields() — 字段清理

```python
_STRIP_KEYS = {"action", "status"}       # 内部元数据，不暴露给客户端

def _clean_fields(card_type, result):
    cleaned = {}
    for k, v in result.items():
        if k in _STRIP_KEYS: continue     # 跳过 action/status
        if isinstance(v, list):
            cleaned[k] = json.dumps(v)    # ["张三","李四"] → '["张三","李四"]'
        else:
            cleaned[k] = v
    return cleaned
```

**为什么数组要序列化？** iOS 端 `ActionCard.fields` 类型是 `[String: String]`。`participants` 是 `list`，无法直接赋值给 `String`。服务端预先 `json.dumps()` 可避免 Swift 端处理异构类型。

### 6.4 _build_summary() — 中文摘要生成

根据 `card_type` 用字段值拼中文文案，只用于 iOS 卡片 UI 的摘要展示，不影响系统 APP 写入（系统 APP 用 `fields` 结构化数据）。

```
create_meeting  → "为{participants}创建会议「{title}」，时间 {datetime}"
create_contact  → "添加联系人：{name}（{title or phone}）"
update_contact  → "更新联系人「{name}」的{field}为「{value}」"
create_reminder → "创建提醒：{content}" + ("（截止：{due_date}）" if due_date)
```

### 6.5 SSE 事件 → iOS 模型映射

| SSE event | iOS `StreamEvent` case | 对应模型 |
|-----------|----------------------|---------|
| `struct` | `.structure(StructPayload)` | `participants: [String]` + `messages: [StructMessage]` |
| `card` | `.card(ActionCard)` | `id` + `type` + `summary` + `fields: [String: String]` |
| `insight` | `.insight(String)` | 洞察文本 |
| `error` | `.error(ErrorPayload)` | `code` + `message` |
| `done` | `.done` | 无 |
| `status` | `.state(String)` | session_state 或 step 信息 |
| `meta` | `.state("__sid__...")` | session_id |
| `cancelled` | — | 用户取消分析 |

---

## 7. 数据流（端到端）

```
[iOS] ContentView
  ├── PhotosPicker 或 CameraPicker 选图
  ├── ImageProcessor 压缩 (max 1024px, JPEG 0.7)
  └── AnalysisViewModel.startAnalysis()
        │
        ▼
[iOS] AnalysisService.liveStream()
  ├── Base64 编码图片
  ├── POST /api/v1/analyze  {image: base64, user_context: "..."}
  └── SSE 逐行解析 (event: / data:)
        │
        ▼
[Server] api/analyze.py event_stream()
  ├── [1/7] 提取 image_b64 + user_context
  ├── [2/7] 输入验证（至少一个非空）
  ├── [3/7] 生成 session_id，写 analyze_sessions (PENDING)
  ├── [4/7] 调 LiteAilohaAgent.stream_analyze()
  │     │
  │     ├── [1/4] 懒初始化 Agent（首次请求时创建）
  │     ├── [2/4] 组装 DeepAgent (Coordinator + 3 Subagents + tools)
  │     ├── [3/4] 构建 Coordinator 消息 (纯文本提示词)
  │     ├── [4/4] set_shared_image() → astream_events()
  │     │     │
  │     │     ├── Coordinator 调 structure_conversation
  │     │     │     └── VISION_MODEL 看图 → {participants, messages}
  │     │     │         └→ SSE event:struct
  │     │     │
  │     │     ├── Coordinator 委派 3 个 Subagent（并行）
  │     │     │     ├── meeting-agent  → create_meeting tool
  │     │     │     ├── contact-agent  → create_contact / update_contact tools
  │     │     │     └── reminder-agent → create_reminder tool
  │     │     │         └→ SSE event:card × N  (含 fields)
  │     │     │
  │     │     └── Coordinator 输出总结
  │     │           └→ SSE event:done (session_state=READY)
  │     │
  │     ├── [5/7] 事件分发表 (struct → card → done)
  │     ├── [6/7] 写入 analyze_sessions (structured_conversation + cards JSON)
  │     └── [7/7] 异常捕获 → error 事件
  │
  └── SSE → iOS 客户端
        │
        ▼
[iOS] AnalysisViewModel 消费 AsyncThrowingStream
  ├── .structure(sp) → 展示可折叠对话视图
  ├── .card(card)    → 逐张渲染 ActionCardView
  └── .done          → isAnalyzing = false

┌─ 用户交互 ──────────────────────────────────────────────────────┐
│  确认卡片 → CoreData 持久化 → POST /actions/{id}/confirm        │
│          → 采集设备数据 → POST /sessions/{id}/insight (阶段二)   │
│  执行卡片 → DeviceDataProvider 用 card.fields 写系统 APP         │
└──────────────────────────────────────────────────────────────────┘
```

---

## 8. API 契约

### 8.1 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/analyze` | **阶段一** SSE: meta → status → struct → card × N → done |
| `POST` | `/api/v1/actions/{id}/confirm` | 确认卡片（写 confirmed_actions 表） |
| `POST` | `/api/v1/actions/{id}/cancel` | 取消卡片 |
| `POST` | `/api/v1/actions/{id}/execute` | 标记卡片已执行 |
| `POST` | `/api/v1/sessions/{id}/insight` | **阶段二** SSE: insight → done |
| `GET` | `/api/v1/sessions/{id}` | 查询完整会话 |
| `GET` | `/health` | 健康检查 |

### 8.2 SSE 事件格式

**阶段一** (`POST /api/v1/analyze`):

```
event:meta    → {"session_id": "uuid"}
event:status  → {"step": "structuring", "message": "正在理解聊天内容…"}
event:struct  → {"event":"struct", "session_state":"STRUCTURED",
                 "participants":["张三","李四"], "messages":[...]}
event:status  → {"step": "extracting", "message": "正在识别待办事项…"}
event:card    → {"event":"card", "session_state":"EXTRACTING",
                 "card":{"id":"create_meeting-xxx","type":"create_meeting",
                         "summary":"为张三创建会议...",
                         "fields":{"title":"产品评审","participants":"[\"张三\"]",...}}}
event:done    → {"event":"done", "session_state":"READY", "data":{}}
```

**阶段二** (`POST /api/v1/sessions/{id}/insight`):

```
event:insight → {"event":"insight", "session_state":"GENERATING",
                 "insight":"{\"verdict\":\"approved\", ...}"}
event:done    → {"event":"done", "session_state":"COMPLETED", "data":{}}
```

---

## 9. Card 类型与 fields

### 9.1 Canonical 类型

| Type Key | 中文标签 | 生成者 | fields 包含 |
|----------|---------|--------|------------|
| `create_meeting` | 创建会议 | meeting-agent | `title`, `participants`, `datetime`, `notes` |
| `create_contact` | 创建联系人 | contact-agent | `name`, `phone`, `email`, `company`, `title`, `notes` |
| `update_contact` | 更新联系人 | contact-agent | `name`, `field`, `value` |
| `create_reminder` | 创建提醒 | reminder-agent | `title`, `content`, `due_date` |

### 9.2 fields 结构

`fields` 是 Agent tool 返回的完整结构化数据，经过 `_clean_fields()` 清洗后透传到 iOS。iOS `DeviceDataProvider` 使用 `fields` 精确映射系统 API（CNContact / EKEvent / EKReminder），而非使用 `summary` 文本。详细映射关系见 `docs/CARD_FIELDS_DESIGN.md`。

---

## 10. Session 状态机

```
PENDING → STRUCTURING → STRUCTURED → EXTRACTING → READY
                                                    │
                                              [用户确认卡片]
                                                    │
                                              GENERATING → COMPLETED
```

| 状态 | 含义 | 触发 |
|------|------|------|
| `PENDING` | 会话已创建，等待处理 | 请求到达 |
| `STRUCTURING` | VISION_MODEL 看图中 | 开始调 structure_conversation |
| `STRUCTURED` | 结构化对话完成 | structure_conversation 返回 |
| `EXTRACTING` | 子 Agent 提取中 | 开始委派子 Agent |
| `READY` | 阶段一完成，等待用户交互 | SSE done |
| `GENERATING` | 阶段二洞察中 | POST /sessions/{id}/insight |
| `COMPLETED` | 全流程结束 | 阶段二 SSE done |

---

## 11. 质量评估回路

每次分析完成后自动写入 `analyze_sessions` 表：

```
analyze_sessions
  ├── session_id               — UUID
  ├── session_state             — 状态机当前状态
  ├── structured_conversation   — VISION_MODEL 的原始结构化 JSON
  ├── cards                     — ActionCard 数组（含 fields）
  ├── insight                   — AI 洞察文本
  └── created_at                — 创建时间

GET /api/v1/sessions/{id} → 对照原始截图评估:
  1. VISION_MODEL 结构化准确率（participants + messages 是否正确）
  2. Agent 卡片提取准确率（fields 是否准确）
  3. 洞察建议质量
```

---

## 12. 开发命令

```bash
make install          # 创建 venv + 安装依赖
make run              # 启动服务端 (localhost:8080)
make test             # 运行 pytest
make lint             # ruff 检查
make clean            # 清理临时文件
```
