
# Lite Ailoha — 产品需求文档

## 1. 项目描述

Lite Ailoha 是一个基于 iOS Swift 开发的 App，帮助用户通过上传聊天截图，自动识别可执行的行动项（会议、联系人、提醒），生成可确认的动作卡片，并基于上下文提供洞察建议。

## 2. 需求目标

1. 用户上传一张聊天截图，可附带补充文字说明。
2. 系统理解截图中的上下文，识别可执行的行动，生成用户可确认的 **Action Cards**（创建会议、创建联系人、更新联系人、创建提醒）。
3. 用户确认卡片后，系统结合联系人数据与上下文，生成洞察与建议。
4. 支持事后质量评估：每次分析结果持久化存储，可对照原始截图复核准确率。

## 3. 功能拆解

### 3.1 输入

- **聊天截图**：支持相册选择或相机拍摄，JPEG/PNG 格式
- **补充文字**：用户可选，用于提供额外上下文（如参与者身份）

### 3.2 处理管道（两阶段人在回路）

```
阶段一: POST /api/v1/analyze
  聊天截图 + 补充文字
    → iOS ImageProcessor 压缩（max 1024px, JPEG 0.7）
    → POST base64 到服务端
    → VISION_MODEL 看图 → 结构化对话 JSON {participants, messages}
    → LLM_MODEL 子Agent 分析结构化 JSON
      ├── Meeting Agent → 识别会议安排
      ├── Contact Agent → 识别联系人创建/更新
      └── Reminder Agent → 识别提醒事项
    → SSE 流式返回 (struct → card × N → done)
    → 写入 analyze_sessions 表

用户交互: 确认/取消卡片

阶段二: POST /api/v1/sessions/{id}/insight
  用户确认的卡片 + 设备端数据（通讯录/日历/提醒）
    → Agent 生成逐卡片洞察建议
    → SSE: insight → done
```

### 3.3 输出 — Action Cards

4 种 canonical action card 类型：

| 类型 | 中文标签 | 生成条件 |
|------|---------|---------|
| `create_meeting` | 创建会议 | 对话中包含会议时间、参与人、主题 |
| `create_contact` | 创建联系人 | 对话中出现新联系人的姓名、电话等 |
| `update_contact` | 更新联系人 | 对话中提到已有联系人的信息变更 |
| `create_reminder` | 创建提醒 | 对话中包含待办事项、截止时间 |

每张卡片包含唯一 ID、类型、中文摘要、结构化字段（`fields`），用户可确认或取消。

### 3.4 确认后

- 确认的卡片持久化到 Core Data（iOS 端）
- 异步通知服务端 (`POST /api/v1/actions/{id}/confirm`)，携带 `fields` 结构化数据
- 自动触发阶段二洞察请求（结合设备端通讯录/日历/提醒数据）
- 用户点击「执行」按钮 → `DeviceDataProvider` 用 `fields` 映射系统 API 写入通讯录/日历/提醒

## 4. UI 设计

- **主界面**：图片预览区 + 相册/拍照按钮 + 补充文字输入框 + 开始分析按钮
- **分析中**：按钮变灰，显示进度指示器
- **结果区**：
  - 结构化对话（可折叠查看，显示参与人和逐条消息）
  - Action Card 列表（类型图标 + 摘要 + 确认/取消按钮）
  - 洞察建议卡片（灯泡图标 + 建议文本）
- **反馈**：顶部 Toast 浮动提示（成功绿色 / 失败红色，2 秒自动消失）

## 5. Mock 模式

iOS 客户端支持 Mock 模式（`AnalysisService.useMock = true`），无需服务端即可测试完整 UI：

- 返回 4 种 canonical card 类型的模拟数据
- 模拟 400ms-500ms 的 SSE 事件间隔
- 覆盖结构展示、卡片渲染、确认/取消、Toast 反馈全部流程

## 6. 质量评估回路

```
POST /api/v1/analyze → 分析完成
  → INSERT INTO analyze_sessions (session_id, structured_conversation, cards, insight)
  → GET /api/v1/sessions/{id} 可随时查询
  → 对照原始截图，评估 VISION_MODEL 的结构化准确率
  → 对照结构化对话，评估 LLM_MODEL 的卡片提取准确率
```

## 7. 技术选型

| 层 | 技术 | 选型原因 |
|----|------|---------|
| iOS 客户端 | SwiftUI + MVVM + Core Data + CNContactStore + EKEventStore | 原生性能，声明式 UI，本地持久化，系统 APP 集成 |
| 服务端框架 | Python 3.11 + FastAPI | 异步支持，SSE 流式响应 |
| AI 框架 | LangChain + LangGraph + DeepAgents | Coordinator + Subagent 分层架构 |
| 视觉模型 | 多模态 LLM（可配） | GPT-4o / Qwen-VL / GLM-4V / doubao-seed-evolving |
| 文本模型 | 纯文本 LLM（可配） | DeepSeek / Moonshot / GPT-4o |
| 通信协议 | SSE (Server-Sent Events) | 单向流式推送，逐事件实时渲染 |
| 存储 | SQLite (WAL 模式) | 零运维，适合本地开发与测试 |
| 代理处理 | httpx 自定义 transport | 避免系统代理干扰 LLM API 调用 |

## 8. 交付形式

1. iOS Swift App（Xcode 项目）
2. Python FastAPI Server
3. GitHub 仓库（含完整文档）
4. 可运行测试环境（本地 localhost:8080）
