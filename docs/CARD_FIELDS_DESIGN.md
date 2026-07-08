# 卡片结构化数据透传 + 系统 APP 写入优化方案

## 背景

当前 Agent 管道存在两处数据丢失：

1. **SSE 管道丢弃结构化数据**：Tool 返回完整 JSON（含 `title`/`participants`/`datetime`/`phone`/`email` 等），但 `_tool_output_to_card_event()` 只提取 `id` + `type` + `summary` 三个字段发给 iOS
2. **写入系统 APP 时只用 summary**：`DeviceDataProvider.executeAction()` 把 `card.summary` 当作 `title`/`givenName` 直接写入，导致联系人名字变成 "添加联系人：张三（产品经理，138xxxx）"，会议标题变成 "为张三,李四创建会议「产品评审」，时间 周四 15:00"

## 目标

- 整条链路（Tool → SSE → iOS → confirm API → DB）携带结构化 `fields`
- `DeviceDataProvider` 用 `card.fields` 的对应字段写入系统 APP（CNMutableContact / EKEvent / EKReminder），而非把 summary 文本整坨塞进去

## 不改动的内容

- 业务流程不变：确认 → 展示洞察（含执行按钮）→ 点击执行 → 写入系统 APP
- Tool 层：`meeting.py`、`contact.py`、`reminder.py` 返回格式不变
- Prompt 层：`prompts/` 目录下所有子 Agent prompt 不变
- Validator 层：`validators/` 目录下所有 schema 不变
- Subagent 层：`subagents/` 目录下所有配置不变
- iOS `AnalysisViewModel` 确认/取消流程不变
- iOS UI 层（`ActionCardView` 等）暂不改动

---

## 涉及文件与改动

### 1. `server/app/schemas/response.py` — ActionCard 加 `fields`

```python
class ActionCard(BaseModel):
    id: str = Field(description="服务端生成的 UUID")
    type: str = Field(description="动作类型")
    summary: str = Field(description="中文摘要")
    fields: dict = Field(default_factory=dict, description="结构化字段，透传 tool 返回的完整 JSON")
```

### 2. `server/app/agent/deep_agent.py` — SSE 管道透传 `fields`

只改 `_tool_output_to_card_event()` 函数返回值。Tool 返回的 `result` dict 包含 `action`、`status` 等内部字段，需要 strip 掉。同时数组类型字段（如 `participants`）需要 `json.dumps()` 序列化为字符串，保证 Swift 端 `[String: String]` 能解码。

新增 `_clean_fields(card_type, result)` 辅助函数：

```python
import json as _json

_STRIP_KEYS = {"action", "status"}

def _clean_fields(card_type: str, result: dict) -> dict:
    """清理 fields：去掉内部字段，数组值序列化为 JSON 字符串。"""
    cleaned = {}
    for k, v in result.items():
        if k in _STRIP_KEYS:
            continue
        if isinstance(v, list):
            cleaned[k] = _json.dumps(v, ensure_ascii=False)  # ["张三","李四"] → '["张三","李四"]'
        else:
            cleaned[k] = v
    return cleaned
```

`_tool_output_to_card_event()` 改为：

```python
def _tool_output_to_card_event(tool_name: str, output) -> dict | None:
    # ... 前面不变：提取 ToolMessage.content → json.loads → result dict ...
    # ... summary 生成逻辑不变 ...

    return {
        "type": "card",
        "data": {
            "id": f"{card_type}-{hash(summary) & 0x7FFFFFFF:08x}",
            "type": card_type,
            "summary": summary,
            "fields": _clean_fields(card_type, result),  # ← 新增：清理后透传结构化数据
        },
    }
```

### 3. `server/app/schemas/request.py` — ActionRequest 加 `fields`

```python
class ActionRequest(BaseModel):
    session_id: str = Field(default="")
    type: str = Field(default="")
    summary: str = Field(default="")
    fields: dict = Field(default_factory=dict)  # ← 新增
```

### 4. `server/app/storage/database.py` — `confirmed_actions` 表加 `fields` 列

在 `_init_schema()` 中追加 ALTER TABLE（兼容旧库）：

```sql
ALTER TABLE confirmed_actions ADD COLUMN fields TEXT DEFAULT '{}';
```

### 5. `server/app/api/actions.py` — confirm/cancel 写入 `fields`

confirm 和 cancel 两个端点各加一个 `fields` 参数写入 DB。需要在文件顶部新增 `import json`：

