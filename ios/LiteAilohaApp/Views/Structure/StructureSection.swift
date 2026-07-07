import SwiftUI

/// 可展开的结构化对话区域。
struct StructureSection: View {

    let structure: StructPayload?
    @Binding var showStructure: Bool

    var body: some View {
        if let sp = structure, !sp.messages.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                // 标题栏（可点击展开/折叠）
                Button {
                    withAnimation { showStructure.toggle() }
                } label: {
                    HStack {
                        Label("结构化对话", systemImage: "text.bubble")
                            .font(.subheadline.bold())
                        Spacer()
                        Text(sp.participants.joined(separator: " & "))
                            .font(.caption).foregroundStyle(.secondary)
                        Image(systemName: showStructure ? "chevron.down" : "chevron.right")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                // 消息列表（展开时显示）
                if showStructure {
                    ForEach(sp.messages, id: \.time) { msg in
                        HStack(alignment: .top, spacing: 8) {
                            Text(msg.time.suffix(8)).font(.caption2).foregroundStyle(.secondary)
                                .frame(width: 50, alignment: .trailing)
                            Text(msg.speaker).font(.caption).foregroundStyle(.blue)
                                .frame(width: 60, alignment: .leading)
                            Text(msg.content).font(.caption)
                            Spacer()
                        }
                    }
                }
            }
            .padding()
            .background(Color(.secondarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }
}
