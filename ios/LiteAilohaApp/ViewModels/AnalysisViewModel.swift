import SwiftUI
import CoreData
import Combine

// MARK: - 分析视图模型（MVVM 中央状态机）
///
/// `AnalysisViewModel` 是客户端架构中的核心调度器，连接 UI 层与网络层。
///
/// ## 架构角色
/// - 持有 `AnalysisService`（网络层）和 Core Data `viewContext`（持久化层）
/// - 通过 `@Published` 属性驱动 SwiftUI 视图更新
/// - 所有状态变更都在 `@MainActor` 上执行，确保线程安全
///
/// ## 数据流
/// ```
/// 用户点击「开始分析」
///   → startAnalysis(imageData:userContext:)
///     → service.analyze() 返回 AsyncThrowingStream<StreamEvent, Error>
///       → for-await 逐事件消费：
///         event:struct  → structure = sp       (展示结构化对话)
///         event:card    → cards.append(card)    (逐张展示动作卡片)
///         event:insight → insight = text        (展示洞察建议)
///         event:error   → showToast(error)      (错误提示)
///         event:done    → isAnalyzing = false   (结束加载态)
///       → 异常捕获 → showToast(失败信息)
/// ```
///
/// ## 确认/取消流程（双写模式）
/// ```
/// 用户点击确认
///   → confirm(card)
///     → updateStatus(card, .confirmed)   // 1. 立即更新本地状态（UI 即时反馈）
///     → save(card)                       // 2. 持久化到 Core Data
///     → service.confirmAction(cardId)    // 3. 异步通知服务器（fire-and-forget）
///     → showToast(成功提示)              // 4. 用户反馈
/// ```

@MainActor
final class AnalysisViewModel: ObservableObject {

    // MARK: - 发布属性（驱动 UI 更新）

    /// 分析得出的动作卡片列表。
    /// 每收到一个 SSE `event:card` 事件就追加一张卡片。
    /// 卡片状态（pending/confirmed/cancelled）由用户交互驱动变更。
    @Published var cards: [ActionCard] = []

    /// 分析得出的洞察/建议文本。
    /// 由 SSE `event:insight` 事件写入，显示在结果列表底部。
    @Published var insight: String = ""

    /// 是否正在进行网络分析。
    /// - `true`：显示加载指示器，禁用「开始分析」按钮
    /// - `false`：恢复正常 UI
    @Published var isAnalyzing = false

    /// 结构化对话数据（参与人 + 消息列表）。
    /// 由 SSE `event:struct` 事件写入，用于展示可展开的对话详情。
    @Published var structure: StructPayload?

    /// 是否有可展示的结构化对话数据。
    var hasStructure: Bool { structure != nil && !(structure?.messages.isEmpty ?? true) }

    /// 当前会话状态（PENDING → STRUCTURING → ... → COMPLETED）。
    /// 由 SSE 事件的 session_state 字段更新，驱动 StatusSection 展示。
    @Published var sessionState: String?

    /// 服务端会话 ID，用于阶段二请求洞察
    var sessionId: String?

    /// Toast 浮动提示消息文本。
    /// 非 nil 时显示 Toast，nil 时隐藏。
    @Published var toastMessage: String?

    /// Toast 的视觉样式：
    /// - `true`：绿色成功样式（对勾图标）
    /// - `false`：红色失败样式（警告图标）
    @Published var toastIsSuccess = true

    // MARK: - 依赖

    /// 网络服务层（HTTP 请求 + SSE 流解析）
    private let service = AnalysisService()

    /// Core Data 托管上下文（用于持久化已确认的卡片）
    private let context = PersistenceController.shared.container.viewContext

    /// 当前分析任务（用于取消）
    private var currentTask: Task<Void, Never>?

    // MARK: - 分析方法