```python
import json  # ← 新增

# confirm_action（第 28-31 行改为）：
await db.execute(
    "INSERT OR REPLACE INTO confirmed_actions (id, type, summary, fields, status) VALUES (?, ?, ?, ?, 'confirmed')",
    (action_id, body.type or "", body.summary or "", json.dumps(body.fields, ensure_ascii=False)),
)

# cancel_action（第 50-53 行同理）
```

### 6. `ios/LiteAilohaApp/Models/Models.swift` — ActionCard 加 `fields`

```swift
struct ActionCard: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let type: String
    let summary: String
    let fields: [String: String]  // ← 新增。数组字段已由服务端序列化为 JSON 字符串
    var status: CardStatus = .pending
    var insight: CardInsight? = nil

    enum CodingKeys: String, CodingKey { case id, type, summary, fields }
}
```

> `fields` 值类型说明：Tool 返回的 `participants` 数组在服务端 `_clean_fields()` 里已通过 `json.dumps()` 转为 JSON 字符串（如 `'["张三","李四"]'`），Swift 端用 `[String: String]` 即可统一解码。需要数组时，对对应 key 做一次 `JSONDecoder().decode([String].self, from: Data(f["participants"]!.utf8))`。

### 7. `ios/LiteAilohaApp/Services/AnalysisService.swift` — confirm/cancel 请求体加 `fields`

```swift
// confirmAction（第 133 行）：
r.httpBody = try JSONSerialization.data(withJSONObject: [
    "session_id": "",
    "type": cardType,
    "summary": cardSummary,
    "fields": cardFields,  // ← 新增
])

// cancelAction（第 148 行同理）
```

### 8. `ios/LiteAilohaApp/Services/Persistence.swift` — SavedCard 加 `fields`

Core Data 实体 `SavedCard` 新增 `fields` 属性；`save(_:)` 方法同步写入。

### 9. `ios/LiteAilohaApp/Services/DeviceDataProvider.swift` — 系统 APP 写入映射

`executeAction()` 分派不变，只改三个 private 方法内部的数据来源 —— 从 `card.summary` 改为 `card.fields`。

另外 `update_contact` 从原来跟 `create_contact` 共用分支，拆为独立方法。

---

#### 9.1 `createContact`（`CNMutableContact`）

`fields` 示例：
```json
{
  "name": "张三",
  "phone": "138xxxx",
  "email": "zhangsan@abc.com",
  "company": "ABC科技",
  "title": "产品经理",
  "notes": "在群里认识的"
}
```

映射：

| fields key | CNMutableContact 属性 | 备注 |
|------------|----------------------|------|
| `name` | `givenName` | 直接赋值 |
| `phone` | `phoneNumbers` | 包装为 `[CNLabeledValue<CNPhoneNumber>]`，label 用 `CNLabelPhoneNumberMobile` |
| `email` | `emailAddresses` | 包装为 `[CNLabeledValue<NSString>]`，label 用 `CNLabelWork` |
| `company` | `organizationName` | 直接赋值 |
| `title` | `jobTitle` | 直接赋值 |
| `notes` | `note` | 直接赋值 |

```swift
private func createContact(_ card: ActionCard) async -> Bool {
    let store = CNContactStore()
    let granted = (try? await store.requestAccess(for: .contacts)) ?? false
    guard granted else { return false }

    let f = card.fields
    let contact = CNMutableContact()
    contact.givenName       = f["name"]     ?? ""
    contact.jobTitle        = f["title"]    ?? ""
    contact.organizationName = f["company"] ?? ""
    contact.note            = f["notes"]    ?? ""

    if let phone = f["phone"], !phone.isEmpty {
        contact.phoneNumbers = [CNLabeledValue(
            label: CNLabelPhoneNumberMobile,
            value: CNPhoneNumber(stringValue: phone)
        )]
    }
    if let email = f["email"], !email.isEmpty {
        contact.emailAddresses = [CNLabeledValue(
            label: CNLabelWork,
            value: email as NSString
        )]
    }

    let request = CNSaveRequest()
    request.add(contact, toContainerWithIdentifier: nil)
    do { try store.execute(request); return true }
    catch { print("[DeviceData] ❌ 创建联系人失败: \(error)"); return false }
}
```

---

#### 9.2 `updateContact`（`CNMutableContact`）

从原来 `case "create_contact", "update_contact"` 走同一分支，改为独立方法。

