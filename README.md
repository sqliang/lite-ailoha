# Lite Ailoha

AI 驱动的聊天截图分析工具 — 上传聊天截图，自动识别会议、联系人、提醒事项，生成可确认的动作卡片。确认后结合设备端数据生成洞察建议，一键写入系统 APP。

## 工作原理

```
┌─ 阶段一：分析 ──────────────────────────────────────────────────────┐
│                                                                      │
│  iOS 拍照/选图                                                       │
│    │  ImageProcessor 压缩 (max 1024px)                                │
│    │  POST /api/v1/analyze  {image: base64, user_context: "..."}     │
│    ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Coordinator (LLM_MODEL)                                      │   │
│  │    ├─ structure_conversation 工具 ── 内部调 VISION_MODEL 看图  │   │
│  │    │    └→ SSE event:struct   {participants, messages}        │   │
│  │    │                                                           │   │
│  │    ├─ task("meeting-agent")   ┐                                │   │
│  │    ├─ task("contact-agent")   ├─ 并行，用 LLM_MODEL 提取      │   │
│  │    └─ task("reminder-agent")  ┘    └→ SSE event:card × N      │   │
│  │                                       {id, type, summary,      │   │
│  │                                        fields: {结构化数据}}    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│    └→ SSE event:done                                                 │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 用户交互 ──────────────────────────────────────────────────────────┐
│                                                                      │
│  iOS 渲染 ActionCard 列表（类型图标 + 摘要 + 确认/取消按钮）           │
│  用户逐张确认或取消                                                   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─ 阶段二：洞察 + 执行 ────────────────────────────────────────────────┐
│                                                                      │
│  确认卡片后：                                                         │
│    ├─ DeviceDataProvider 读取设备端通讯录/日历/提醒                    │
│    ├─ POST /sessions/{id}/insight  → SSE event:insight               │
│    │    Agent 逐卡片分析冲突、重复、可行性                              │
│    │                                                                  │
│    └─ 用户点击「执行」                                                 │
│         DeviceDataProvider 用 card.fields 结构化字段                   │
│         写入 CNContactStore / EKEventStore / EKReminder               │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```
识别的动作类型

| 类型 | 中文标签 | summary 示例 | fields 包含的结构化字段 |
|------|---------|-------------|----------------------|
| `create_meeting` | 创建会议 | "为张三创建会议「产品评审」，时间 周四 15:00" | `title`, `participants`, `datetime`, `notes` |
| `create_contact` | 创建联系人 | "添加联系人：张三（产品经理，138xxxx）" | `name`, `phone`, `email`, `company`, `title`, `notes` |
| `update_contact` | 更新联系人 | "更新联系人「李四」的部门为「产品部」" | `name`, `field`, `value` |
| `create_reminder` | 创建提醒 | "会前 30 分钟提醒准备演示文稿" | `title`, `content`, `due_date` |

### 架构设计

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


## 快速开始

### 环境要求

- **Server**: Python 3.11+
- **iOS**: Xcode 16+, iOS 18+

### 1. 安装

```bash
git clone git@github.com:sqliang/lite-ailoha.git
cd lite-ailoha
make install          # 创建 venv + 安装依赖
```

### 2. 配置

```bash
cp .env.example .env  # 复制配置模板到 server/ 目录
cp .env.example server/.env
```

编辑 `server/.env`，填入 API Key：

```bash
# Vision 模型（需要多模态，如 GPT-4o / Qwen-VL / GLM-4V / doubao-seed-evolving）
VISION_MODEL=gpt-4o
VISION_API_KEY=sk-xxxxxxxx
VISION_BASE_URL=https://api.openai.com/v1

# LLM 模型（纯文本即可，如 DeepSeek / Moonshot）
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.openai.com/v1
```

> **两个模型可以指向同一个**（如都用 GPT-4o），也可以分开。任何 OpenAI 兼容 API 均可使用。

### 3. 启动服务端

```bash
make run
# Server running at http://localhost:8080
# 日志实时输出: [1/7] 收到请求 → [2/7] 验证 → ... → [7/7] 完成
```

验证：

```bash
curl http://localhost:8080/health
# {"status":"healthy","version":"0.1.0"}
```

### 4. 运行 iOS 客户端

1. 用 Xcode 打开 `ios/LiteAilohaApp.xcodeproj`
2. 选择模拟器，Run
3. Mock 模式（无需服务端）：`AnalysisService.useMock = true`
4. 真机模式：确保 `endpoint` 指向 `http://<your-ip>:8080/api/v1/analyze`

## 项目结构

