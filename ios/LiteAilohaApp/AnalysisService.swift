import Foundation

// MARK: - 分析服务：SSE 流式请求与 Mock 模拟
///
/// 本文件负责向 AI 后端发送分析请求并解析 SSE 流式响应。
///
/// 架构设计：
/// - 支持两种模式：真实 HTTP + SSE 请求模式 / 本地 Mock 流式模拟模式
/// - 使用 AsyncThrowingStream 实现响应式流式数据传递
/// - 所有异步操作通过 Task.detached 在后台执行，不阻塞主线程
///
/// 并发设计说明：
/// - AnalysisService 标记为 `@unchecked Sendable`，声明其跨 actor 传递安全性
/// - 所有属性通过 `nonisolated` / `nonisolated(unsafe)` 明确退出 MainActor 隔离，
///   避免与项目级 `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` 冲突
/// - URLSession 和 Task.sleep 等耗时操作均在 Task.detached 中执行，
///   不会阻塞 UI 线程

// MARK: - 错误类型

/// 分析过程中可能发生的错误
enum AnalysisError: Error {
    /// 服务端返回了非 200-299 的状态码
    case badResponse
    /// 网络请求失败（携带错误描述文案）
    case network(String)
}

// MARK: - 分析服务

/// AI 分析服务：封装与后端的 SSE 通信，同时提供本地 Mock 能力。
///
/// 使用方式：
/// ```swift
/// let service = AnalysisService()
/// for try await event in service.analyze(imageData: data, text: "补充文字") {
///     switch event {
///     case .card(let card): // 处理动作卡片
///     case .insight(let text): // 处理洞察文本
///     case .done: break // 流结束
///     }
/// }
/// ```
///
/// - Note: 当前默认使用 Mock 模式。要切换到真实后端，将 `useMock` 设为 `false`
///   并更新 `endpoint` 为目标 SSE 地址。
final class AnalysisService: @unchecked Sendable {
    /// 是否使用本地 Mock 流式响应（第一版默认开启）。
    ///
    /// 设为 `false` 后将发起真实的 HTTP POST + SSE 请求。
    ///
    /// - Warning: 使用 `nonisolated(unsafe)` 标记因为 mutable 属性无法使用 `nonisolated`。
    ///   该属性仅在初始化或配置阶段单线程写入，运行时不会并发修改，因此是安全的。
    nonisolated(unsafe) var useMock: Bool = true

    /// 真实后端 SSE 端点地址。
    ///
    /// 替换为你的服务端分析 API 的 SSE endpoint URL。
    nonisolated let endpoint = URL(string: "https://your-backend.example.com/analyze")!

    /// 发起分析请求，通过 AsyncThrowingStream 逐条返回流式事件。
    ///
    /// - Parameters:
    ///   - imageData: 用户截图/照片的原始数据，可为 `nil`
    ///   - text: 用户输入的补充说明文字，可为空字符串
    /// - Returns: 异步抛出流，依次 yield `.card`, `.insight`, `.done` 事件
    nonisolated func analyze(imageData: Data?, text: String) -> AsyncThrowingStream<StreamEvent, Error> {
        if useMock {
            return mockStream(text: text)
        }
        return liveStream(imageData: imageData, text: text)
    }

    // MARK: - 真实 SSE 请求