    /// 启动图片分析流程，通过 SSE 流式接收 AI 分析结果。
    ///
    /// 调用前会重置所有状态（cards、insight、structure），
    /// 然后通过 `service.analyze()` 获取 SSE 事件流并逐个消费。
    ///
    /// - Parameters:
    ///   - imageData: 待分析的聊天截图原始数据（可选，Mock 模式下可不传）
    ///   - userContext: 用户附加的补充说明文本
    ///
    /// - 消费的 SSE 事件序列：
    ///   1. `event:struct` → 写入 `structure`（结构化对话）
    ///   2. `event:card` × N → 逐个追加到 `cards`
    ///   3. `event:insight` → 写入 `insight`
    ///   4. `event:error` → 弹出错误提示
    ///   5. `event:done` → 流结束
    ///
    /// - 异常处理：流中任何网络错误会触发 catch 分支，显示失败 Toast
    func startAnalysis(imageData: Data?, userContext: String = "") {
        // 取消旧任务
        currentTask?.cancel()
        // 重置所有分析状态，确保新分析不受旧数据影响
        cards = []; insight = ""; structure = nil; sessionState = nil; sessionId = nil; insightRequestedCards = []; isAnalyzing = true
        currentTask = Task {
            do {
                // 逐事件消费 SSE 流，每个事件驱动一次 UI 更新
                for try await event in service.analyze(imageData: imageData, userContext: userContext) {
                    switch event {
                    case .structure(let sp): structure = sp; if let s = sp.sessionState { sessionState = s }
                    case .card(let card): cards.append(card)
                    case .insight(let text): insight = text
                    case .error(let p): showToast(p.message, success: false)
                    case .done: break
                    case .state(let s):
                        if s.hasPrefix("__sid__") { sessionId = String(s.dropFirst(7)) }
                        else { sessionState = s }
                    }
                }
                isAnalyzing = false
            } catch {
                guard !Task.isCancelled else { return }
                isAnalyzing = false; showToast("分析失败：\(error.localizedDescription)", success: false)
            }
        }
    }

    /// 中断当前分析。
    func cancelAnalysis() {
        currentTask?.cancel()
        isAnalyzing = false
        sessionState = "CANCELLED"
    }

    // MARK: - 卡片操作

    /// 确认一张动作卡片。
    ///
    /// 执行顺序（双写模式）：
    /// 1. 立即更新本地卡片状态为 `.confirmed`（UI 即时反馈，不等待网络）
    /// 2. 将卡片转为 `SavedCard` 持久化到 Core Data
    /// 3. 异步通知服务器（fire-and-forget，不阻塞 UI）
    /// 4. 显示成功 Toast
    ///
    /// - Parameter card: 被确认的动作卡片
    /// 已请求过洞察的卡片 ID 集合（防重复）。
    private var insightRequestedCards: Set<String> = []

