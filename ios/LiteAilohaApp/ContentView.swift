import SwiftUI
import PhotosUI

// MARK: - 主界面
///
/// 本文件是应用的主界面视图，包含以下功能区域：
/// 1. 上传区：照片预览 + 相册选择 + 拍照按钮
/// 2. 文本区：补充说明文字输入框
/// 3. 分析按钮：触发 AI 分析（含加载状态）
/// 4. 结果区：流式展示分析结果卡片列表
/// 5. 洞察区：AI 分析后的建议文本
/// 6. Toast：操作反馈浮动提示

/// 应用主界面，组合上传区、文本区、分析按钮和结果展示。
///
/// 布局结构：
/// ```
/// NavigationStack
///   └── ZStack
///        ├── ScrollView（主内容）
///        │    └── VStack
///        │         ├── uploadSection（照片 + 选择按钮）
///        │         ├── textSection（补充文字）
///        │         ├── analyzeButton（分析按钮）
///        │         ├── resultSection（分析结果卡片）
///        │         └── insightSection（洞察建议）
///        └── ToastView（浮动提示，条件显示）
/// ```
struct ContentView: View {
    /// 分析 ViewModel，管理所有业务状态
    @StateObject private var vm = AnalysisViewModel()

    /// 相册选择器的选中项
    @State private var pickerItem: PhotosPickerItem?
    /// 用户选择/拍摄的照片原始数据
    @State private var imageData: Data?
    /// 用户输入的补充说明文字
    @State private var supplementText: String = ""
    /// 是否弹出相机拍照 Sheet
    @State private var showCamera = false

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                // --- 主内容区域（可滚动） ---
                ScrollView {
                    VStack(spacing: 20) {
                        uploadSection
                        textSection
                        analyzeButton

                        // 结果区：有卡片时或分析中时显示
                        if !vm.cards.isEmpty || vm.isAnalyzing {
                            resultSection
                        }

                        // 洞察区：有洞察文本时显示
                        if !vm.insight.isEmpty {
                            insightSection
                        }
                    }
                    .padding()
                }

                // --- 浮动 Toast（条件显示 + 动画） ---
                if let toast = vm.toastMessage {
                    ToastView(message: toast, success: vm.toastIsSuccess)
                        .transition(.move(edge: .top).combined(with: .opacity))  // 从顶部滑入
                        .padding(.top, 8)
                }
            }
            .animation(.spring(), value: vm.toastMessage)  // Toast 切换时使用弹簧动画
            .navigationTitle("Lite Ailoha")
        }
        // 监听相册选择器变化，加载照片数据
        .onChange(of: pickerItem) { _, newItem in
            Task {
                if let data = try? await newItem?.loadTransferable(type: Data.self) {
                    imageData = data
                }
            }
        }
        // 弹出系统相机
        .sheet(isPresented: $showCamera) {
            CameraPicker(imageData: $imageData)
        }
    }

    // MARK: - 上传区

    /// 照片上传区域：
    /// - 上方：已选照片的缩略图预览
    /// - 下方：横排两个按钮 —— 相册选择 + 拍照
    private var uploadSection: some View {
        VStack(spacing: 12) {
            // 照片预览（仅在选中有数据时显示）
            if let data = imageData, let uiImage = UIImage(data: data) {
                Image(uiImage: uiImage)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }

            // 相册 + 拍照按钮（横排等宽）
            HStack(spacing: 12) {
                // 相册选择器（PhotosPicker）
                PhotosPicker(selection: $pickerItem, matching: .images) {
                    Label("相册", systemImage: "photo.on.rectangle")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                // 拍照按钮（弹出 CameraPicker）
                Button {
                    showCamera = true
                } label: {
                    Label("拍照", systemImage: "camera")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
            }
        }
    }

    // MARK: - 文本区

    /// 补充文字输入区域：
    /// 用户可在此输入额外的上下文信息辅助 AI 分析（如会议目的、联系人背景等）
    private var textSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("补充文字")
                .font(.subheadline).foregroundStyle(.secondary)
            TextEditor(text: $supplementText)
                .frame(height: 100)
                .padding(8)
                .background(Color(.secondarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    // MARK: - 分析按钮

    /// 分析触发按钮。
    ///
    /// 两种状态：
    /// - 空闲：显示"开始分析"，主题色背景
    /// - 分析中：显示"分析中…"+ 转圈动画，灰色背景，不可点击
    private var analyzeButton: some View {
        Button {
            // 触发分析流程
            vm.startAnalysis(imageData: imageData, text: supplementText)
        } label: {
            HStack {
                // 分析中显示旋转进度指示器
                if vm.isAnalyzing { ProgressView().tint(.white) }
                Text(vm.isAnalyzing ? "分析中…" : "开始分析")
            }
            .font(.headline)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(vm.isAnalyzing ? Color.gray : Color.accentColor)
            .foregroundStyle(.white)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .disabled(vm.isAnalyzing)  // 分析中禁止重复点击
    }

    // MARK: - 结果区

    /// 分析结果展示区域：
    /// 以列表形式展示 AI 识别出的动作卡片，每张卡片支持确认/取消交互
    private var resultSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("分析结果")
                .font(.headline)

            // 遍历卡片列表，渲染每张 ActionCardView
            ForEach(vm.cards) { card in
                ActionCardView(
                    card: card,
                    typeLabel: vm.typeLabel(card.type),
                    onConfirm: { vm.confirm(card) },
                    onCancel: { vm.cancel(card) }
                )
            }
        }
    }

    // MARK: - 洞察区

    /// AI 洞察/建议文本展示区域：
    /// 以灯泡图标 + 文本形式展示 AI 对截图和补充文字的综合分析建议
    private var insightSection: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lightbulb.fill").foregroundStyle(.yellow)
            Text(vm.insight).font(.callout)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

#Preview {
    ContentView()
}