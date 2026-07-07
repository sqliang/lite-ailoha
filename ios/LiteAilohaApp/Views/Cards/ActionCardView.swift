import SwiftUI

// MARK: - 动作卡片

/// 单张动作卡片的 SwiftUI 视图。
///
/// 卡片分为两个区域：
/// 1. 头部：动作类型图标 + 类型标签 + 状态徽章（已确认/已取消）
/// 2. 底部：动作摘要 + 确认/取消按钮（仅在 pending 状态显示）
///
/// 使用示例：
/// ```swift
/// ActionCardView(
///     card: card,
///     typeLabel: "创建会议",
///     onConfirm: { viewModel.confirm(card) },
///     onCancel: { viewModel.cancel(card) }
/// )
/// ```
struct ActionCardView: View {
    /// 卡片数据模型
    let card: ActionCard
    /// 动作类型的中文显示文案（如 "创建会议"）
    let typeLabel: String
    /// 用户点击"确认"按钮的回调
    let onConfirm: () -> Void
    /// 用户点击"取消"按钮的回调
    let onCancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // --- 卡片头部：类型图标 + 中文标签 + 状态徽章 ---
            HStack {
                Label(typeLabel, systemImage: icon)
                    .font(.subheadline.bold())
                    .foregroundColor(.accentColor)
                Spacer()
                statusBadge
            }

            // --- 卡片正文：动作摘要描述 ---
            Text(card.summary)
                .font(.body)
                .foregroundStyle(.primary)

            // --- 操作按钮区：仅在待确认状态显示确认/取消按钮 ---
            if card.status == .pending {
                HStack(spacing: 12) {
                    // 取消按钮
                    Button(action: onCancel) {
                        Text("取消")
                            .frame(maxWidth: .infinity).padding(.vertical, 10)
                            .background(Color(.tertiarySystemBackground))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    // 确认按钮（主题色高亮）
                    Button(action: onConfirm) {
                        Text("确认")
                            .frame(maxWidth: .infinity).padding(.vertical, 10)
                            .background(Color.accentColor)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                }
            }
        }
        .padding()
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    // MARK: - 辅助属性

    private var icon: String { CardIconHelper.icon(for: card.type) }

    /// 状态徽章视图。
    ///
    /// - pending：不显示徽章
    /// - confirmed：绿色"已确认"徽章 + 对勾图标
    /// - cancelled：红色"已取消"徽章 + 叉号图标
    @ViewBuilder private var statusBadge: some View {
        switch card.status {
        case .pending:
            // 待确认状态不显示徽章
            EmptyView()
        case .confirmed:
            Label("已确认", systemImage: "checkmark.circle.fill")
                .font(.caption).foregroundStyle(.green)
        case .cancelled:
            Label("已取消", systemImage: "xmark.circle.fill")
                .font(.caption).foregroundStyle(.red)
        }
    }
}