```
lite-ailoha/
├── server/                     # Python FastAPI 服务端
│   ├── app/
│   │   ├── api/                # 4 个 API 端点 + health
│   │   ├── agent/              # DeepAgents 管道
│   │   │   ├── deep_agent.py   # LiteAilohaAgent（双模型）
│   │   │   ├── llm_factory.py  # ChatOpenAI 工厂 + 单例管理
│   │   │   ├── prompts/        # 系统提示词（一个 Agent 一个文件）
│   │   │   ├── subagents/      # 子Agent 定义（一个领域一个文件）
│   │   │   ├── validators/     # JSON 输出校验 + 重试
│   │   │   └── tools/          # 7 个 tool 函数
│   │   ├── schemas/            # Pydantic 请求/响应模型
│   │   ├── services/           # MVP mock（日历/联系人/洞察）
│   │   └── storage/            # SQLite + LangGraph checkpoint
│   └── README.md               # 服务端详细文档
├── ios/                        # iOS SwiftUI 客户端
│   └── LiteAilohaApp/
│       ├── App/ActionCardsApp.swift         # App 入口
│       ├── Models/Models.swift              # 数据模型 + SSE 事件枚举
│       ├── Services/
│       │   ├── AnalysisService.swift        # HTTP + SSE 解析
│       │   ├── ImageProcessor.swift         # 图片压缩
│       │   ├── Persistence.swift            # Core Data 持久化
│       │   └── DeviceDataProvider.swift     # 系统 APP 写入 + 通讯录/日历读取
│       ├── ViewModels/AnalysisViewModel.swift # 中央状态机
│       └── Views/
│           ├── AnalysisView.swift           # 主界面
│           ├── Cards/ActionCardView.swift   # 动作卡片
│           ├── Status/StatusSection.swift   # 状态指示器
│           ├── Insight/InsightSection.swift # 洞察区域
│           └── Input/InputSection.swift     # 图片选择 + 文字输入
├── docs/
│   ├── PRD.md                    # 产品需求文档
│   ├── ARCHITECTURE.md           # 高层架构设计
│   ├── DESIGN.md                 # 详细架构设计（当前参考）
│   ├── INSIGHT_DESIGN.md         # 阶段二洞察方案设计
│   └── CARD_FIELDS_DESIGN.md     # 卡片结构化字段透传方案
├── CLAUDE.md                   # 开发指南
├── Makefile                    # install/run/test/lint/clean
└── .env.example                # 配置模板
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/analyze` | **阶段一** SSE: meta → status → struct → card × N → done |
| `POST` | `/api/v1/actions/{id}/confirm` | 确认卡片（写入 `confirmed_actions` 表） |
| `POST` | `/api/v1/actions/{id}/cancel` | 取消卡片 |
| `POST` | `/api/v1/actions/{id}/execute` | 标记卡片已执行 |
| `POST` | `/api/v1/sessions/{id}/insight` | **阶段二** SSE: insight → done |
| `GET` | `/api/v1/sessions/{id}` | 查询完整会话（含 session_state） |
| `GET` | `/health` | 健康检查 |

### SSE 事件序列

阶段一（`POST /api/v1/analyze`）：
```
event:meta     →  {"session_id": "uuid"}
event:status   →  {"step": "structuring", "message": "正在理解聊天内容…"}
event:struct   →  {"event": "struct", "session_state": "STRUCTURED", "participants": [...], "messages": [...]}
event:status   →  {"step": "extracting", "message": "正在识别待办事项…"}
event:card     →  {"event": "card", "session_state": "EXTRACTING", "card": {"id": "...", "type": "create_meeting", "summary": "...", "fields": {...}}}
   ... (×N)
event:done     →  {"event": "done", "session_state": "READY"}
```

阶段二（`POST /api/v1/sessions/{id}/insight`）：
```
event:insight  →  {"event": "insight", "session_state": "GENERATING", "insight": "..."}
event:done     →  {"event": "done", "session_state": "COMPLETED"}
```

## 技术栈

| 层 | 技术 |
|----|------|
| iOS 客户端 | SwiftUI, MVVM, Core Data, AsyncThrowingStream (SSE) |
| 服务端 | Python 3.11, FastAPI, sse-starlette, aiosqlite |
| AI 框架 | LangChain, LangGraph, DeepAgents |
| 模型 | 双模型可配（VISION_MODEL + LLM_MODEL），OpenAI 兼容 API |
| 存储 | SQLite (WAL 模式) |

## 架构

详细架构设计见 [`docs/DESIGN.md`](docs/DESIGN.md)。核心思路：

- **Coordinator（LLM_MODEL）**：任务规划与分发，调用 `structure_conversation` 工具和三个子 Agent，合成结果
- **structure_conversation 工具（内部调 VISION_MODEL）**：看图理解聊天截图，输出结构化对话 JSON（参与人 + 消息时间线）
- **3 个 Subagent（LLM_MODEL）**：纯文本领域推理，分别从结构化 JSON 中提取会议/联系人/提醒，输出带 `fields` 结构化字段的动作卡片
- **两阶段人在回路**：阶段一 analyze → 用户确认/取消 → 阶段二 insight + 写入系统 APP
- **SSE 流式返回**：事件逐个推送，卡片实时渲染，带 `session_state` 驱动客户端状态机
- **质量评估回路**：每次分析写入 `analyze_sessions` 表，可事后对照截图评估准确率

## 更多文档

| 文档 | 内容 |
|------|------|
| [`docs/PRD.md`](docs/PRD.md) | 产品需求与设计 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 高层架构设计与关键决策 |
| [`docs/DESIGN.md`](docs/DESIGN.md) | 详细架构设计（当前参考） |
| [`docs/INSIGHT_DESIGN.md`](docs/INSIGHT_DESIGN.md) | 阶段二洞察方案 |
| [`docs/CARD_FIELDS_DESIGN.md`](docs/CARD_FIELDS_DESIGN.md) | 卡片结构化字段透传方案 |
| [`server/README.md`](server/README.md) | 服务端详细文档 |
| [`ios/README.md`](ios/README.md) | iOS 客户端详细文档 |
| [`CLAUDE.md`](CLAUDE.md) | 开发指南与规范 |

## License

MIT
