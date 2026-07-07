import SwiftUI

/// 分析页：组装 4 个功能区域 + Toast 覆盖层。
///
/// 作为 NavigationStack 中的一个页面，后续可 push 到其他页面。
struct AnalysisView: View {

    @StateObject private var vm = AnalysisViewModel()

    @State private var imageData: Data?
    @State private var supplementText: String = ""

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                ScrollView {
                    VStack(spacing: 20) {
                        // 1. 输入区域
                        InputSection(
                            imageData: $imageData,
                            supplementText: $supplementText,
                            isAnalyzing: vm.isAnalyzing,
                            onAnalyze: { vm.startAnalysis(imageData: imageData, userContext: supplementText) }
                        )

                        // 2. Agent 状态区域
                        if vm.sessionState != nil {
                            StatusSection(state: vm.sessionState)
                        }

                        // 3. 查看结构化对话入口（分析完成后显示）
                        if vm.hasStructure, let sp = vm.structure {
                            NavigationLink {
                                SessionDetailView(structure: sp)
                            } label: {
                                Label("查看分析详情", systemImage: "text.bubble")
                                    .font(.subheadline.bold())
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 14)
                                    .background(Color(.secondarySystemBackground))
                                    .clipShape(RoundedRectangle(cornerRadius: 12))
                            }
                        }

                        // 4. 卡片列表区域
                        if !vm.cards.isEmpty || vm.isAnalyzing {
                            CardsSection(
                                cards: vm.cards,
                                onConfirm: { vm.confirm($0) },
                                onCancel: { vm.cancel($0) }
                            )
                        }

                        // 5. 洞察建议区域
                        InsightSection(insight: vm.insight)
                    }
                    .padding()
                }

                // Toast 覆盖层
                if let toast = vm.toastMessage {
                    ToastView(message: toast, success: vm.toastIsSuccess)
                        .transition(.move(edge: .top).combined(with: .opacity))
                        .padding(.top, 8)
                }
            }
            .animation(.spring(), value: vm.toastMessage)
            .navigationTitle("Lite Ailoha")
        }
    }
}

#Preview { AnalysisView() }
