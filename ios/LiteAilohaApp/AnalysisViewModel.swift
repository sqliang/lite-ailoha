import SwiftUI
import CoreData
import Combine

// MARK: - 分析状态管理
///
/// 本文件是应用的 ViewModel 层，负责：
/// 1. 管理 UI 状态（卡片列表、洞察文本、加载状态、Toast 消息）
/// 2. 调用 AnalysisService 发起分析并消费 SSE 流式事件
/// 3. 处理用户交互（确认/取消卡片）
/// 4. 将用户确认的卡片持久化到 Core Data

// MARK: - 分析 ViewModel

/// 主界面的状态管理与业务逻辑控制器。
///
/// 作为 `@MainActor ObservableObject`，确保所有 UI 状态更新在主线程执行。
/// 通过 `@Published` 属性自动驱动 SwiftUI 视图刷新。
///
/// 数据流：
/// ```
/// 用户点击"开始分析"
///   → startAnalysis() 调用 AnalysisService.analyze()
///   → 逐条消费 AsyncThrowingStream 中的 StreamEvent
///   → .card 追加到 cards，.insight 更新 insight，.done 结束加载
/// 用户确认卡片
///   → confirm() 更新状态 + 存入 Core Data + 显示 Toast
/// ```
@MainActor
final class AnalysisViewModel: ObservableObject {
    /// 当前分析结果中的动作卡片列表
    @Published var cards: [ActionCard] = []
    /// AI 分析后的洞察/建议文本
    @Published var insight: String = ""
    /// 是否正在执行分析（控制加载指示器和按钮状态）
    @Published var isAnalyzing = false

    // MARK: - Toast 状态

    /// Toast 提示消息内容（`nil` 时不显示）
    @Published var toastMessage: String?
    /// Toast 消息类型：`true` 为成功（绿色），`false` 为失败（红色）
    @Published var toastIsSuccess = true

    /// 分析服务实例
    private let service = AnalysisService()
    /// Core Data 托管上下文，用于持久化已确认的卡片
    private let context = PersistenceController.shared.container.viewContext

    // MARK: - 分析流程

    /// 启动分析流程：清空旧结果 → 设置加载状态 → 消费 SSE 流式事件。
    ///
    /// 整个分析过程在主线程消费事件（保证 UI 更新安全），
    /// 但实际的网络 I/O 在 AnalysisService 内部的 `Task.detached` 中执行，
    /// 不会阻塞 UI。
    ///
    /// - Parameters:
    ///   - imageData: 用户选择的截图/照片数据（可选）
    ///   - text: 用户输入的补充说明文字
    func startAnalysis(imageData: Data?, text: String) {
        // 清空上一次的分析结果
        cards = []
        insight = ""
        isAnalyzing = true

        // 在 MainActor 上消费流式事件，确保 UI 更新在主线程
        Task {
            do {
                // 逐条迭代 SSE 流式事件
                for try await event in service.analyze(imageData: imageData, text: text) {
                    switch event {
                    case .card(let card):
                        // 将新卡片追加到列表末尾
                        cards.append(card)
                    case .insight(let text):
                        // 更新洞察文本
                        insight = text
                    case .done:
                        // 流结束，不做额外处理（isAnalyzing 在循环外统一设置）
                        break
                    }
                }
                isAnalyzing = false
            } catch {
                // 分析失败：停止加载并显示错误提示
                isAnalyzing = false
                showToast("分析失败：\(error.localizedDescription)", success: false)
            }
        }
    }

    // MARK: - 卡片操作

    /// 确认指定卡片：将其状态更新为已确认，持久化到 Core Data，并显示成功提示。
    ///
    /// - Parameter card: 要确认的动作卡片
    func confirm(_ card: ActionCard) {
        updateStatus(card, to: .confirmed)
        save(card)
        showToast("已确认：\(typeLabel(card.type))", success: true)
    }

    /// 取消指定卡片：将其状态更新为已取消，并显示取消提示。
    ///
    /// 取消的卡片不会被持久化到 Core Data。
    ///
    /// - Parameter card: 要取消的动作卡片
    func cancel(_ card: ActionCard) {
        updateStatus(card, to: .cancelled)
        showToast("已取消：\(typeLabel(card.type))", success: false)
    }

    /// 更新指定卡片在列表中的状态。
    ///
    /// - Parameters:
    ///   - card: 目标卡片（通过 id 匹配）
    ///   - status: 新状态
    private func updateStatus(_ card: ActionCard, to status: CardStatus) {
        guard let idx = cards.firstIndex(where: { $0.id == card.id }) else { return }
        cards[idx].status = status
    }

    // MARK: - Core Data 持久化

    /// 将已确认的卡片保存到 Core Data。
    ///
    /// 保存的字段包括：id、type、summary、status（固定为 confirmed）、createdAt（当前时间）。
    ///
    /// - Parameter card: 已确认的动作卡片
    private func save(_ card: ActionCard) {
        let saved = SavedCard(context: context)
        saved.id = card.id
        saved.type = card.type
        saved.summary = card.summary
        saved.status = CardStatus.confirmed.rawValue
        saved.createdAt = Date()
        do {
            try context.save()
        } catch {
            showToast("保存失败", success: false)
        }
    }

    // MARK: - Toast

    /// 显示 Toast 提示消息，2 秒后自动消失。
    ///
    /// - Parameters:
    ///   - message: 提示文本
    ///   - success: `true` 显示绿色成功图标，`false` 显示红色错误图标
    private func showToast(_ message: String, success: Bool) {
        toastMessage = message
        toastIsSuccess = success
        // 2 秒后自动清除 Toast（仅当消息未被覆盖时）
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            if toastMessage == message { toastMessage = nil }
        }
    }

    // MARK: - 工具方法

    /// 将动作类型的英文标识转换为中文显示文案。
    ///
    /// - Parameter type: 英文动作类型，如 "create_meeting"
    /// - Returns: 中文文案，如 "创建会议"
    func typeLabel(_ type: String) -> String {
        switch type {
        case "create_meeting": return "创建会议"
        case "add_contact": return "添加联系人"
        case "set_reminder": return "设置提醒"
        default: return "动作"
        }
    }
}