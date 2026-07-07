import SwiftUI

/// AI 洞察/建议展示区域。
struct InsightSection: View {

    let insight: String

    var body: some View {
        if !insight.isEmpty {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "lightbulb.fill").foregroundStyle(.yellow)
                Text(insight).font(.callout)
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }
}
