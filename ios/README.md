# Lite Ailoha iOS 客户端

## 目录结构

```
LiteAilohaApp/
├── ActionCardsApp.swift             # @main 应用入口
├── ContentView.swift                # 主界面（选图、分析、结构化对话、卡片、洞察）
├── ActionCardView.swift             # 动作卡片组件 + Toast 提示
├── CameraPicker.swift               # 系统相机/相册 UIKit 桥接
├── Models.swift                     # 全部数据模型（StructPayload, ActionCard, StreamEvent 等）
├── AnalysisViewModel.swift          # 主 ViewModel（选图 → 发送 → 消费 SSE → 确认/取消）
├── AnalysisService.swift            # SSE 流式 HTTP 客户端 + Mock 模式
├── Persistence.swift                # Core Data 持久化（已确认卡片）
└── Services/
    └── ImageProcessor.swift         # 图片缩放压缩（发送前预处理）
```

## 架构分层

```
┌─────────────────────────────────────────────────────────┐
│  Views (SwiftUI)                                        │
│  ContentView  ActionCardView  CameraPicker  ToastView    │
├─────────────────────────────────────────────────────────┤
│  ViewModel                                              │
│  AnalysisViewModel (@MainActor ObservableObject)         │
│  状态: structure? cards[] insight isAnalyzing toast       │
├─────────────────────────────────────────────────────────┤
│  Services                                               │
│  AnalysisService  ImageProcessor                         │
├─────────────────────────────────────────────────────────┤
│  Models + Persistence                                   │
│  StructPayload  ActionCard  StreamEvent  StreamPayload    │
│  SavedCard (Core Data)                                   │
└─────────────────────────────────────────────────────────┘
```

## 核心流程

### 完整数据流

```
用户选择/拍摄聊天截图
       │
       ▼
ImageProcessor.process() — 压缩至 max 1024px
       │
       ▼
用户点击「开始分析」
       │
       ▼
AnalysisService.analyze(imageData:userContext:)
  POST /api/v1/analyze
  body: {"image":"<base64>","user_context":"..."}
  Accept: text/event-stream
       │
       ▼
SSE 流式消费（按序）:
  1. .structure  → VISION_MODEL 解析的结构化对话
     └─ 可折叠查看 participants + messages 时间线
  2. .card × N   → 动作卡片追加到列表
  3. .insight    → AI 洞察文本
  4. .error      → Toast 提示（不中断流）
  5. .done       → isAnalyzing = false
       │
       ▼
用户确认卡片 → confirm(card)
  ├── 本地状态 → .confirmed
  ├── Core Data 持久化 (SavedCard)
  └── POST /api/v1/actions/{id}/confirm

用户取消卡片 → cancel(card)
  ├── 本地状态 → .cancelled
  └── POST /api/v1/actions/{id}/cancel
```

### Mock 模式 vs 真实模式

| | Mock (useMock=true) | 真实 (useMock=false) |
|---|---|---|
| `analyze()` | 返回 mock struct + 4 张卡片 + insight | POST 到 endpoint，消费 SSE 流 |
| `confirmAction()` | 直接 return | POST /api/v1/actions/{id}/confirm |

## 关键模块

### Models.swift

```
StructPayload       # SSE event:struct — 结构化对话（participants + messages）
StructMessage       # 单条消息（time, speaker, content）
ActionCard          # 动作卡片（id, type, summary, status）
CardStatus          # .pending | .confirmed | .cancelled
StreamEvent         # .structure | .card | .insight | .error | .done
StreamPayload       # SSE data 行的 JSON 解码
ErrorPayload        # SSE error 事件的 code + message
```

四种标准 card type：
| type | 中文 | 图标 |
|---|---|---|
| `create_meeting` | 创建会议 | `calendar.badge.plus` |
| `create_contact` | 创建联系人 | `person.crop.circle.badge.plus` |
| `update_contact` | 更新联系人 | `person.text.rectangle` |
| `create_reminder` | 创建提醒 | `bell.badge` |

### AnalysisService.swift

```swift
func analyze(imageData: Data?, userContext: String = "") -> AsyncThrowingStream<StreamEvent, Error>
func confirmAction(cardId: String) async throws
func cancelAction(cardId: String) async throws
```

SSE 解析同时兼容两种协议格式：标准 SSE（event: + data:）和旧协议（data: 内嵌 event）。

### AnalysisViewModel.swift

```
@Published 状态:
  structure: StructPayload?   # VISION_MODEL 结构化对话
  cards: [ActionCard]         # 动作卡片列表
  insight: String             # AI 洞察
  isAnalyzing: Bool           # 分析进行中
  toastMessage/isSuccess      # Toast
```

## 并发设计

- `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` — 默认 MainActor 隔离
- Service 层 `@unchecked Sendable` + `nonisolated` 退出隔离
- 网络 I/O 在 `Task.detached` 中执行
- SSE 流通过 `continuation.yield()` → `for-await (MainActor)` → `@Published` → SwiftUI
