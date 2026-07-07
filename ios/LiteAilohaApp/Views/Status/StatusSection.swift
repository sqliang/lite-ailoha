import SwiftUI

/// Agent 工作状态区域。
///
/// 根据 session_state 展示不同的状态 UI。
struct StatusSection: View {

    let state: String?

    var body: some View {
        if state != nil {
            HStack(spacing: 8) {
                statusIcon
                Text(statusText)
                    .font(.subheadline)
                if isProcessing {
                    ProgressView()
                        .scaleEffect(0.8)
                }
                Spacer()
            }
            .padding()
            .background(Color(.secondarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    // MARK: - Helpers

    private var isProcessing: Bool {
        guard let state else { return false }
        return ["PENDING", "STRUCTURING", "EXTRACTING", "GENERATING"].contains(state)
    }

    private var statusIcon: some View {
        guard let state else { return AnyView(EmptyView()) }
        switch state {
        case "STRUCTURE_FAILED", "INSIGHT_FAILED":
            return AnyView(Image(systemName: "xmark.circle.fill").foregroundStyle(.red))
        case "COMPLETED":
            return AnyView(Image(systemName: "checkmark.circle.fill").foregroundStyle(.green))
        case "STRUCTURED", "EXTRACTED":
            return AnyView(Image(systemName: "checkmark.circle.fill").foregroundStyle(.green))
        case "PARTIAL", "NO_CARDS":
            return AnyView(Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange))
        default:
            return AnyView(Image(systemName: "hourglass").foregroundStyle(.blue))
        }
    }

    private var statusText: String {
        guard let state else { return "" }
        switch state {
        case "PENDING": return "准备中..."
        case "STRUCTURING": return "正在理解聊天内容..."
        case "STRUCTURED": return "聊天内容已理解"
        case "EXTRACTING": return "正在识别待办事项..."
        case "EXTRACTED": return "待办事项已识别"
        case "PARTIAL": return "部分内容已识别"
        case "NO_CARDS": return "聊天中未发现待办事项"
        case "READY": return "请查看并确认卡片"
        case "GENERATING": return "正在生成建议..."
        case "COMPLETED": return "分析完成"
        case "STRUCTURE_FAILED": return "分析失败，请重试"
        case "INSIGHT_FAILED": return "洞察生成失败"
        default: return state
        }
    }
}
