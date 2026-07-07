import SwiftUI
import CoreData
import Combine

@MainActor
final class AnalysisViewModel: ObservableObject {
    @Published var cards: [ActionCard] = []
    @Published var insight: String = ""
    @Published var isAnalyzing = false
    @Published var structure: StructPayload?
    var hasStructure: Bool { structure != nil && !(structure?.messages.isEmpty ?? true) }

    @Published var toastMessage: String?
    @Published var toastIsSuccess = true

    private let service = AnalysisService()
    private let context = PersistenceController.shared.container.viewContext

    func startAnalysis(imageData: Data?, userContext: String = "") {
        cards = []; insight = ""; structure = nil; isAnalyzing = true
        Task {
            do {
                for try await event in service.analyze(imageData: imageData, userContext: userContext) {
                    switch event {
                    case .structure(let sp): structure = sp
                    case .card(let card): cards.append(card)
                    case .insight(let text): insight = text
                    case .error(let p): showToast(p.message, success: false)
                    case .done: break
                    }
                }
                isAnalyzing = false
            } catch { isAnalyzing = false; showToast("分析失败：\(error.localizedDescription)", success: false) }
        }
    }

    func confirm(_ card: ActionCard) {
        updateStatus(card, to: .confirmed); save(card)
        Task { try? await service.confirmAction(cardId: card.id) }
        showToast("已确认：\(typeLabel(card.type))", success: true)
    }

    func cancel(_ card: ActionCard) {
        updateStatus(card, to: .cancelled)
        Task { try? await service.cancelAction(cardId: card.id) }
        showToast("已取消：\(typeLabel(card.type))", success: false)
    }

    private func updateStatus(_ card: ActionCard, to status: CardStatus) {
        guard let idx = cards.firstIndex(where: { $0.id == card.id }) else { return }
        cards[idx].status = status
    }

    private func save(_ card: ActionCard) {
        let saved = SavedCard(context: context)
        saved.id = card.id; saved.type = card.type; saved.summary = card.summary
        saved.status = CardStatus.confirmed.rawValue; saved.createdAt = Date()
        do { try context.save() } catch { showToast("保存失败", success: false) }
    }

    private func showToast(_ message: String, success: Bool) {
        toastMessage = message; toastIsSuccess = success
        Task { try? await Task.sleep(nanoseconds: 2_000_000_000); if toastMessage == message { toastMessage = nil } }
    }

    func typeLabel(_ type: String) -> String {
        switch type {
        case "create_meeting": return "创建会议"
        case "create_contact": return "创建联系人"
        case "update_contact": return "更新联系人"
        case "create_reminder": return "创建提醒"
        default: return "动作"
        }
    }
}
