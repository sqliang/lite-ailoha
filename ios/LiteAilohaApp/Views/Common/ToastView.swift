import SwiftUI

/// 浮动 Toast 提示视图，用于在屏幕顶部显示操作反馈。
///
/// 视觉风格：
/// - 成功：绿色前景色 + 对勾图标 + 毛玻璃背景
/// - 失败：红色前景色 + 警告三角图标 + 毛玻璃背景
struct ToastView: View {
    let message: String
    let success: Bool

    var body: some View {
        Label(message, systemImage: success ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
            .font(.subheadline)
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(.ultraThinMaterial)
            .foregroundStyle(success ? .green : .red)
            .clipShape(Capsule())
            .shadow(radius: 6)
    }
}
