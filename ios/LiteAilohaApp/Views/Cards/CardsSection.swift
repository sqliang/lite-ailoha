import SwiftUI

/// 动作卡片列表区域。
struct CardsSection: View {

    let cards: [ActionCard]
    let onConfirm: (ActionCard) -> Void
    let onCancel: (ActionCard) -> Void
    var onAction: ((ActionCard, InsightAction) -> Void)? = nil

    var body: some View {
        if !cards.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("分析结果").font(.headline)
                ForEach(cards) { card in
                    ActionCardView(
                        card: card,
                        typeLabel: CardIconHelper.label(for: card.type),
                        onConfirm: { onConfirm(card) },
                        onCancel: { onCancel(card) },
                        onAction: { action in onAction?(card, action) }
                    )
                }
            }
        }
    }
}
