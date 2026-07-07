import Foundation

// MARK: - 分析结果数据模型

struct StructPayload: Codable, Sendable {
    let event: String
    let participants: [String]
    let messages: [StructMessage]
}

struct StructMessage: Codable, Sendable {
    let time: String
    let speaker: String
    let content: String
}

struct ActionCard: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let type: String
    let summary: String
    var status: CardStatus = .pending

    enum CodingKeys: String, CodingKey { case id, type, summary }
}

enum CardStatus: String, Codable, Sendable {
    case pending, confirmed, cancelled
}

enum StreamEvent: Sendable {
    case structure(StructPayload)
    case card(ActionCard)
    case insight(String)
    case error(ErrorPayload)
    case done
}

struct StreamPayload: Codable, Sendable {
    let event: String
    let card: ActionCard?
    let insight: String?
    let code: String?
    let message: String?
    let participants: [String]?
    let messages: [StructMessage]?
    let data: [String: String]?
}

struct ErrorPayload: Codable, Sendable {
    let code: String
    let message: String
}
