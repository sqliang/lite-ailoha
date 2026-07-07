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
| 通信 | SSE 流式 | struct → card → insight → done |
| 存储 | SQLite | 零运维 + analyze_sessions 质量评估 |
| 模型配置 | VISION_MODEL / LLM_MODEL 独立 | 支持 OpenAI 兼容 API，国内模型可替换 |

## 2. API 契约

### POST /api/v1/analyze

```json
// Request: {"image": "<base64>", "user_context": "可选补充"}
// Response SSE: event:struct → event:card × N → event:insight → event:done
```

### GET /api/v1/sessions/{id}

返回完整会话数据（结构化对话 + 卡片 + 洞察），用于事后对照截图复核质量。

## 3. Card 类型

| Type Key | 中文标签 |
|---|---|
| `create_meeting` | 创建会议 |
| `create_contact` | 创建联系人 |
| `update_contact` | 更新联系人 |
| `create_reminder` | 创建提醒 |
