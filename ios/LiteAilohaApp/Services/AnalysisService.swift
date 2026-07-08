import Foundation

// MARK: - 网络服务层（HTTP 客户端 + SSE 解析 + Mock 支持）
///
/// `AnalysisService` 是客户端的唯一网络出口，负责所有与服务端的 HTTP 通信。
///
/// ## 职责范围
/// - **分析请求**：POST 图片 + 上下文 → SSE 流式响应解析
/// - **操作确认/取消**：POST 卡片 ID → 标准 HTTP 响应
/// - **Mock 模式**：`useMock = true` 时返回模拟数据，无需服务端运行
///
/// ## 三组 API 概览
/// | API | 方法 | 端点 | 输入 | 输出 |
/// |-----|------|------|------|------|
/// | 分析 | `analyze()` | POST `/api/v1/analyze` | 图片 base64 + 用户上下文 | `AsyncThrowingStream<StreamEvent, Error>`（SSE 流） |
/// | 确认 | `confirmAction()` | POST `/api/v1/actions/{id}/confirm` | cardId | 200 OK |
/// | 取消 | `cancelAction()` | POST `/api/v1/actions/{id}/cancel` | cardId | 200 OK |
///
/// ## 线程安全
/// - 使用 `@unchecked Sendable` 标记，因为 `useMock` 以 `nonisolated(unsafe)` 访问
/// - 所有网络请求在 `Task.detached` 中执行，不阻塞主线程
/// - SSE 事件通过 `AsyncThrowingStream` 在 Actor 间安全传递
///
/// ## Mock 模式
/// 设置 `AnalysisService.useMock = true` 可在不启动服务端的情况下
/// 返回 4 种卡片类型的完整 Mock 数据，用于 UI 开发和测试。

// MARK: - 错误类型

