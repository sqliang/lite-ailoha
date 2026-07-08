import SwiftUI

/// 分析页 — AI Native 布局：状态区在顶部，卡片居中，输入区固定在底部。
struct AnalysisView: View {

    @StateObject private var vm = AnalysisViewModel()

    @State private var imageData: Data?
    @State private var supplementText: String = ""

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Agent 状态（pinned 顶部，始终可见）
                if vm.isAnalyzing || vm.sessionState != nil {
                    Group {
                        if let sp = vm.structure {
                            NavigationLink(destination: SessionDetailView(structure: sp)) {
                                StatusSection(
                                    state: vm.sessionState,
                                    structure: vm.structure,
                                    cardCount: vm.cards.count,
                                    isAnalyzing: vm.isAnalyzing
                                )
                            }
                            .buttonStyle(.plain)
                        } else {
                            StatusSection(
                                state: vm.sessionState,
                                structure: vm.structure,
                                cardCount: vm.cards.count,
                                isAnalyzing: vm.isAnalyzing
                            )
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                }

                // 内容区域（可滚动）
                ScrollView {
                    VStack(spacing: 16) {

                        // 卡片列表（核心区域）
                        if !vm.cards.isEmpty {
                            ForEach(vm.cards) { card in
                                ActionCardView(
                                    card: card,
                                    typeLabel: CardIconHelper.label(for: card.type),
                                    onConfirm: { vm.confirm(card) },
                                    onCancel: { vm.cancel(card) },
                                    onAction: { action in vm.handleAction(card, action) }
                                )
                                .transition(.opacity.combined(with: .scale(scale: 0.95)))
                            }
                            .animation(.spring(response: 0.4, dampingFraction: 0.8), value: vm.cards.count)
                        }

                        // 空状态
                        if vm.cards.isEmpty && !vm.isAnalyzing {
                            VStack(spacing: 12) {
                                Image(systemName: "sparkles")
                                    .font(.largeTitle)
                                    .foregroundStyle(.secondary)
                                Text("上传聊天截图，让 AI 帮你\n识别会议、联系人和提醒事项")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .multilineTextAlignment(.center)
                            }
                            .padding(.vertical, 60)
                        }

                        // 洞察区域
                        InsightSection(insight: vm.insight)
                    }
                    .padding(16)
                }

                // 输入区域（固定底部）
                InputSection(
                    imageData: $imageData,
                    supplementText: $supplementText,
                    isAnalyzing: vm.isAnalyzing,
                    sessionState: vm.sessionState,
                    onAnalyze: { vm.startAnalysis(imageData: imageData, userContext: supplementText) },
                    onCancel: { vm.cancelAnalysis() }
                )
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(.bar)
            }
            .navigationTitle("Lite Ailoha")
            .navigationBarTitleDisplayMode(.inline)
            .animation(.spring(), value: vm.toastMessage)

            // Toast
            .overlay(alignment: .top) {
                if let toast = vm.toastMessage {
                    ToastView(message: toast, success: vm.toastIsSuccess)
                        .transition(.move(edge: .top).combined(with: .opacity))
                        .padding(.top, 4)
                        .padding(.horizontal, 16)
                }
            }
        }
    }
}

#Preview { AnalysisView() }
