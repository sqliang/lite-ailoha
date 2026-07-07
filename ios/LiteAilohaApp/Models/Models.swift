import Foundation

// MARK: - 分析结果数据模型
///
/// 本文件定义了客户端与服务端之间所有数据传输对象的 Swift 模型。
///
/// ## 模型分层
/// ```
/// 服务端 JSON（SSE 事件流或 HTTP 响应体）
///   → JSONDecoder 反序列化
///     → Codable 模型（StructPayload, ActionCard, StreamPayload, ErrorPayload）
///       → 业务逻辑枚举（StreamEvent）
///         → SwiftUI @Published 状态（AnalysisViewModel）
/// ```
///
/// ## 模型分类
/// | 类别 | 类型 | 方向 | 用途 |
/// |------|------|------|------|
/// | 结构化数据 | `StructPayload`, `StructMessage` | 服务端 → 客户端 | SSE `event:struct` |
/// | 动作卡片 | `ActionCard`, `CardStatus` | 服务端 → 客户端 + 本地状态 | SSE `event:card` |
/// | SSE 事件流 | `StreamEvent` | 内部 | 统一 SSE 事件枚举 |
/// | SSE 解码容器 | `StreamPayload` | 服务端 → 客户端 | 通用 JSON 解码容器 |
/// | 错误信息 | `ErrorPayload` | 服务端 → 客户端 | SSE `event:error` |
///
/// ## 与服务器模型的对应关系
/// - 服务端 `schemas/response.py` 中的 4 种 canonical 卡片类型
///   （`create_meeting`, `create_contact`, `update_contact`, `create_reminder`）
///   对应 `ActionCard.type` 字段
/// - 卡片类型必须前后端一致，新增类型需同时更新 Models.swift 和 schemas/response.py

// MARK: - 结构化对话模型

/// 结构化对话数据，对应 SSE `event:struct` 事件。
///
/// 由 Vision 模型分析聊天截图后生成，包含参与人列表和消息列表。
///
/// - `Codable`：支持 JSON 反序列化
/// - `Sendable`：支持在 Actor 间安全传递（用于 `@MainActor` ViewModel）
///
/// JSON 示例：
/// ```json
/// {
///   "event": "struct",
///   "participants": ["张三", "李四"],
///   "messages": [
///     {"time": "2026-07-06T15:56:00", "speaker": "张三", "content": "明天开会吗？"},
///     {"time": "2026-07-06T15:57:00", "speaker": "李四", "content": "好的，下午3点"}
///   ]
/// }
/// ```
struct StructPayload: Codable, Sendable {
    /// SSE 事件类型
    let event: String
    /// 会话状态（PENDING → STRUCTURED → ... → COMPLETED）
    var sessionState: String? = nil
    /// 对话参与人的名称列表
    let participants: [String]
    /// 消息列表（按时间升序排列）
    let messages: [StructMessage]

    enum CodingKeys: String, CodingKey {
        case event, participants, messages
        case sessionState = "session_state"
    }
}

/// 结构化对话中的单条消息。
///
/// 由 Vision 模型从聊天截图中逐条提取。
struct StructMessage: Codable, Sendable {
    /// 消息时间戳（ISO 8601 格式字符串，如 "2026-07-06T15:56:00"）
    let time: String
    /// 消息发送者名称
    let speaker: String
    /// 消息正文内容
    let content: String
}

// MARK: - 动作卡片模型

/// 由 AI 分析生成的动作卡片，代表一个可被用户确认或取消的建议操作。
///
/// ## 数据来源与状态
/// - 服务端通过 SSE `event:card` 下发时，仅包含 `id`, `type`, `summary` 三个字段
/// - `status` 是**纯客户端状态**，默认值为 `.pending`，不在 JSON 中传输
/// - 因此 `CodingKeys` 显式排除了 `status`，确保解码时不会因缺少字段而失败
///
/// ## 协议遵循
/// - `Identifiable`：支持 SwiftUI `ForEach` 按 id 区分
/// - `Equatable`：支持 SwiftUI 增量更新（状态变化时精确重绘对应卡片）
/// - `Codable`：支持 JSON 反序列化
/// - `Sendable`：支持 Actor 间安全传递
///
/// ## 卡片类型（4 种 canonical 类型）
/// | type 字符串 | 含义 | 图标 |
/// |------------|------|------|
/// | `create_meeting` | 创建会议 | calendar.badge.plus |
/// | `create_contact` | 创建联系人 | person.crop.circle.badge.plus |
/// | `update_contact` | 更新联系人 | person.text.rectangle |
/// | `create_reminder` | 创建提醒 | bell.badge |
struct ActionCard: Identifiable, Codable, Equatable, Sendable {
    /// 卡片唯一标识（UUID 字符串，由服务端生成）
    let id: String
    /// 动作类型（4 种 canonical 类型之一）
    let type: String
    /// 动作摘要描述（人类可读的中文摘要，如 "为张三创建会议「产品评审」"）
    let summary: String
    /// 卡片确认状态（纯客户端状态，不从 JSON 解码）
    var status: CardStatus = .pending

