import Foundation

// MARK: - 分析结果数据模型
///
/// 本文件定义智能截图分析功能所需的所有数据模型：
/// - ActionCard：AI 分析后生成的可执行动作卡片
/// - CardStatus：卡片在 UI 中的生命周期状态
/// - StreamEvent：SSE 流式响应的事件枚举
/// - StreamPayload：服务端 SSE 每行 `data:` 的 JSON 解码结构

// MARK: - 动作卡片

/// 单个动作卡片，表示 AI 从截图/文字中识别出的一个可执行动作。
///
/// 典型动作类型包括：
/// - `create_meeting`：创建会议
/// - `add_contact`：添加联系人
/// - `set_reminder`：设置提醒
///
/// 卡片在 UI 中默认为"待确认"状态，用户可确认或取消。
struct ActionCard: Identifiable, Codable, Equatable, Sendable {
    /// 卡片唯一标识（由服务端生成）
    let id: String
    /// 动作类型，如 "create_meeting" / "add_contact" / "set_reminder"
    let type: String
    /// 动作的摘要描述，如"为张三创建会议「产品评审」，时间 周四 15:00"
    let summary: String
    /// 卡片在当前会话中的确认状态（不从服务端下发，始终从 .pending 开始）
    var status: CardStatus = .pending

    /// 解码键：status 不由服务端下发，仅解码 id/type/summary
    enum CodingKeys: String, CodingKey {
        case id, type, summary
    }
}

// MARK: - 卡片状态

/// 卡片在分析结果列表中的生命周期状态
enum CardStatus: String, Codable, Sendable {
    /// 等待用户确认或取消
    case pending
    /// 用户已确认，已持久化到 Core Data
    case confirmed
    /// 用户已取消，不持久化
    case cancelled
}

// MARK: - SSE 流式事件

/// SSE 流式响应中每一条解析后的事件
///
/// 服务端按顺序推送卡片和洞察文本，最后以 `done` 事件结束：
/// ```
/// data: {"event":"card","card":{...}}
/// data: {"event":"insight","insight":"..."}
/// data: [DONE]
/// ```
enum StreamEvent: Sendable {
    /// 一张动作卡片
    case card(ActionCard)
    /// AI 分析后的洞察/建议文本
    case insight(String)
    /// 流式响应结束标记
    case done
}

// MARK: - SSE 原始负载

/// 服务端每一条 `data:` 行对应的 JSON 结构
///
/// `event` 字段决定如何解析：`"card"` 时取 `card` 字段，`"insight"` 时取 `insight` 字段。
struct StreamPayload: Codable, Sendable {
    /// 事件类型："card" | "insight" | "done"
    let event: String
    /// 卡片数据（event 为 "card" 时有效）
    let card: ActionCard?
    /// 洞察文本（event 为 "insight" 时有效）
    let insight: String?
}