    /// 处理洞察操作按钮
    func handleAction(_ card: ActionCard, _ action: InsightAction) {
        print("[VM] handleAction card=\(card.id) action=\(action.label) type=\(action.type)")
        switch action.type {
        case "execute":
            print("[VM] 执行卡片 | id=\(card.id) type=\(card.type) summary=\(card.summary) fields=\(card.fields)")
            Task {
                let success = await DeviceDataProvider().executeAction(card: card)
                if success { try? await service.executeAction(cardId: card.id) }
                await MainActor.run {
                    showToast(success ? "已执行: \(action.label)" : "执行失败，请检查权限", success: success)
                    if success {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                            withAnimation { self.cards.removeAll { $0.id == card.id } }
                        }
                    }
                }
            }
        case "dismiss":
            showToast("已关闭", success: true)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                withAnimation { self.cards.removeAll { $0.id == card.id } }
            }
        default: break
        }
    }

    func confirm(_ card: ActionCard) {
        updateStatus(card, to: .confirmed); save(card)
        Task { try? await service.confirmAction(cardId: card.id, cardType: card.type, cardSummary: card.summary, cardFields: card.fields) }
        showToast("已确认：\(CardIconHelper.label(for: card.type))", success: true)
        requestInsightIfNeeded(for: card)
    }

    private func requestInsightIfNeeded(for card: ActionCard) {
        print("[VM] requestInsight triggered: cardId=\(card.id) sessionId=\(sessionId ?? "nil") alreadyRequested=\(insightRequestedCards.contains(card.id))")
        guard !insightRequestedCards.contains(card.id), let sid = sessionId else { return }
        print("[VM] 开始采集设备数据并请求洞察...")
        insightRequestedCards.insert(card.id)
        sessionState = "GENERATING"

        Task {
            let provider = DeviceDataProvider()
            async let contacts = provider.fetchContacts()
            async let events = provider.fetchEvents()
            async let reminders = provider.fetchReminders()
            let (dc, de, dr) = await (contacts, events, reminders)

            do {
                for try await event in service.requestInsight(
                    sessionId: sid, cardId: card.id, cardType: card.type, cardSummary: card.summary,
                    deviceContacts: dc, deviceEvents: de, deviceReminders: dr
                ) {
                    switch event {
                    case .insight(let text):
                        if let idx = cards.firstIndex(where: { $0.id == card.id }) {
                            if let data = text.data(using: .utf8),
                               let ci = try? JSONDecoder().decode(CardInsight.self, from: data) {
                                cards[idx].insight = ci
                            } else {
                                print("[VM] CardInsight 解码失败，fallback 展示原文 raw=\(text.prefix(100))")
                                cards[idx].insight = CardInsight(
                                    cardId: card.id, verdict: "approved_with_note",
                                    title: "洞察生成完成", analysis: "无法解析", recommendation: text, actions: []
                                )
                            }
                        }
                    case .done: sessionState = "COMPLETED"
                    case .error(let p): sessionState = "INSIGHT_FAILED"; showToast("洞察失败: \(p.message)", success: false)
                    default: break
                    }
                }
            } catch {
                sessionState = "INSIGHT_FAILED"
                showToast("洞察请求失败", success: false)
            }
        }
    }

    /// 取消一张动作卡片。
    ///
    /// 执行顺序：
    /// 1. 立即更新本地卡片状态为 `.cancelled`（UI 即时反馈）
    /// 2. 异步通知服务器
    /// 3. 显示提示 Toast
    ///
    /// - Note: 取消操作不持久化到 Core Data，仅确认操作才保存
    /// - Parameter card: 被取消的动作卡片
    func cancel(_ card: ActionCard) {
        updateStatus(card, to: .cancelled)
        Task { try? await service.cancelAction(cardId: card.id, cardType: card.type, cardSummary: card.summary, cardFields: card.fields) }
        showToast("已取消：\(CardIconHelper.label(for: card.type))", success: false)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            withAnimation { self.cards.removeAll { $0.id == card.id } }
        }
    }

    // MARK: - 私有辅助方法

    /// 更新卡片列表中指定卡片的确认状态。
    ///
    /// 通过 `card.id` 在 `cards` 数组中定位目标卡片，
    /// 找到后直接修改其 `status` 属性（ActionCard 是 struct，需通过下标写入）。
    ///
    /// - Parameters:
    ///   - card: 目标卡片（仅用于 id 匹配）
    ///   - status: 新状态
    private func updateStatus(_ card: ActionCard, to status: CardStatus) {
        guard let idx = cards.firstIndex(where: { $0.id == card.id }) else {
            print("[VM] updateStatus 警告: 未找到卡片 id=\(card.id)"); return
        }
        cards[idx].status = status
    }

    /// 将确认的 `ActionCard` 转换为 `SavedCard` 并持久化到 Core Data。
    ///
    /// 转换映射：
    /// | ActionCard | SavedCard |
    /// |-----------|-----------|
    /// | id | id |
    /// | type | type |
    /// | summary | summary |
    /// | status.rawValue | status |
    /// | (无) | createdAt = Date() |
    ///
    /// - Parameter card: 待持久化的动作卡片
    private func save(_ card: ActionCard) {
        let saved = SavedCard(context: context)
        saved.id = card.id; saved.type = card.type; saved.summary = card.summary
        if let fieldsData = try? JSONEncoder().encode(card.fields),
           let fieldsStr = String(data: fieldsData, encoding: .utf8) {
            saved.fields = fieldsStr
        }
        saved.status = CardStatus.confirmed.rawValue; saved.createdAt = Date()
        do { try context.save() } catch { showToast("保存失败", success: false) }
    }

    /// 显示浮动 Toast 提示，2 秒后自动消失。
    ///
    /// 自动消失机制：等待 2 秒后检查 `toastMessage` 是否仍然是本次设置的消息，
    /// 如果是则清空（防止连续操作时后一条 Toast 被前一条的延迟清除覆盖）。
    ///
    /// - Parameters:
    ///   - message: 提示文本
    ///   - success: 是否成功（控制绿色/红色样式）
    private func showToast(_ message: String, success: Bool) {
        toastMessage = message; toastIsSuccess = success
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            // 仅当消息未被后续操作覆盖时才清除
            if toastMessage == message { toastMessage = nil }
        }
    }

}
