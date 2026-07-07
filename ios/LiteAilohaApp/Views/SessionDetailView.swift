import SwiftUI

/// 会话详情页 — 按需查看 Agent 分析过程数据。
///
/// 当前展示结构化对话，后续可追加：处理步骤、原始数据、耗时统计等。
struct SessionDetailView: View {

    let structure: StructPayload

    var body: some View {
        List {
            // 基本信息
            Section {
                LabeledContent("参与人") {
                    Text(structure.participants.joined(separator: "、"))
                }
                LabeledContent("消息数") {
                    Text("\(structure.messages.count) 条")
                }
            }

            // 消息列表
            Section("消息") {
                ForEach(structure.messages, id: \.time) { msg in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(msg.speaker)
                                .font(.caption)
                                .foregroundStyle(.blue)
                            Spacer()
                            Text(formatTime(msg.time))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Text(msg.content)
                            .font(.body)
                    }
                    .padding(.vertical, 4)
                }
            }

            // (预留) 处理步骤
            // (预留) 原始数据
            // (预留) 耗时统计
        }
        .navigationTitle("分析详情")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func formatTime(_ iso: String) -> String {
        if iso.count >= 16 {
            let start = iso.index(iso.startIndex, offsetBy: 11)
            let end = iso.index(iso.startIndex, offsetBy: 16)
            return String(iso[start..<end])
        }
        return String(iso.suffix(8))
    }
}
