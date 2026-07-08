# 阶段二：确认后洞察生成 — 完整方案设计 (v2)

## 1. 需求

用户确认一张动作卡片后，系统结合服务端数据 + 客户端本地数据，生成针对**这张卡片**的洞察建议，帮助用户做出最终决策。

关键区别：不是一份"总体总结报告"，而是**逐卡片的可执行洞察**。

## 2. 用户视角

用户点击"确认"时，心理模型是"我要采纳这个建议"。系统的工作是：

1. **验证可行性** — 这个操作真的能做吗？（联系人已存在？会议时间冲突？）
2. **给出调整建议** — 如果冲突，怎么调整？（合并、改时间、拆分）
3. **让用户二次确认** — 调整方案需要用户批准

### 三种卡片的洞察场景

| 卡片类型 | 验证项 | 可能的结果 |
|---------|--------|-----------|
| `create_contact` | 是否已有同名/同电话联系人 | 不存在 → 确认创建；已存在 → 无需操作；信息不一致 → 建议合并 |
| `create_meeting` | 是否与已有会议时间冲突；参与人是否存在 | 无冲突 → 确认创建；时间冲突 → 建议改期；参与人信息不全 → 提示补充 |
| `create_reminder` | 是否与已有提醒重复；截止时间是否合理 | 无冲突 → 确认创建；重复提醒 → 建议合并；时间冲突 → 建议调整 |
| `update_contact` | 待更新联系人是否存在 | 存在 → 确认更新；不存在 → 降级为创建 |

## 3. 数据来源

### 服务端数据（已有）

| 数据 | 来源 |
|------|------|
| 结构化对话 | `analyze_sessions` 表 |
| 用户确认/取消记录 | `confirmed_actions` 表 |
| 已有联系人 | `contacts` 表 + mock |
| 已有日历 | `calendar` mock |

### 客户端数据（需上传）— 技术可行性已验证

| 数据 | iOS API | Info.plist Key | 可读写 | 技术风险 |
|------|---------|---------------|:--:|------|
| 系统联系人 | `CNContactStore` | `NSContactsUsageDescription` | 读写 | 无 |
| 系统日历事件 | `EKEventStore` | `NSCalendarsUsageDescription` | 读写 | 无 |
| 系统提醒事项 | `EKEventStore` | `NSRemindersUsageDescription` | 读写 | 无 |

全部三个框架自 iOS 9+ 稳定可用，本项目最低 iOS 18，完全支持。

**权限处理**：用户可拒绝。拒绝时该数据源为空数组上传，Agent 仅基于服务端数据分析。不影响核心流程。 |

### 数据流

```
iOS 确认卡片
  │
  ├── CNContactStore.requestAccess(for: .contacts)
  │     ├── 已授权 → 读取所有联系人 → device_contacts
  │     │   字段：givenName, familyName, phoneNumbers, emailAddresses,
  │     │         organizationName, jobTitle
  │     └── 未授权 → device_contacts = []
  │
  ├── EKEventStore.requestAccess(to: .event)
  │     ├── 已授权 → 读取近30天事件 → device_events
  │     │   字段：title, startDate, endDate, attendees, location, notes
  │     └── 未授权 → device_events = []
  │
  ├── EKEventStore.requestAccess(to: .reminder)
  │     ├── 已授权 → 读取未完成提醒 → device_reminders
  │     │   字段：title, dueDateComponents, priority, notes
  │     └── 未授权 → device_reminders = []
  │
  └── POST /api/v1/sessions/{id}/insight
        Body: {
          card_id: "create_meeting-abc",
          card_type: "create_meeting",
          card_summary: "为张三创建会议...",
          card_fields: {title: "产品评审", participants: "[\"张三\"]", datetime: "周四 15:00"},
          device_contacts: [{name, phones, emails, company, title}, ...],
          device_events: [{title, start, end, attendees, location}, ...],
          device_reminders: [{title, dueDate, priority}, ...],
        }
```

**权限处理**：
- 首次请求权限时 iOS 弹出系统对话框
- 用户拒绝 → 对应数据源为空数组，Agent 仅基于服务端数据分析
- 后续可在设置中重新开启
- 三种权限独立，互不影响

## 4. 服务端 Agent 处理

### 输入

针对**一张**卡片 + 所有上下文：

```
## 当前卡片
类型: create_meeting
摘要: 为张三创建会议「产品评审」，时间 周四 15:00
详情: {title: "产品评审", participants: ["张三"], datetime: "周四 15:00"}

## 结构化对话上下文
{participants: [...], messages: [...]}

## 已有联系人
### 服务端
- 张三 | 产品经理 | 138xxxx | 已有 3 次会面
### 设备端（iOS 通讯录）
- 张三 | 设计师 | 139xxxx
→ 注意：电话不一致！

## 已有日历
### 服务端
- 周四 15:00 | 项目周会
### 设备端（iOS 日历）
- 周四 14:00-16:00 | 客户拜访
→ 注意：时间重叠！

## 其他用户已确认的操作
- [create_reminder] 周二前投简历

请调用 generate_insight 工具，分析这张卡片是否可行，有什么冲突或建议。
```