    /// 向 `endpoint` 发起 POST 请求并通过 SSE 逐行解析流式 JSON。
    ///
    /// 请求体格式：
    /// ```json
    /// {"text": "...", "image": "<base64>"}
    /// ```
    ///
    /// SSE 数据格式约定：
    /// ```
    /// data: {"event":"card","card":{"id":"1","type":"create_meeting","summary":"..."}}
    /// data: {"event":"insight","insight":"您已为张三创建了3个会议..."}
    /// data: [DONE]
    /// ```
    ///
    /// - Note: 使用 `nonisolated` 确保方法不继承项目的全局 MainActor 隔离。
    /// - Note: 内部使用 `Task.detached` 将网络 I/O 移至后台线程，避免阻塞 UI。
    private nonisolated func liveStream(imageData: Data?, text: String) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            // 使用 Task.detached 将整个网络请求和 SSE 解析移至后台线程
            // detached 不继承当前 actor 上下文，避免阻塞 MainActor
            let task = Task.detached {
                do {
                    // 1. 构建 POST 请求
                    let endpoint = self.endpoint
                    var request = URLRequest(url: endpoint)
                    request.httpMethod = "POST"
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

                    // 2. 构造请求体：文字 + 图片 base64
                    let body = [
                        "text": text,
                        "image": imageData?.base64EncodedString() ?? ""
                    ]
                    request.httpBody = try JSONSerialization.data(withJSONObject: body as [String: String])

                    // 3. 发起请求，获取 SSE 字节流
                    let (bytes, response) = try await URLSession.shared.bytes(for: request)

                    // 4. 检查 HTTP 状态码
                    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                        throw AnalysisError.badResponse
                    }

                    // 5. 逐行解析 SSE 数据流
                    // 格式：每一行以 "data:" 开头，后跟 JSON 字符串
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data:") else { continue }
                        // 去掉 "data:" 前缀（5 个字符）并去除首尾空白
                        let json = line.dropFirst(5).trimmingCharacters(in: .whitespaces)

                        // 流结束标记
                        if json == "[DONE]" {
                            continuation.yield(.done)
                            break
                        }

                        // 尝试解码 JSON 并分发事件
                        if let data = json.data(using: .utf8),
                           let payload = try? JSONDecoder().decode(StreamPayload.self, from: data) {
                            self.emit(payload, to: continuation)
                        }
                    }
                    continuation.finish()
                } catch {
                    // 将任意错误包装为 AnalysisError.network 传递给调用方
                    continuation.finish(throwing: AnalysisError.network(error.localizedDescription))
                }
            }
            // 当外部取消 AsyncThrowingStream 的迭代时，取消内部的网络任务
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// 根据 SSE payload 的事件类型，将数据转换为 StreamEvent 并通过 continuation 发送。
    ///
    /// - Parameters:
    ///   - payload: 从 SSE JSON 解码出的原始负载
    ///   - continuation: AsyncThrowingStream 的续体，用于向调用方推送事件
    private nonisolated func emit(_ payload: StreamPayload, to continuation: AsyncThrowingStream<StreamEvent, Error>.Continuation) {
        switch payload.event {
        case "card":
            // 卡片事件：提取 ActionCard 并推送
            if let card = payload.card { continuation.yield(.card(card)) }
        case "insight":
            // 洞察事件：提取文本并推送
            if let insight = payload.insight { continuation.yield(.insight(insight)) }
        case "done":
            // 流结束事件
            continuation.yield(.done)
        default:
            // 未知事件类型：静默忽略
            break
        }
    }

    // MARK: - Mock 流式响应

    /// 本地 Mock 模式：模拟 SSE 流式推送 3 张预设动作卡片和 1 条洞察文本。
    ///
    /// 每条卡片间隔约 0.6 秒推送，模拟真实的流式响应体验。
    /// 推送顺序：卡片 1 → 卡片 2 → 卡片 3 → 洞察 → done
    ///
    /// - Parameter text: 用户补充文字，会被嵌入选中的洞察文本中
    /// - Returns: Mock 异步抛出流
    ///
    /// - Note: 使用 `Task.detached` 确保 `Task.sleep` 不阻塞 MainActor。
    private nonisolated func mockStream(text: String) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task.detached {
                // 预设 3 张模拟卡片，覆盖 create_meeting / add_contact / set_reminder 三种类型
                let cards = [
                    ActionCard(id: UUID().uuidString, type: "create_meeting",
                               summary: "为张三创建会议「产品评审」，时间 周四 15:00"),
                    ActionCard(id: UUID().uuidString, type: "add_contact",
                               summary: "添加联系人：张三（产品经理）"),
                    ActionCard(id: UUID().uuidString, type: "set_reminder",
                               summary: "会前 30 分钟提醒准备演示文稿")
                ]
                do {
                    // 逐张推送卡片，间隔 0.6 秒模拟流式效果
                    for card in cards {
                        try await Task.sleep(nanoseconds: 600_000_000)
                        continuation.yield(.card(card))
                    }
                    // 洞察文本在卡片全部推送后再发送
                    try await Task.sleep(nanoseconds: 600_000_000)
                    let insight = text.isEmpty
                        ? "您已为张三创建了 3 个会议，本次会议主题与上次相似。"
                        : "根据您补充的「\(text)」，已为张三创建了 3 个会议，本次主题与上次相似。"
                    continuation.yield(.insight(insight))
                    // 流结束标记
                    continuation.yield(.done)
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: AnalysisError.network("Mock stream cancelled: \(error.localizedDescription)"))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}