`fields` 示例：
```json
{
  "name": "张三",
  "field": "phone",
  "value": "139xxxx"
}
```

| fields key | 用途 | 备注 |
|------------|------|------|
| `name` | 查询匹配已有联系人 | 用 `CNContact.predicateForContacts(matchingName:)` |
| `field` | 决定更新哪个属性 | `phone`→phoneNumbers, `email`→emailAddresses, `company`→organizationName, `title`→jobTitle, `notes`→note |
| `value` | 写入对应属性的新值 | 需要包装的类型（phone/email）做对应的 CNLabeledValue 包装 |

```swift
private func updateContact(_ card: ActionCard) async -> Bool {
    let store = CNContactStore()
    let granted = (try? await store.requestAccess(for: .contacts)) ?? false
    guard granted else { return false }

    let f = card.fields
    let name = f["name"] ?? ""
    let field = f["field"] ?? ""
    let value = f["value"] ?? ""

    let predicate = CNContact.predicateForContacts(matchingName: name)
    let keys: [CNKeyDescriptor] = [
        CNContactGivenNameKey as CNKeyDescriptor,
        CNContactPhoneNumbersKey as CNKeyDescriptor,
        CNContactEmailAddressesKey as CNKeyDescriptor,
        CNContactOrganizationNameKey as CNKeyDescriptor,
        CNContactJobTitleKey as CNKeyDescriptor,
        CNContactNoteKey as CNKeyDescriptor,
    ]
    guard let match = try? store.unifiedContacts(matching: predicate, keysToFetch: keys).first,
          let mutable = match.mutableCopy() as? CNMutableContact
    else { print("[DeviceData] ❌ 未找到联系人: \(name)"); return false }

    switch field {
    case "phone":    mutable.phoneNumbers  = [CNLabeledValue(label: CNLabelPhoneNumberMobile, value: CNPhoneNumber(stringValue: value))]
    case "email":    mutable.emailAddresses = [CNLabeledValue(label: CNLabelWork, value: value as NSString)]
    case "company":  mutable.organizationName = value
    case "title":    mutable.jobTitle = value
    case "notes":    mutable.note = value
    default: break
    }

    let request = CNSaveRequest()
    request.update(mutable)
    do { try store.execute(request); return true }
    catch { print("[DeviceData] ❌ 更新联系人失败: \(error)"); return false }
}
```

---

#### 9.3 `createReminder`（`EKReminder`）

三个字段全部原生支持，直接映射。

`fields` 示例：
```json
{
  "title": "准备演示文稿",
  "content": "会前准备好演示文稿和会议材料",
  "due_date": "下周一"
}
```

| fields key | EKReminder 属性 | 系统原生 | 备注 |
|------------|----------------|:---:|------|
| `title` | `title` | ✅ | 直接赋值 |
| `content` | `notes` | ✅ | 直接赋值 |
| `due_date` | `dueDateComponents` | ✅ | 自然语言解析为 `DateComponents` |

```swift
private func createReminder(_ card: ActionCard) async -> Bool {
    let store = EKEventStore()
    let granted = (try? await store.requestAccess(to: .reminder)) ?? false
    guard granted else { return false }

    let f = card.fields
    let reminder = EKReminder(eventStore: store)
    reminder.title  = f["title"]   ?? ""
    reminder.notes  = f["content"] ?? ""
    if let due = f["due_date"], !due.isEmpty {
        reminder.dueDateComponents = parseNaturalDueDate(due)
    }
    reminder.calendar = store.defaultCalendarForNewReminders()
    do { try store.save(reminder, commit: true); return true }
    catch { print("[DeviceData] ❌ 创建提醒失败: \(error)"); return false }
}
```

---

#### 9.4 `createEvent`（`EKEvent`）

三个字段原生支持，`participants` 因为 `EKEvent.attendees` 只读，无法编程设置，放入 `notes` 用结构化 Markdown 呈现。

`fields` 示例：
```json
{
  "title": "产品评审",
  "participants": ["张三", "李四"],
  "datetime": "周四 15:00",
  "notes": "讨论新功能方案"
}
```

| fields key | EKEvent 属性 | 系统原生 | 备注 |
|------------|-------------|:---:|------|
| `title` | `title` | ✅ | 直接赋值 |
| `datetime` | `startDate` + `endDate` | ✅ | 自然语言解析为 `Date`，endDate 默认 startDate + 1h |
| `notes` | `notes` | ✅ | 会议备注 |
| `participants` | 写入 `notes` | ❌ 只读 | `attendees` 无法编程写入，改为在 `notes` 中追加 Markdown 列表 |