### 输出格式

```json
{
  "action": "generate_insight",
  "card_id": "create_meeting-abc",
  "verdict": "conflict",
  "conflicts": [
    "张三在通讯录中有两个号码（138xxxx / 139xxxx），建议确认并合并",
    "周四 15:00 与「客户拜访」时间重叠（14:00-16:00）"
  ],
  "suggestion": "建议将会议改到周五 10:00，或联系张三确认是否有空",
  "adjusted_action": {
    "type": "create_meeting",
    "title": "产品评审",
    "participants": ["张三"],
    "datetime": "周五 10:00",
    "notes": "原定周四 15:00，因与客户拜访冲突自动调整"
  },
  "next_steps": [
    "合并张三的重复联系人信息",
    "向张三发送会议邀请"
  ]
}
```

### verdict 枚举

| verdict | 含义 | UI 行为 |
|---------|------|--------|
| `approved` | 无冲突，可直接执行 | 绿色提示 + 执行 |
| `approved_with_note` | 可行但有备注 | 绿色提示 + 展示备注 |
| `conflict` | 有冲突，需调整 | 黄色警告 + 展示调整建议 + 二次确认 |
| `unnecessary` | 无需操作（如联系人已存在） | 灰色提示 + 跳过 |

## 5. iOS 端交互

### 5.1 确认卡片 → 自动请求洞察

```
用户点击 [确认]
  → 卡片状态 → .confirmed
  → StatusSection: "正在分析这张卡片..."
  → POST /sessions/{id}/insight（携带卡片 info + 设备数据）
  → 等待 InsightAgent 返回
```

### 5.2 根据 verdict 展示不同 UI

**approved**：
```
卡片底部展开绿色条：
✅ 可以执行 — 联系人信息完整，无时间冲突
[执行]
```

**conflict**：
```
卡片底部展开黄色条：
⚠️ 发现 2 个问题：
• 周四 15:00 与「客户拜访」时间重叠
• 张三在通讯录中有两个号码
建议：改到周五 10:00
[接受调整] [忽略并继续] [取消]
```

### 5.3 insight 绑定到具体卡片

每张卡片有自己的 insight 状态。`ActionCard` 加字段：

```swift
struct ActionCard {
    let id: String
    let type: String
    let summary: String
    let fields: [String: String]  // 结构化字段（透传 tool 输出）
    var status: CardStatus = .pending
    var insight: CardInsight?     // 这张卡片的洞察
}
```

## 6. 目录结构与数据流

### 6.1 服务端目录结构

新增/修改的文件以 `*` 标注：

```
server/app/
├── api/
│   ├── analyze.py              # * 修改：SSE 开头加 event:meta
│   └── sessions.py             # * 修改：扩展 _build_insight_message，查询 contacts/calendar
├── agent/
│   ├── deep_agent.py           # (不变) LiteAilohaAgent
│   ├── llm_factory.py          # (不变) LLM 单例
│   ├── prompts/                # (不变) 提示词
│   ├── subagents/              # (不变) 子 Agent
│   ├── tools/
│   │   └── insight.py          # * 修改：generate_insight tool 输出调整
│   └── validators/             # (不变) 校验
├── services/
│   ├── contact.py              # * 确认：list_all() 正常工作
│   └── calendar.py             # * 确认：list_upcoming() 正常工作
├── storage/
│   └── database.py             # (不变) SQLite
└── schemas/
    └── response.py             # * 修改：新增 MetaEvent 模型
```

### 6.2 iOS 目录结构

```
ios/LiteAilohaApp/
├── App/
│   └── ActionCardsApp.swift
├── Models/
│   └── Models.swift            # * 修改：StreamPayload +sessionId, ActionCard +insight
├── Services/
│   ├── AnalysisService.swift   # * 修改：提取 SSE 解析，新增 requestInsight()
│   ├── DeviceDataProvider.swift # ★ 新建：CNContactStore + EKEventStore 读取
│   ├── ImageProcessor.swift
│   └── Persistence.swift
├── ViewModels/
│   └── AnalysisViewModel.swift # * 修改：sessionId, requestInsight(), 自动触发
└── Views/
    ├── AnalysisView.swift       # (不变)
    ├── Cards/
    │   └── ActionCardView.swift # * 修改：渲染 card.insight 区域
    ├── Input/
    ├── Status/
    ├── Insight/
    ├── Common/
    └── SessionDetailView.swift
```