/// 分析服务错误类型，实现了 `LocalizedError` 以提供中文错误描述。
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
    /// 是否使用 Mock 模式（不发送网络请求，返回预置模拟数据）。
    /// 使用 `nonisolated(unsafe)` 因为 Swift 6 下 Bool 的 Sendable 检查需要通过此标记绕过。
    nonisolated(unsafe) var useMock: Bool = false

    /// 服务端分析 API 的基础端点。
    /// 其他端点（confirm/cancel）通过 `deletingLastPathComponent()` 从此 URL 推导：
    /// `/api/v1/analyze` → `/api/v1/actions/{id}/confirm`
    nonisolated let endpoint = URL(string: "http://127.0.0.1:8080/api/v1/analyze")!

    /// 绕过系统代理的 URLSession — 本地开发直连 127.0.0.1。
    /// 设置空的 `connectionProxyDictionary` 防止请求走系统 HTTP 代理。
    nonisolated private let session: URLSession = {
        let c = URLSessionConfiguration.default
        c.connectionProxyDictionary = [:]
        return URLSession(configuration: c)
    }()

    nonisolated func executeAction(cardId: String) async throws {
        guard !useMock else { return }
        let url = endpoint.deletingLastPathComponent().appendingPathComponent("actions").appendingPathComponent(cardId).appendingPathComponent("execute")
        var r = URLRequest(url: url); r.httpMethod = "POST"
        print("[AnalysisService] 执行操作 → cardId: \(cardId)")
        let (data, res) = try await self.session.data(for: r)
        if let body = String(data: data, encoding: .utf8) { print("[AnalysisService] ◀︎ 执行响应: \(body)") }
        guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
    }

    /// 阶段二：请求洞察建议
    nonisolated func requestInsight(sessionId: String, cardId: String, cardType: String, cardSummary: String,
                                     deviceContacts: [[String: Any]], deviceEvents: [[String: Any]], deviceReminders: [[String: Any]]) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task.detached {
                do {
                    let url = self.endpoint.deletingLastPathComponent().appendingPathComponent("sessions").appendingPathComponent(sessionId).appendingPathComponent("insight")
                    var req = URLRequest(url: url); req.httpMethod = "POST"
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    let body: [String: Any] = [
                        "card_id": cardId, "card_type": cardType, "card_summary": cardSummary,
                        "device_contacts": deviceContacts, "device_events": deviceEvents, "device_reminders": deviceReminders,
                    ]
                    req.httpBody = try JSONSerialization.data(withJSONObject: body)
                    print("[AnalysisService] 请求洞察 → sessionId=\(sessionId) cardId=\(cardId)")
                    let (bytes, res) = try await self.session.bytes(for: req)
                    guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
                    var curEvent: String? = nil
                    for try await line in bytes.lines {
                        let trimmed = line.trimmingCharacters(in: .whitespaces)
                        if trimmed.hasPrefix("event:") { curEvent = String(trimmed.dropFirst(6)).trimmingCharacters(in: .whitespaces); continue }
                        guard trimmed.hasPrefix("data:") else { continue }
                        let jsonStr = String(trimmed.dropFirst(5)).trimmingCharacters(in: .whitespaces)
                        print("[AnalysisService] ◀︎ insight data: \(jsonStr.prefix(300))")
                        self.emit(event: curEvent, data: jsonStr, to: continuation)
                        curEvent = nil
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: AnalysisError.network(error.localizedDescription)) }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// 分析入口 — 根据 `useMock` 标志分发生成 Mock 数据还是真实网络请求。
    ///
    /// - Parameters:
    ///   - imageData: 待分析的聊天截图原始数据（Mock 模式下忽略）
    ///   - userContext: 用户附加的补充说明文本
    /// - Returns: SSE 事件流的 `AsyncThrowingStream`，调用方用 `for try await` 消费
    nonisolated func analyze(imageData: Data?, userContext: String = "") -> AsyncThrowingStream<StreamEvent, Error> {
        useMock ? mockStream(userContext: userContext) : liveStream(imageData: imageData, userContext: userContext)
    }

    /// 确认操作卡片 — POST /api/v1/actions/{cardId}/confirm
    /// 输入：cardId（操作卡片的唯一 ID）
    /// 请求体：{"session_id": ""}
    /// 响应：标准 HTTP 状态码，200-299 为成功
    nonisolated func confirmAction(cardId: String, cardType: String = "", cardSummary: String = "") async throws {
        guard !useMock else { return }
        let url = endpoint.deletingLastPathComponent().appendingPathComponent("actions").appendingPathComponent(cardId).appendingPathComponent("confirm")
        var r = URLRequest(url: url); r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["session_id": "", "type": cardType, "summary": cardSummary])
        print("[AnalysisService] 确认操作卡片 → cardId: \(cardId) type: \(cardType)")
        let (data, res) = try await self.session.data(for: r)
        if let body = String(data: data, encoding: .utf8) { print("[AnalysisService] ◀︎ 确认响应: \(body)") }
        guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
    }

    /// 取消操作卡片 — POST /api/v1/actions/{cardId}/cancel
    /// 输入：cardId（操作卡片的唯一 ID）
    /// 请求体：{"session_id": ""}
    /// 响应：标准 HTTP 状态码，200-299 为成功
    nonisolated func cancelAction(cardId: String, cardType: String = "", cardSummary: String = "") async throws {
        guard !useMock else { return }
        let url = endpoint.deletingLastPathComponent().appendingPathComponent("actions").appendingPathComponent(cardId).appendingPathComponent("cancel")
        var r = URLRequest(url: url); r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["session_id": "", "type": cardType, "summary": cardSummary])
        print("[AnalysisService] 取消操作卡片 → cardId: \(cardId) type: \(cardType)")
        let (data, res) = try await self.session.data(for: r)
        if let body = String(data: data, encoding: .utf8) { print("[AnalysisService] ◀︎ 取消响应: \(body)") }
        guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
    }

    /// 核心分析请求 — POST /api/v1/analyze
    /// SSE 流式管道：发送图片 + 上下文 → 接收 event:struct → event:card × N → event:insight → event:done
    /// 输入：imageData（原始图片 Data，将被 base64 编码）、userContext（用户附加文本）
    /// 请求体 JSON：{"image": "<base64>", "user_context": "..."}
    /// 响应头：Accept: text/event-stream，用 session.bytes(for:) 逐行读取 SSE 事件
    /// 错误处理：非 2xx 状态码抛 AnalysisError.badResponse，网络异常抛 AnalysisError.network
    private nonisolated func liveStream(imageData: Data?, userContext: String) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task.detached {
                do {
                    // 构造 POST 请求：JSON body + SSE 流式接收
                    var req = URLRequest(url: self.endpoint); req.httpMethod = "POST"
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")   // 请求体为 JSON
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")         // 告知服务器返回 SSE 流
                    // 请求体：image（图片 base64 编码字符串）+ user_context（用户自由文本）
                    let imageBase64 = imageData?.base64EncodedString() ?? ""
                    req.httpBody = try JSONSerialization.data(withJSONObject: [
                        "image": imageBase64,
                        "user_context": userContext,
                    ])
                    // 打印发送的数据概要（不打印完整 base64，避免日志爆炸）
                    let imageSizeKB = Double(imageData?.count ?? 0) / 1024.0
                    print("[AnalysisService] 发送分析请求 → URL: \(self.endpoint.absoluteString), 图片大小: \(String(format: "%.1f", imageSizeKB))KB, base64长度: \(imageBase64.count)字符, userContext: \"\(userContext)\"")
                    // 使用 bytes(for:) 流式读取 SSE 响应，逐行解析 event: / data: 前缀
                    let (bytes, res) = try await self.session.bytes(for: req)
                    guard let http = res as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw AnalysisError.badResponse }
                    var curEvent: String? = nil
                    // SSE 协议解析：event: 行记录事件类型 → data: 行触发 emit() 分发
                    print("[AnalysisService] === SSE 流开始 ===")
                    for try await line in bytes.lines {
                        let trimmed = line.trimmingCharacters(in: .whitespaces)
                        // 打印所有行，包括 ping
                        if trimmed.hasPrefix(":") {
                            print("[AnalysisService] ◀︎ ping")
                        } else if trimmed.hasPrefix("event:") {
                            curEvent = trimmed.dropFirst(6).trimmingCharacters(in: .whitespaces)
                            print("[AnalysisService] ◀︎ event: \(curEvent ?? "(nil)")")
                        } else if trimmed.hasPrefix("data:") {
                            let jsonStr = trimmed.dropFirst(5).trimmingCharacters(in: .whitespaces)
                            print("[AnalysisService] ◀︎ data: \(jsonStr.prefix(300))")
                            // 显式打印 session_state
                            if let d = jsonStr.data(using: .utf8),
                               let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
                               let ss = obj["session_state"] as? String {
                                print("[AnalysisService]    ↳ session_state = \(ss)")
                            }
                            self.emit(event: curEvent, data: jsonStr, to: continuation)
                            curEvent = nil
                        }
                    }
                    print("[AnalysisService] === SSE 流结束 ===")
                    continuation.finish()
                } catch { continuation.finish(throwing: AnalysisError.network(error.localizedDescription)) }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// SSE 数据行解析器 — 将 `data:` 行的 JSON 字符串转换为 `StreamEvent` 枚举值。
    ///
    /// ## 两层解码策略
    /// 1. **第一层（通用容器）**：用 `StreamPayload` 解码，通过 `event` 字段路由到对应 case。
    ///    这是主要路径，覆盖绝大多数 SSE 事件。
    /// 2. **第二层（Fallback）**：若第一层失败，根据 SSE `event:` header 直接解码对应类型。
    ///    用于兼容不同服务端实现的协议差异。
    ///
    /// ## 事件分发表
    /// | SSE event 类型 | 第一层（StreamPayload） | 第二层（Fallback） |
    /// |---------------|------------------------|-------------------|
    /// | `struct` | `p.event == "struct"` + participants + messages | 直接解码 `StructPayload` |
    /// | `card` | `p.event == "card"` + p.card 非空 | 直接解码 `ActionCard` |
    /// | `insight` | `p.event == "insight"` + p.insight 非空 | 解码 `StreamPayload` 取 insight 字段 |
    /// | `error` | `p.event == "error"` + code + message | 直接解码 `ErrorPayload` |
    /// | `done` | `p.event == "done"` | 直接 yield `.done` |
    ///
    /// - Parameters:
    ///   - event: SSE `event:` 行的值（如 "struct", "card"），可能为 nil（某些实现省略 event 行）
    ///   - json: SSE `data:` 行的 JSON 字符串
    ///   - c: `AsyncThrowingStream` 的 continuation，用于向流中 yield 事件
    private nonisolated func emit(event: String?, data json: String, to c: AsyncThrowingStream<StreamEvent, Error>.Continuation) {
        // === 第一层：通用容器解码（主要路径） ===
        if let d = json.data(using: .utf8), let p = try? JSONDecoder().decode(StreamPayload.self, from: d) {
            // meta 事件（data JSON 无 event 字段，需提前处理）
            if let sid = p.sessionId {
                print("[AnalysisService] ✅ 解析→meta | session_id=\(sid)")
                c.yield(.state("__sid__\(sid)"))
                return
            }
            // 每个事件都可能携带 session_state
            if let state = p.sessionState {
                c.yield(.state(state))
            }
            switch p.event {
            case "struct":
                if let pp = p.participants, let mm = p.messages {
                    print("[AnalysisService] ✅ 解析→struct | participants=\(pp.count), messages=\(mm.count)")
                    c.yield(.structure(StructPayload(event: "struct", participants: pp, messages: mm))); return
                }
            case "card": if let card = p.card {
                print("[AnalysisService] ✅ 解析→card | type=\(card.type), summary=\(card.summary.prefix(60))")
                c.yield(.card(card)); return
            }
            case "insight": if let ins = p.insight {
                print("[AnalysisService] ✅ 解析→insight | text=\(ins.prefix(120))")
                c.yield(.insight(ins)); return
            }
            case "error": if let code = p.code, let msg = p.message {
                print("[AnalysisService] ❌ 解析→error | code=\(code), message=\(msg)")
                c.yield(.error(ErrorPayload(code: code, message: msg))); return
            }
            case "done":
                print("[AnalysisService] ✅ 解析→done")
                c.yield(.done); return
            default: break
            }
        }
        // === 第二层：Fallback — 按 SSE event: header 直接解码对应类型 ===
        guard let d = json.data(using: .utf8) else { return }
        switch event {
        case "struct": if let sp = try? JSONDecoder().decode(StructPayload.self, from: d) {
            print("[AnalysisService] ✅ fallback→struct | participants=\(sp.participants.count)")
            c.yield(.structure(sp))
        }
        case "card": if let card = try? JSONDecoder().decode(ActionCard.self, from: d) {
            print("[AnalysisService] ✅ fallback→card | type=\(card.type)")
            c.yield(.card(card))
        }
        case "insight": if let p = try? JSONDecoder().decode(StreamPayload.self, from: d), let ins = p.insight {
            print("[AnalysisService] ✅ fallback→insight | text=\(ins.prefix(120))")
            c.yield(.insight(ins))
        }
        case "error": if let ep = try? JSONDecoder().decode(ErrorPayload.self, from: d) {
            print("[AnalysisService] ❌ fallback→error | code=\(ep.code)")
            c.yield(.error(ep))
        }
        case "done":
            print("[AnalysisService] ✅ fallback→done")
            c.yield(.done)
        default: break
        }
    }

    /// Mock 模式 — 返回预置的模拟 SSE 事件流，无需服务端运行。
    ///
    /// ## 模拟的 SSE 事件序列
    /// 1. `event:struct`（400ms 延迟）→ 结构化对话数据
    /// 2. `event:card` × 4（每张 500ms 延迟）→ 4 种 canonical 卡片类型全覆盖
    /// 3. `event:insight`（500ms 延迟）→ 洞察建议文本
    /// 4. `event:done` → 流结束
    ///
    /// ## 模拟卡片覆盖
    /// | 卡片类型 | 模拟内容 |
    /// |---------|---------|
    /// | `create_meeting` | 为张三创建会议「产品评审」 |
    /// | `create_contact` | 添加联系人：张三（产品经理） |
    /// | `update_contact` | 更新联系人「李四」的部门 |
    /// | `create_reminder` | 会前 30 分钟提醒准备演示文稿 |
    ///
    /// ## 使用方式
    /// ```swift
    /// AnalysisService.useMock = true  // 在 App 启动时设置
    /// ```
    ///
    /// - Parameter userContext: 用户附加的补充说明文本（当前 Mock 模式下未使用，预留）
    /// - Returns: 模拟的 SSE 事件流
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
                    // 构造模拟的结构化对话数据
                    let sp = StructPayload(event: "struct", participants: ["sqliang", "wangru"], messages: [StructMessage(time: "2026-07-06T15:56:00", speaker: "sqliang", content: "哈喽，收到回复了吗？")])
                    // 400ms 模拟网络延迟后发送 struct 事件
                    try await Task.sleep(nanoseconds: 400_000_000); continuation.yield(.structure(sp))
                    // 逐张发送 4 张模拟卡片，每张间隔 500ms 模拟服务端处理延迟
                    for card in cards { try await Task.sleep(nanoseconds: 500_000_000); continuation.yield(.card(card)) }
                    // 500ms 后发送洞察建议
                    try await Task.sleep(nanoseconds: 500_000_000)
                    continuation.yield(.insight("您已为张三创建了 3 个会议，本次会议主题与上次相似。"))
                    continuation.yield(.done); continuation.finish()
                } catch { continuation.finish(throwing: AnalysisError.network("Mock cancelled")) }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