    /// 显式声明编解码键，排除 `status`（客户端状态不参与序列化）
    enum CodingKeys: String, CodingKey { case id, type, summary }
}

/// 卡片确认状态（纯客户端概念，不传输到服务端）。
///
/// 状态流转：
/// ```
/// pending ──用户确认──→ confirmed
/// pending ──用户取消──→ cancelled
/// ```
///
/// - `pending`：等待用户决策，显示确认/取消按钮
/// - `confirmed`：用户已确认，显示绿色"已确认"徽章
/// - `cancelled`：用户已取消，显示红色"已取消"徽章
enum CardStatus: String, Codable, Sendable {
    case pending, confirmed, cancelled
}

// MARK: - SSE 事件流模型

/// SSE 事件流中所有可能的事件类型。
///
/// 这是客户端内部使用的枚举，统一了 `AsyncThrowingStream` 中传递的所有事件类型。
/// 每个 case 对应一个 SSE `event:` 类型：
///
/// | 枚举 case | SSE event 类型 | 携带数据 | 触发时机 |
/// |-----------|---------------|---------|---------|
/// | `.structure(StructPayload)` | `struct` | 参与人 + 消息列表 | 首个事件，分析开始 |
/// | `.card(ActionCard)` | `card` | 单张动作卡片 | 每个识别到的动作 |
/// | `.insight(String)` | `insight` | 洞察文本 | 所有卡片之后 |
/// | `.error(ErrorPayload)` | `error` | 错误码 + 消息 | 分析异常时 |
/// | `.done` | `done` | 无 | 流正常结束 |
///
/// - `Sendable`：支持在 `Task.detached` 闭包中通过 `AsyncThrowingStream` 传递到 `@MainActor`
enum StreamEvent: Sendable {
    /// 结构化对话数据（首个事件）
    case structure(StructPayload)
    /// 单张动作卡片（可重复多次）
    case card(ActionCard)
    /// AI 洞察/建议文本（单个）
    case insight(String)
    /// 错误事件
    case error(ErrorPayload)
    /// 流结束标记
    case done
}

/// 通用 SSE 数据行解码容器。
///
/// ## 设计原因
/// SSE 协议中每个 `data:` 行的 JSON 结构随 `event:` 类型不同而变化。
/// 例如：
/// - `event:struct` → `{"event":"struct","participants":[...],"messages":[...]}`
/// - `event:card` → `{"event":"card","card":{...}}`
/// - `event:insight` → `{"event":"insight","insight":"..."}`
/// - `event:error` → `{"event":"error","code":"...","message":"..."}`
/// - `event:done` → `{"event":"done"}`
///
/// `StreamPayload` 用**所有可选字段**容纳这些异构结构，
/// 解码后根据 `event` 字段的值分发到对应的 `StreamEvent` case。
///
/// 所有字段均为 Optional 是因为不同事件类型只填充自己的字段，
/// 其余字段在 JSON 中不存在，解码为 nil。
///
/// ## 两层解码策略（见 `AnalysisService.emit()`）：
/// 1. 先尝试用 `StreamPayload` 解码（通用容器 + event 字段分发）
/// 2. 失败时 fallback 到按 SSE `event:` header 直接解码对应类型
struct StreamPayload: Codable, Sendable {
    /// SSE 事件类型（"struct" | "card" | "insight" | "error" | "done"）
    let event: String
    /// `event:card` 时填充：单张动作卡片数据
    let card: ActionCard?
    /// `event:insight` 时填充：洞察文本
    let insight: String?
    /// `event:error` 时填充：错误码
    let code: String?
    /// `event:error` 时填充：错误消息
    let message: String?
    /// `event:struct` 时填充：参与人列表
    let participants: [String]?
    /// `event:struct` 时填充：消息列表
    let messages: [StructMessage]?
    /// 预留字段：键值对形式的额外数据
    let data: [String: String]?
}

// MARK: - 错误模型

/// 服务端错误信息，对应 SSE `event:error` 事件。
///
/// JSON 示例：
/// ```json
/// {"code": "ANALYSIS_FAILED", "message": "图片分析失败：图片质量过低"}
/// ```
struct ErrorPayload: Codable, Sendable {
    /// 错误码（如 "ANALYSIS_FAILED", "INVALID_IMAGE"）
    let code: String
    /// 人类可读的错误描述
    let message: String
}