```swift
private func createEvent(_ card: ActionCard) async -> Bool {
    let store = EKEventStore()
    let granted = (try? await store.requestAccess(to: .event)) ?? false
    guard granted else { return false }

    let f = card.fields
    let event = EKEvent(eventStore: store)
    event.title = f["title"] ?? ""

    if let dt = f["datetime"], !dt.isEmpty {
        let parsed = parseNaturalDateTime(dt)
        event.startDate = parsed.start
        event.endDate   = parsed.end
    } else {
        event.startDate = Date()
        event.endDate   = Date().addingTimeInterval(3600)
    }

    // notes：先写会议备注，再追加参会人（因为 attendees 只读）
    var notesParts: [String] = []
    if let rawNotes = f["notes"], !rawNotes.isEmpty {
        notesParts.append(rawNotes)
    }
    if let p = f["participants"] {
        let ppl = parseParticipants(p)
        if !ppl.isEmpty {
            notesParts.append("- 参会人: \(ppl.joined(separator: "、"))")
        }
    }
    event.notes = notesParts.joined(separator: "\n")

    event.calendar = store.defaultCalendarForNewEvents
    do { try store.save(event, span: .thisEvent); return true }
    catch { print("[DeviceData] ❌ 创建会议失败: \(error)"); return false }
}
```

---

### 字段映射总览

| fields key | create_contact | update_contact | create_meeting | create_reminder |
|------------|:---:|:---:|:---:|:---:|
| `name` | CNContact.givenName | 查询匹配 | — | — |
| `phone` | CNContact.phoneNumbers | ✅ (if field=phone) | — | — |
| `email` | CNContact.emailAddresses | ✅ (if field=email) | — | — |
| `company` | CNContact.organizationName | ✅ (if field=company) | — | — |
| `title` | CNContact.jobTitle | ✅ (if field=title) | EKEvent.title | EKReminder.title |
| `notes` | CNContact.note | ✅ (if field=notes) | EKEvent.notes | — |
| `field` | — | 更新哪个属性 | — | — |
| `value` | — | 新值 | — | — |
| `datetime` | — | — | EKEvent.startDate/endDate | — |
| `participants` | — | — | EKEvent.notes（Markdown） | — |
| `content` | — | — | — | EKReminder.notes |
| `due_date` | — | — | — | EKReminder.dueDateComponents |

---

## 辅助方法（新增）

以下三个辅助方法新增在 `DeviceDataProvider` 中：

```
parseNaturalDateTime(_ text: String) -> (start: Date, end: Date)
    "周四 15:00" → (下周四15:00, 下周四16:00)

parseNaturalDueDate(_ text: String) -> DateComponents
    "下周一" → 下周一 23:59 的 DateComponents

parseParticipants(_ raw: Any) -> [String]
    支持 ["张三","李四"] (JSON array) 或 "张三,李四" (comma string)
```

第一期可用简单规则实现，后续可接入系统 `NSDataDetector` 或让服务端 Agent 返回 ISO 8601。

---

## 验证

```bash
# 1. Server import 检查
cd server && ../.venv/bin/python -c "from app.main import app; print('OK')"

# 2. Server lint 检查
cd server && ../.venv/bin/ruff check app/

# 3. iOS build 检查
SIM_ID=$(xcrun simctl list devices available | grep -m1 Booted | grep -oE '[A-F0-9-]{36}')
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodebuild -project ios/LiteAilohaApp.xcodeproj \
  -scheme LiteAilohaApp \
  -destination "platform=iOS Simulator,id=$SIM_ID" \
  build 2>&1 | grep -E "error:|warning:"
```

---

## 注意事项

- **服务端和 iOS 必须同步上线**：新 SSE card 事件增加了 `fields` 字段，iOS `ActionCard` 的 `CodingKeys` 里已声明 `fields`。旧版本 iOS 收到含 `fields` 的事件会因为 CodingKeys 匹配不上而解码失败。
- **`fields` 可能为空 `{}`**：如果 Agent 返回了非标格式，`_tool_output_to_card_event` 里的 `json.loads` 可能失败返回 `None`（当前行为），此时 `fields` 为空 dict。`DeviceDataProvider` 里所有 `f["key"] ?? ""` 的 fallback 已覆盖此情况。
