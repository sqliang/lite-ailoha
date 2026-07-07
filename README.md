# Lite Ailoha

AI 驱动的聊天截图分析工具 — 拍一张聊天截图，自动识别会议、联系人、提醒事项，生成可确认的动作卡片。

## 工作原理

```
  iOS 拍照/选图 → 压缩 → POST base64 → SSE 流式返回
  ┌──────────┐       ┌──────────────────────────────────────┐
  │ 聊天截图  │  →    │  VISION_MODEL 看图 → 结构化对话 JSON   │
  │ + 补充文字 │       │  LLM_MODEL 子Agent → 动作卡片 × N     │
  └──────────┘       │  SSE: struct → card → insight → done │
                     └──────────────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │  iOS 实时渲染 ActionCard 列表 + 确认/取消 + Toast 反馈     │
  └──────────────────────────────────────────────────────────┘
```

### 识别的动作类型

| 类型 | 中文标签 | 示例 |
|------|---------|------|
| `create_meeting` | 创建会议 | "为张三创建会议「产品评审」，时间 周四 15:00" |
| `create_contact` | 创建联系人 | "添加联系人：张三（产品经理，138xxxx）" |
| `update_contact` | 更新联系人 | "更新联系人「李四」的部门为「产品部」" |
| `create_reminder` | 创建提醒 | "会前 30 分钟提醒准备演示文稿" |

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
# 日志实时输出: [1/7] 收到请求 → [2/7] 验证 → ... → [6/7] 持久化
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
│       ├── ContentView.swift       # 主界面
│       ├── AnalysisViewModel.swift # 中央状态机
│       ├── AnalysisService.swift   # HTTP + SSE 解析
│       ├── Models.swift            # 数据模型
│       ├── ActionCardView.swift    # 动作卡片 + Toast
│       ├── Persistence.swift       # Core Data 持久化
│       └── Services/
│           └── ImageProcessor.swift # 图片压缩
├── docs/
│   ├── PRD.md                  # 产品需求文档
│   └── ARCHITECTURE.md         # 架构设计文档
├── CLAUDE.md                   # 开发指南
├── Makefile                    # install/run/test/lint/clean
└── .env.example                # 配置模板
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/analyze` | SSE 流式分析（struct → card × N → insight → done） |
| `POST` | `/api/v1/actions/{id}/confirm` | 确认动作卡片 |
| `POST` | `/api/v1/actions/{id}/cancel` | 取消动作卡片 |
| `GET` | `/api/v1/sessions/{id}` | 查询历史分析结果 |
| `GET` | `/health` | 健康检查 |

### SSE 事件序列

```
event:struct   →  {"participants": [...], "messages": [...]}
event:card     →  {"card": {"id": "...", "type": "create_meeting", "summary": "..."}}
   ... (×N)
event:insight  →  {"insight": "张三已有 2 个待定会议..."}
event:done     →  {}
event:error    →  {"code": "...", "message": "..."} （仅异常时）
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

详细架构设计见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。核心思路：

- **VISION_MODEL**（Coordinator）：看图理解聊天截图，调用 `structure_conversation` 工具输出结构化 JSON
- **LLM_MODEL**（3 个 Subagent）：纯文本推理，从结构化 JSON 中提取会议/联系人/提醒
- **SSE 流式返回**：事件逐个推送，卡片实时渲染
- **质量评估回路**：每次分析写入 `analyze_sessions` 表，可事后对照截图评估准确率

## 更多文档

| 文档 | 内容 |
|------|------|
| [`docs/PRD.md`](docs/PRD.md) | 产品需求与设计 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 架构设计与关键决策 |
| [`server/README.md`](server/README.md) | 服务端详细文档 |
| [`ios/README.md`](ios/README.md) | iOS 客户端详细文档 |
| [`CLAUDE.md`](CLAUDE.md) | 开发指南与规范 |

## License

MIT
