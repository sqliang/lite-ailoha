import SwiftUI

// MARK: - 动作卡片组件 + Toast 提示组件
///
/// 本文件包含两个可复用的 UI 组件：
/// - ActionCardView：可交互的动作卡片，支持确认/取消操作
/// - ToastView：浮动提示条，支持成功/失败两种样式

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

    /// 根据卡片类型返回对应的 SF Symbol 图标名称。
    ///
    /// 图标映射：
    /// - `create_meeting` → `calendar.badge.plus`
    /// - `add_contact` → `person.crop.circle.badge.plus`
    /// - `set_reminder` → `bell.badge`
    /// - 其他 → `square.and.pencil`（通用编辑图标）
    private var icon: String {
        switch card.type {
        case "create_meeting": return "calendar.badge.plus"
        case "add_contact": return "person.crop.circle.badge.plus"
        case "set_reminder": return "bell.badge"
        default: return "square.and.pencil"
        }
    }

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

// MARK: - Toast 提示

/// 浮动 Toast 提示视图，用于在屏幕顶部显示操作反馈。
///
/// 使用示例：
/// ```swift
/// if let toast = vm.toastMessage {
///     ToastView(message: toast, success: vm.toastIsSuccess)
/// }
/// ```
///
/// 视觉风格：
/// - 成功：绿色前景色 + 对勾图标 + 毛玻璃背景
/// - 失败：红色前景色 + 警告三角图标 + 毛玻璃背景
struct ToastView: View {
    /// 提示消息文本
    let message: String
    /// `true` 为成功样式（绿色对勾），`false` 为失败样式（红色警告）
    let success: Bool

    var body: some View {
        Label(message, systemImage: success ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
            .font(.subheadline)
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(.ultraThinMaterial)    // 毛玻璃半透明背景
            .foregroundStyle(success ? .green : .red)
            .clipShape(Capsule())              // 胶囊形状
            .shadow(radius: 6)                 // 柔和投影
    }
}