import SwiftUI

/// Agent 工作步骤列表 — 实时展示处理进度。
struct StatusSection: View {

    let state: String?
    let structure: StructPayload?
    let cardCount: Int
    let isAnalyzing: Bool

    /// 循环切换文案的索引
    @State private var messageIndex = 0

    /// 文案池
    private let messagePool: [String: [String]] = [
        "structuring": [
            "正在理解聊天内容…",
            "正在分析对话结构…",
            "正在识别参与者…",
            "正在解析消息时间线…",
        ],
        "extracting": [
            "正在识别待办事项…",
            "正在分析会议安排…",
            "正在提取联系人信息…",
            "正在匹配提醒规则…",
        ],
        "insight": [
            "正在生成洞察建议…",
            "正在分析上下文关联…",
            "正在整理关键发现…",
        ],
    ]

    /// 当前展示的文案（由 sessionState 决定文案池）
    private var displayMessage: String {
        let step = stepFromState
        guard let pool = messagePool[step] else {
            return "Agent 正在分析…"
        }
        if messageIndex == 0 {
            return pool[0]
        }
        return pool[messageIndex % pool.count]
    }

    /// sessionState → 文案池步骤标识
    private var stepFromState: String {
        switch state {
        case "PENDING", "STRUCTURING": return "structuring"
        case "STRUCTURED", "EXTRACTING", "EXTRACTED", "PARTIAL", "NO_CARDS": return "extracting"
        case "GENERATING", "COMPLETED": return "insight"
        default: return "structuring"
        }
    }

    // MARK: - Body

    var body: some View {
        // 分析中但没有具体状态 → 显示基础进度
        if state == nil && !isAnalyzing { EmptyView() }

        VStack(alignment: .leading, spacing: 0) {
            // 当前进度文案（循环切换，分析中始终展示）
            if isAnalyzing || (state != nil && state != "READY" && state != "COMPLETED") {
                HStack(spacing: 10) {
                    ProgressView().scaleEffect(0.8)
                    Text(displayMessage)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.primary)
                        .contentTransition(.opacity)
                        .animation(.easeInOut(duration: 0.3), value: displayMessage)
                    Spacer()
                }
                .padding(.vertical, 10)
                .padding(.horizontal, 4)
            }

            if state == "CANCELLED" {
                HStack {
                    Image(systemName: "stop.circle.fill")
                        .foregroundColor(.orange)
                    Text("已停止分析")
                        .font(.subheadline)
                    Spacer()
                }
                .padding(.vertical, 10)
                .padding(.horizontal, 4)
            }

            stepRow(
                icon: "text.bubble.fill",
                label: "理解聊天内容",
                status: stepStatus(for: .structure),
                detail: structure.map { "\($0.participants.count)人, \($0.messages.count)条消息" },
                link: structure.map { _ in AnyView(Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.secondary)) }
            )

            Divider().padding(.leading, 36)

            stepRow(
                icon: "list.bullet.rectangle",
                label: "识别待办事项",
                status: stepStatus(for: .extract),
                detail: cardCount > 0 ? "已识别 \(cardCount) 个" : nil
            )

            Divider().padding(.leading, 36)

            stepRow(
                icon: "lightbulb.fill",
                label: "生成洞察建议",
                status: stepStatus(for: .insight),
                detail: nil
            )
        }
        .padding(.vertical, 12)
        .padding(.horizontal, 16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .onChange(of: state) { _, _ in
            messageIndex = 0  // 状态变化时重置
        }
        .task(id: state) {
            // 每 3 秒循环切换文案
            let step = stepFromState
            guard let pool = messagePool[step], pool.count > 1 else { return }
            var i = 1
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                if Task.isCancelled { return }
                withAnimation { messageIndex = i }
                i = (i + 1) % pool.count
                if i == 0 { i = 1 }
            }
        }
    }

    // MARK: - 步骤状态判定

    private enum Step { case structure, extract, insight }

    private func stepStatus(for step: Step) -> StepStatus {
        guard let state else {
            // state 未到达时的保守推断：running 乐观（在干），done 等 state 确认
            let structDone = structure != nil
            switch step {
            case .structure: return structDone ? .done : (isAnalyzing ? .running : .pending)
            case .extract:   return structDone ? .running : .pending
            case .insight:   return .pending
            }
        }

        switch state {
        case "CANCELLED":
            return .failed
        default: break
        }

        switch step {
        case .structure:
            switch state {
            case "PENDING", "STRUCTURING": return .running
            case "STRUCTURED", "EXTRACTING", "EXTRACTED", "PARTIAL", "NO_CARDS",
                 "READY", "GENERATING", "COMPLETED": return .done
            case "STRUCTURE_FAILED": return .failed
            default: return .pending
            }
        case .extract:
            switch state {
            case "PENDING", "STRUCTURING": return .pending
            case "STRUCTURED", "EXTRACTING": return .running
            case "EXTRACTED", "PARTIAL", "NO_CARDS",
                 "READY", "GENERATING", "COMPLETED": return .done
            default: return .pending
            }
        case .insight:
            switch state {
            case "GENERATING": return .running
            case "COMPLETED": return .done
            case "INSIGHT_FAILED": return .failed
            default: return .pending
            }
        }
    }

    private enum StepStatus {
        case pending, running, done, failed
    }

    @ViewBuilder
    private func stepRow(icon: String, label: String, status: StepStatus, detail: String?, link: AnyView? = nil) -> some View {
        HStack(spacing: 12) {
            // 图标 + 状态
            ZStack {
                Image(systemName: icon)
                    .font(.callout)
                    .foregroundStyle(iconColor(status))
                    .opacity(status == .pending ? 0.5 : 1)

                if status == .running {
                    ProgressView()
                        .scaleEffect(0.7)
                }
            }
            .frame(width: 24, height: 24)

            // 文字
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(label)
                        .font(.subheadline)
                        .foregroundStyle(status == .pending ? .secondary : .primary)
                    statusBadge(status)
                }
                if let detail {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()
            if let link { link }
        }
        .padding(.vertical, 10)
    }

    private func iconColor(_ status: StepStatus) -> Color {
        switch status {
        case .pending: return .secondary
        case .running: return .accentColor
        case .done: return .green
        case .failed: return .red
        }
    }

    @ViewBuilder
    private func statusBadge(_ status: StepStatus) -> some View {
        switch status {
        case .pending:
            Image(systemName: "circle")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        case .running:
            Text("进行中")
                .font(.caption2)
                .foregroundStyle(.blue)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .font(.caption2)
                .foregroundStyle(.green)
        case .failed:
            Image(systemName: "xmark.circle.fill")
                .font(.caption2)
                .foregroundStyle(.red)
        }
    }
}
