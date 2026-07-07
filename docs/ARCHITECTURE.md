# Lite Ailoha 架构设计

## 1. 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    iOS Client (SwiftUI)                           │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────────────────┐  │
│  │ 图片选择  │ → │ 客户端压缩    │ → │ POST base64 + SSE 消费   │  │
│  │ 相册/拍照 │   │ max 1024px   │   │                         │  │
│  └──────────┘   └──────────────┘   └─────────────────────────┘  │
│                                              │                    │
│  ┌──────────────┐  ┌──────────────────┐      │                    │
│  │ 结构化对话    │  │ 动作卡片 + 洞察   │  ←──┘                    │
│  │ (可折叠查看)  │  │ 确认/取消 + Toast │                           │
│  └──────────────┘  └──────────────────┘                           │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              Python Server (FastAPI + DeepAgents)                 │
│                                                                   │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ POST analyze    │  │ POST actions/*   │  │ GET sessions/   │  │
│  │ (SSE streaming) │  │                  │  │ {id} (质量评估)  │  │
│  └───────┬─────────┘  └──────────────────┘  └─────────────────┘  │
│          │                                                        │
│          ▼                                                        │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                 Dual-Model Agent Pipeline                   │  │
│  │  VISION_MODEL (Coordinator) → 聊天截图 → 结构化对话 JSON    │  │
│  │  LLM_MODEL (3 Subagents) → 结构化 JSON → action cards      │  │
│  │  SSE: event:struct → event:card × N → event:insight → done │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐  │
│  │ Storage      │  │ analyze_sessions 表 (质量评估)             │  │
│  │ SQLite (WAL) │  │ session_id | structured_conversation      │  │
│  │              │  │ cards (JSON) | insight | created_at        │  │
│  └──────────────┘  └──────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 选择 | 依据 |
|---|---|---|
| 对话理解 | VISION_MODEL 多模态 | 聊天截图是结构化数据，需看图理解对话拓扑 |
| 动作提取 | LLM_MODEL 纯文本 | 子 Agent 处理结构化 JSON，可选更便宜模型 |
| Agent 框架 | DeepAgents | Coordinator + 3 Subagent 分层架构 |
| 通信 | SSE 流式 | struct → card → insight → done，逐事件推送 |
| 存储 | SQLite | 零运维 + analyze_sessions 质量评估回路 |
| 模型配置 | VISION_MODEL / LLM_MODEL 独立 | 支持 OpenAI 兼容 API，国内模型可替换 |
| 代理处理 | httpx.AsyncClient(proxy=None) | 避免 ClashX/V2Ray 等系统代理干扰 LLM API 调用 |
| 图片传递 | 模块级共享变量 | LLM 无法准确复制 42KB+ base64 数据，避免截断导致 1×1 像素 |

## 2. 数据流

```
[iOS] ContentView
  ├── PhotosPicker 或 CameraPicker 选图
  ├── ImageProcessor 压缩 (max 1024px, JPEG 0.7)
  └── AnalysisViewModel.startAnalysis()
        │
        ▼
[iOS] AnalysisService.liveStream()
  ├── Base64 编码图片
  ├── POST http://127.0.0.1:8080/api/v1/analyze
  │     Body: {"image": "<base64>", "user_context": "..."}
  │     Headers: Accept: text/event-stream
  └── SSE 逐行解析 (event: / data:)
        │
        ▼
[Server] api/analyze.py
  ├── [1/7] 接收请求 + 输入验证
  ├── [2/7] 生成 session_id
  └── LiteAilohaAgent.stream_analyze()
        │
        ▼
[Server] agent/deep_agent.py
  ├── [3/8] 初始化 VISION_MODEL + LLM_MODEL (llm_factory.py)
  ├── [4/8] 组装 DeepAgent (Coordinator + 3 Subagents)
  ├── [5/8] 构建多模态提示词 (文本指令 + base64 图片)
  ├── [6/8] 设置共享图片，启动 astream_events 循环
  │     │
  │     ├── Coordinator 调用 structure_conversation
  │     │     └── VISION_MODEL 看图 → {participants, messages}
  │     │         └── → SSE event:struct
  │     │
  │     ├── Coordinator 委派 3 个 Subagent
  │     │     ├── meeting-agent → create_meeting tool
  │     │     ├── contact-agent → create_contact / update_contact tools
  │     │     └── reminder-agent → create_reminder tool
  │     │         └── → SSE event:card × N
  │     │
  │     └── Coordinator 调用 generate_insight
  │           └── → SSE event:insight
  │
  └── [8/8] 完成 → SSE event:done
        │
        ▼
[Server] api/analyze.py
  └── 写入 analyze_sessions 表 (session_id, structured_conversation, cards, insight)
        │
        ▼
[iOS] AnalysisViewModel 消费 AsyncThrowingStream
  ├── .structure(sp) → 更新可折叠结构化对话视图
  ├── .card(card) → 逐张渲染 ActionCardView
  ├── .insight(text) → 显示洞察建议卡片
  └── .done → isAnalyzing = false
```

## 3. 双模型架构

```
  _vision_llm (VISION_MODEL)          _text_llm (LLM_MODEL)
       │                                      │
       ▼                                      ▼
  Coordinator Agent                    子 Agent (Meeting/Contact/Reminder)
  - 看图理解聊天截图                    - 从结构化 JSON 文本中提取信息
  - 调用 structure_conversation         - 不需要 vision 能力
  - 调用 generate_insight               - 可选用更便宜/更快的模型
  - 委派 task() 给子 Agent
```

两个模型通过 `llm_factory.py::create_chat_openai()` 创建，统一传入 `httpx.AsyncClient(proxy=None, trust_env=False)` 禁用系统代理。

### 图片传递：共享变量模式

`structure_conversation` 工具不从 LLM 参数获取 base64 图片数据。原因：Coordinator 是 LLM，当它生成 tool call 参数时，无法准确复制 42KB+ 的 base64 字符串，会截断为几个随机字符，导致视觉模型解析出 1×1 像素的错误。

解决方式：`deep_agent.py` 在启动 Agent 前调用 `set_shared_image(image_base64, user_context)`，将图片存入模块级共享变量。`structure.py` 的 `structure_conversation()` 工具从共享变量读取图片，而非从 LLM 参数获取。

### 配置

两个模型独立配置，支持任意 OpenAI 兼容 API：

```bash
VISION_MODEL=gpt-4o          # Coordinator，需要 vision
VISION_API_KEY=sk-xxxxxxxx
VISION_BASE_URL=https://api.openai.com/v1

LLM_MODEL=gpt-4o             # Subagents，纯文本
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.openai.com/v1
```

`config.py` 设置了 `extra="allow"` 以兼容 `.env` 中的 LangSmith 等额外字段。

## 4. API 契约

### POST /api/v1/analyze

```json
// Request
{
  "image": "<base64 编码的聊天截图>",
  "user_context": "可选补充说明"
}

// Response (SSE)
event:struct
data: {"event":"struct","participants":["张三","李四"],"messages":[...]}

event:card
data: {"event":"card","card":{"id":"create_meeting-abc123","type":"create_meeting","summary":"..."}}

event:insight
data: {"event":"insight","insight":"张三已有2个待定会议..."}

event:done
data: {"event":"done","data":{}}
```

### SSE 解析策略（双层解码）

iOS 客户端 `AnalysisService.emit()` 使用两层策略解析 SSE 数据行：

1. **第一层（主要路径）**：用 `StreamPayload` 通用容器解码，根据 `event` 字段路由到对应 StreamEvent case
2. **第二层（Fallback）**：若第一层失败，根据 SSE `event:` header 直接解码对应类型，用于兼容不同服务端实现

### POST /api/v1/actions/{id}/confirm | cancel

```json
// Request: {"session_id": ""}
// Response: 200 OK
```

### GET /api/v1/sessions/{id}

返回完整会话数据（结构化对话 + 卡片 + 洞察），用于事后对照截图复核质量。

## 5. Card 类型

前后端必须一致的 4 种 canonical 类型：

| Type Key | 中文标签 | SF Symbol (iOS) | 生成者 |
|----------|---------|-----------------|--------|
| `create_meeting` | 创建会议 | `calendar.badge.plus` | Meeting Subagent |
| `create_contact` | 创建联系人 | `person.crop.circle.badge.plus` | Contact Subagent |
| `update_contact` | 更新联系人 | `person.text.rectangle` | Contact Subagent |
| `create_reminder` | 创建提醒 | `bell.badge` | Reminder Subagent |

新增类型需同步更新：`Models.swift` + `schemas/response.py` + `tools/__init__.py` + 所有 prompt 文件。

## 6. 质量评估回路

```
analyze_sessions 表
  ├── session_id (UUID)
  ├── structured_conversation (VISION_MODEL 的原始输出 JSON)
  ├── cards (所有 ActionCard 的 JSON 数组)
  ├── insight (AI 洞察文本)
  └── created_at

GET /api/v1/sessions/{id}  →  对照原始截图评估准确率
```

每次分析完成后自动写入，支持事后质量复核。

## 7. LangSmith 追踪（可选）

通过 `.env` 配置 LangSmith 进行 Agent 链路调试：

```bash
LANGCHAIN_TRACING_V2=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=ls_xxxxxxxx
LANGSMITH_PROJECT=lite-ailoha
```

## 8. 开发命令

```bash
make install          # 创建 venv + 安装依赖
make run              # 启动服务端 (localhost:8080，清除代理变量)
make test             # 运行 pytest
make lint             # ruff 检查
make clean            # 清理临时文件
```