### 6.3 数据存取全景

```
┌─ iOS ──────────────────────────────────────────────────┐
│                                                          │
│  DeviceDataProvider (新建)                                │
│  ├── CNContactStore → [DeviceContact]                     │
│  ├── EKEventStore(.event) → [DeviceEvent]                │
│  └── EKEventStore(.reminder) → [DeviceReminder]          │
│                                                          │
│  AnalysisViewModel                                       │
│  ├── confirm(card)                                       │
│  │   ├── 本地状态更新                                     │
│  │   ├── POST /actions/{id}/confirm (fire-and-forget)    │
│  │   └── 调 DeviceDataProvider 采集设备数据               │
│  │       └── AnalysisService.requestInsight()             │
│  │           └── POST /sessions/{id}/insight              │
│  │               Body: { card, device_contacts,           │
│  │                       device_events, device_reminders }│
│  └── 消费 SSE stream → insight 绑定到 card               │
│                                                          │
│  ActionCardView                                          │
│  └── 如果 card.insight != nil → 渲染洞察区域              │
│                                                          │
└──────────────────────┬───────────────────────────────────┘
                       │ POST /sessions/{id}/insight
                       ▼
┌─ Server ────────────────────────────────────────────────┐
│                                                          │
│  api/sessions.py                                         │
│  ├── 接收 card info + device_* 数据                      │
│  ├── 查询 contacts 表 (get_db)                            │
│  ├── 查询 confirmed_actions 表                            │
│  ├── 调用 ContactService.list_all()                      │
│  ├── 调用 CalendarService.list_upcoming()                │
│  ├── _build_insight_message() 组装上下文                  │
│  └── insight_agent.astream_events()                      │
│      └── on_tool_end: generate_insight                    │
│          └── SSE: event:insight                          │
│              data: { verdict, conflicts[], suggestion,   │
│                      adjusted_action?, next_steps[] }     │
│                                                          │
│  services/contact.py                                     │
│  └── ContactService.list_all() → [Contact]               │
│                                                          │
│  services/calendar.py                                    │
│  └── CalendarService.list_upcoming() → [Event]           │
│                                                          │
│  storage/database.py                                     │
│  ├── contacts 表 (已有 mock 数据)                         │
│  ├── confirmed_actions 表 (用户决策)                      │
│  └── analyze_sessions 表 (结构化对话 + cards)             │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 6.4 数据存取职责矩阵

| 组件 | 读 | 写 | 时机 |
|------|:--:|:--:|------|
| `DeviceDataProvider` | CNContactStore, EKEventStore | — | 确认卡片后 |
| `AnalysisViewModel` | `card`, `sessionId` | `card.insight`, `sessionState` | confirm() 全程 |
| `AnalysisService.requestInsight()` | — | HTTP POST + SSE 消费 | confirm() 后自动 |
| `api/sessions.py` | contacts 表, confirmed_actions, calendar mock | analyze_sessions.insight | 收到 iOS 请求 |
| `ContactService` | contacts 表 (mock) | — | sessions.py 组装上下文 |
| `CalendarService` | 内存 (mock 事件) | — | sessions.py 组装上下文 |
| `_build_insight_message()` | 所有上下文数据 | — | 组装 Agent 消息 |
| `insight_agent` | 组装好的消息 | SSE stream | astream_events |

## 7. 变更清单

| 文件 | 变更 |
|------|------|
| `Info.plist` | 加 3 个权限描述 key |
| `server/app/api/analyze.py` | SSE 开头 yield `event:meta` |
| `server/app/api/sessions.py` | 扩展 `_build_insight_message`；加 contacts/calendar 查询 |
| `ios/.../Models/Models.swift` | `StreamPayload` 加 `sessionId`；`ActionCard` 加 `insight` |
| `ios/.../Services/AnalysisService.swift` | 提取 SSE 解析；新增 `requestInsight()` |
| `ios/.../Services/DeviceDataProvider.swift` | **新建**：读取 CNContactStore / EKEventStore |
| `ios/.../ViewModels/AnalysisViewModel.swift` | 存 sessionId；confirm 后采集设备数据 + 自动触发 insight |
| `ios/.../Views/Cards/ActionCardView.swift` | 根据 verdict 渲染每张卡片的洞察区域 |

## 8. 实施计划

> 分 4 个阶段，每阶段完成后可独立验证。优先打通数据流，再优化 UI。

### 阶段 1：session_id 传递（前后端）

| 步骤 | 文件 | 内容 | 验证 |
|:--:|------|------|------|
| 1.1 | `server/app/api/analyze.py` | SSE 流第一个事件 yield `event:meta {"session_id":"..."}` | curl 看第一条 event |
| 1.2 | `ios/.../Models/Models.swift` | `StreamPayload` 加 `sessionId: String?` + CodingKey | 编译通过 |
| 1.3 | `ios/.../Services/AnalysisService.swift` | `emit()` 加 `case "meta"` 解析 sessionId → yield `.state(id)` 或新增 `.meta(String)` | 控制台打印 session_id |
| 1.4 | `ios/.../ViewModels/AnalysisViewModel.swift` | 新增 `sessionId: String?`，收到 meta 后赋值 | 控制台确认 sessionId 已存储 |

**验证点**：发起一次分析，Xcode 控制台看到 `session_id = abc-123` 日志。

### 阶段 2：设备端数据采集（仅 iOS）

| 步骤 | 文件 | 内容 | 验证 |
|:--:|------|------|------|
| 2.1 | `Info.plist` | 加 `NSContactsUsageDescription`、`NSCalendarsUsageDescription`、`NSRemindersUsageDescription` | 编译通过 |
| 2.2 | `ios/.../Services/DeviceDataProvider.swift` | **新建**：`requestContacts()`、`requestEvents()`、`requestReminders()`，每个方法处理权限 | 模拟器运行，打印采集条数 |
| 2.3 | `ios/.../ViewModels/AnalysisViewModel.swift` | `confirm()` 中调 `DeviceDataProvider`，将结果暂存到局部变量（暂不发请求） | 确认卡片后控制台打印采集数据 |

**验证点**：确认一张卡片 → 控制台打印采集到的设备联系人/日历/提醒数量。权限弹窗正常弹出。

### 阶段 3：阶段二服务端 + iOS 通信

| 步骤 | 文件 | 内容 | 验证 |
|:--:|------|------|------|
| 3.1 | `server/app/services/calendar.py` | 确认 `list_upcoming()` 返回 mock 事件 | curl 调 sessions 端点的 insight 部分 |
| 3.2 | `server/app/api/sessions.py` | `_build_insight_message` 加 contacts/calendar 参数；`generate_insight` 端点查询 contacts+calendar 表 | 用 curl 调 `/sessions/{id}/insight`，检查 SSE 返回 |
| 3.3 | `ios/.../Services/AnalysisService.swift` | 新增 `requestInsight(sessionId:card:deviceData:)`，POST 携带卡片 + 设备数据 | 控制台看请求体 |
| 3.4 | `ios/.../ViewModels/AnalysisViewModel.swift` | `confirm()` 后自动调 `requestInsight()`；防重复（`insightRequested` 标记改为 `Set<String>` 按 cardId 追踪）；消费 SSE 更新 `card.insight` | 确认卡片 → 控制台看到 insight SSE 返回 |
| 3.5 | `ios/.../Models/Models.swift` | `ActionCard` 加 `var insight: CardInsight?`，`CardInsight` 模型含 `verdict/conflicts/suggestion/adjustedAction/nextSteps` | 编译通过 |

**验证点**：确认卡片 → 控制台看到 `verdict=approved, suggestion=...`。可以用 curl 先调阶段二，确认服务端返回格式正确。

### 阶段 4：UI 渲染

| 步骤 | 文件 | 内容 | 验证 |
|:--:|------|------|------|
| 4.1 | `ios/.../Views/Cards/ActionCardView.swift` | 卡片底部加 insight 区域：`approved` → 绿色条；`conflict` → 黄色条 + 按钮；`unnecessary` → 灰色条 | 确认卡片后卡片展开洞察 |
| 4.2 | `ios/.../Views/Status/StatusSection.swift` | `GENERATING` 状态时步骤3 变蓝 | 确认卡片后步骤3 暂时变蓝 |

**验证点**：确认第一张卡片 → 卡片底部长出绿色/黄色洞察条。确认第二张 → 第一张洞察还在，第二张独立渲染。

### 阶段 5：全链路端到端验证

```bash
make run                 # 启动服务端
make test-e2e            # 跑现有 e2e（确认不回归）
```

手动测试：
1. 用 iOS 发送分析 → 收到 3 张卡片
2. 确认第 1 张（create_reminder）→ 卡片展开绿色洞察 ✅ 可执行
3. 确认第 2 张（create_contact）→ 卡片展开黄色洞察 ⚠️ 联系人已存在
4. 确认第 3 张（create_meeting）→ 卡片展开黄色洞察 ⚠️ 时间冲突
5. 每张卡片洞察独立，不互相覆盖

## 9. 验证（完整流程）

```
1. make run 启动服务端
2. iOS 分析 → 收到 struct + 3 cards
3. 确认第 1 张 → Xcode 控制台：session_id + 设备数据 + insight SSE
4. 确认第 2 张 → 同上，独立的 insight
5. 确认第 3 张 → 同上
6. 每张卡片下方渲染独立的洞察区域，verdict 不同颜色
7. make test-e2e 全链路测试通过
```
