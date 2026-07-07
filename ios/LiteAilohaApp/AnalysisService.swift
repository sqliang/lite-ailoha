import Foundation

enum AnalysisError: Error, LocalizedError {
    case badResponse
    case network(String)
    case server(String, String)
    var errorDescription: String? {
        switch self {
        case .badResponse: return "服务端响应异常"
        case .network(let m): return "网络请求失败：\(m)"
        case .server(let c, let m): return "[\(c)] \(m)"
        }
    }
}

final class AnalysisService: @unchecked Sendable {
    nonisolated(unsafe) var useMock: Bool = false
    nonisolated let endpoint = URL(string: "http://127.0.0.1:8080/api/v1/analyze")!

    /// 绕过系统代理的 URLSession — 本地开发直连
    nonisolated private let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.connectionProxyDictionary = [:]
        return URLSession(configuration: c)
    }()

    nonisolated func analyze(imageData: Data?, userContext: String = "") -> AsyncThrowingStream<StreamEvent, Error> {
        useMock ? mockStream(userContext: userContext) : liveStream(imageData: imageData, userContext: userContext)
    }

    nonisolated func confirmAction(cardId: String) async throws {
        guard !useMock else { return }
        let url = endpoint.deletingLastPathComponent().appendingPathComponent("actions").appendingPathComponent(cardId).appendingPathComponent("confirm")
        var r = URLRequest(url: url); r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["session_id": ""])
        let (_, res) = try await self.session.data(for: r)
        guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
    }

    nonisolated func cancelAction(cardId: String) async throws {
        guard !useMock else { return }
        let url = endpoint.deletingLastPathComponent().appendingPathComponent("actions").appendingPathComponent(cardId).appendingPathComponent("cancel")
        var r = URLRequest(url: url); r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["session_id": ""])
        let (_, res) = try await self.session.data(for: r)
        guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
    }

    private nonisolated func liveStream(imageData: Data?, userContext: String) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task.detached {
                do {
                    var req = URLRequest(url: self.endpoint); req.httpMethod = "POST"
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    req.httpBody = try JSONSerialization.data(withJSONObject: [
                        "image": imageData?.base64EncodedString() ?? "",
                        "user_context": userContext,
                    ])
                    let (bytes, res) = try await self.session.bytes(for: req)
                    guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
                    var curEvent: String? = nil
                    for try await line in bytes.lines {
                        if line.hasPrefix("event:") { curEvent = line.dropFirst(6).trimmingCharacters(in: .whitespaces); continue }
                        guard line.hasPrefix("data:") else { continue }
                        self.emit(event: curEvent, data: line.dropFirst(5).trimmingCharacters(in: .whitespaces), to: continuation)
                        curEvent = nil
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: AnalysisError.network(error.localizedDescription)) }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private nonisolated func emit(event: String?, data json: String, to c: AsyncThrowingStream<StreamEvent, Error>.Continuation) {
        if let d = json.data(using: .utf8), let p = try? JSONDecoder().decode(StreamPayload.self, from: d) {
            switch p.event {
            case "struct":
                if let pp = p.participants, let mm = p.messages { c.yield(.structure(StructPayload(event: "struct", participants: pp, messages: mm))); return }
            case "card": if let card = p.card { c.yield(.card(card)); return }
            case "insight": if let ins = p.insight { c.yield(.insight(ins)); return }
            case "error": if let code = p.code, let msg = p.message { c.yield(.error(ErrorPayload(code: code, message: msg))); return }
            case "done": c.yield(.done); return
            default: break
            }
        }
        guard let d = json.data(using: .utf8) else { return }
        switch event {
        case "struct": if let sp = try? JSONDecoder().decode(StructPayload.self, from: d) { c.yield(.structure(sp)) }
        case "card": if let card = try? JSONDecoder().decode(ActionCard.self, from: d) { c.yield(.card(card)) }
        case "insight": if let p = try? JSONDecoder().decode(StreamPayload.self, from: d), let ins = p.insight { c.yield(.insight(ins)) }
        case "error": if let ep = try? JSONDecoder().decode(ErrorPayload.self, from: d) { c.yield(.error(ep)) }
        case "done": c.yield(.done)
        default: break
        }
    }

    private nonisolated func mockStream(userContext: String) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task.detached {
                let cards = [
                    ActionCard(id: UUID().uuidString, type: "create_meeting", summary: "为张三创建会议「产品评审」，时间 周四 15:00"),
                    ActionCard(id: UUID().uuidString, type: "create_contact", summary: "添加联系人：张三（产品经理，138xxxx）"),
                    ActionCard(id: UUID().uuidString, type: "update_contact", summary: "更新联系人「李四」的部门为「产品部」"),
                    ActionCard(id: UUID().uuidString, type: "create_reminder", summary: "会前 30 分钟提醒准备演示文稿"),
                ]
                do {
                    let sp = StructPayload(event: "struct", participants: ["sqliang", "张洪银"], messages: [StructMessage(time: "2026-07-06T15:56:00", speaker: "sqliang", content: "老伙计，收到回复了吗？")])
                    try await Task.sleep(nanoseconds: 400_000_000); continuation.yield(.structure(sp))
                    for card in cards { try await Task.sleep(nanoseconds: 500_000_000); continuation.yield(.card(card)) }
                    try await Task.sleep(nanoseconds: 500_000_000)
                    continuation.yield(.insight("您已为张三创建了 3 个会议，本次会议主题与上次相似。"))
                    continuation.yield(.done); continuation.finish()
                } catch { continuation.finish(throwing: AnalysisError.network("Mock cancelled")) }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
