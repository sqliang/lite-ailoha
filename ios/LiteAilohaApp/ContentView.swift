import SwiftUI
import PhotosUI

// MARK: - 主界面视图
///
/// `ContentView` 是 App 的根视图，组合所有 UI 区块。
///
/// ## 页面布局（从上到下）
/// ```
/// NavigationStack
/// └── ZStack
///     ├── ScrollView
///     │   └── VStack(spacing: 20)
///     │       ├── uploadSection     图片选择区（预览 + 相册/拍照按钮）
///     │       ├── textSection       补充说明输入
///     │       ├── analyzeButton     开始分析按钮
///     │       ├── structureSection  结构化对话（可展开，仅在分析完成后显示）
///     │       ├── resultSection     动作卡片列表
///     │       └── insightSection    洞察建议
///     └── ToastView（覆盖层）        操作反馈浮动提示
/// ```
///
/// ## 交互流程
/// 1. 用户选择图片（相册或拍照）→ `imageData` 绑定更新
/// 2. 用户可选填写补充说明 → `supplementText` 绑定更新
/// 3. 用户点击「开始分析」→ `vm.startAnalysis()` 启动 SSE 流式分析
/// 4. 分析过程中卡片逐个出现，用户可确认/取消
/// 5. 操作反馈通过顶部 Toast 展示

struct ContentView: View {

    // MARK: - 状态

    /// 视图模型（中央状态机），持有所有分析相关的 @Published 状态
    @StateObject private var vm = AnalysisViewModel()

    /// PhotosPicker 选中的图片项（SwiftUI PhotosUI 框架）
    @State private var pickerItem: PhotosPickerItem?

    /// 用户选择/拍摄的图片数据。
    /// PhotosPicker 选中后经 ImageProcessor 预处理写入此变量，
    /// CameraPicker 拍摄后直接写入 JPEG Data。
    @State private var imageData: Data?

    /// 用户附加的补充说明文本（自由文本，发送给服务端作为上下文）
    @State private var supplementText: String = ""

    /// 是否弹出系统相机 Sheet
    @State private var showCamera = false

    /// 结构化对话区域的展开/折叠状态
    @State private var showStructure = false

    // MARK: - 视图主体

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                // --- 内容层：可滚动的分析界面 ---
                ScrollView {
                    VStack(spacing: 20) {
                        uploadSection
                        textSection
                        analyzeButton
                        // 仅在分析完成后显示结构化对话入口
                        if vm.hasStructure { structureSection }
                        // 分析中或有结果时显示卡片列表区域
                        if !vm.cards.isEmpty || vm.isAnalyzing { resultSection }
                        // 洞察文本非空时显示
                        if !vm.insight.isEmpty { insightSection }
                    }.padding()
                }

                // --- 覆盖层：顶部浮动 Toast ---
                // 动画绑定到 toastMessage，消息变化时触发过渡动画
                if let toast = vm.toastMessage {
                    ToastView(message: toast, success: vm.toastIsSuccess)
                        .transition(.move(edge: .top).combined(with: .opacity))  // 从顶部滑入 + 淡入淡出
                        .padding(.top, 8)
                }
            }
            .animation(.spring(), value: vm.toastMessage)  // Toast 出现/消失的弹性动画
            .navigationTitle("Lite Ailoha")
        }
        // PhotosPicker 选取回调：异步加载图片数据 → ImageProcessor 预处理
        .onChange(of: pickerItem) { _, newItem in
            Task {
                if let data = try? await newItem?.loadTransferable(type: Data.self) {
                    // 图片预处理：缩放到 1024px + JPEG 压缩
                    imageData = ImageProcessor().process(data)
                }
            }
        }
        // 系统相机 Sheet：拍摄完成后 imageData 绑定自动更新
        .sheet(isPresented: $showCamera) { CameraPicker(imageData: $imageData) }
    }

    // MARK: - 图片上传区

    /// 图片上传区域：预览已选图片 + 相册/拍照双入口按钮。
    ///
    /// 布局：
    /// - 上方：已选图片预览（缩放至 200px 高，圆角裁剪）
    /// - 下方：水平排列两个按钮 — 相册（PhotosPicker）和拍照（系统相机 Sheet）
    private var uploadSection: some View {
        VStack(spacing: 12) {
            // 已选图片预览：仅在有数据时显示
            if let data = imageData, let uiImage = UIImage(data: data) {
                Image(uiImage: uiImage)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            HStack(spacing: 12) {
                // 相册按钮：使用 iOS 16+ PhotosPicker，无需权限申请
                PhotosPicker(selection: $pickerItem, matching: .images) {
                    Label("相册", systemImage: "photo.on.rectangle")
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                // 拍照按钮：弹出系统相机（模拟器自动降级为相册）
                Button { showCamera = true } label: {
                    Label("拍照", systemImage: "camera")
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
            }
        }
    }

    // MARK: - 补充说明输入区

    /// 补充说明文本输入区。
    ///
    /// 用户在分析前可输入任意文本，作为额外的上下文信息
    /// 与服务端交互（发送到 `user_context` 字段）。
    /// 使用 `TextEditor` 而非 `TextField` 以支持多行输入。
    private var textSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("补充说明").font(.subheadline).foregroundStyle(.secondary)
            TextEditor(text: $supplementText)
                .frame(height: 60).padding(8)
                .background(Color(.secondarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    // MARK: - 分析按钮

    /// 开始分析按钮。
    ///
    /// 状态切换：
    /// - 空闲态：蓝色按钮，文字「开始分析」，可点击
    /// - 分析中：灰色按钮，显示 `ProgressView` 旋转指示器 + 文字「分析中…」，不可点击
    ///
    /// 点击后调用 `vm.startAnalysis()` 传入图片数据 + 补充说明文本。
    private var analyzeButton: some View {
        Button {
            vm.startAnalysis(imageData: imageData, userContext: supplementText)
        } label: {
            HStack {
                if vm.isAnalyzing {
                    ProgressView().tint(.white)   // 白色旋转指示器
                }
                Text(vm.isAnalyzing ? "分析中…" : "开始分析")
            }
            .font(.headline)
            .frame(maxWidth: .infinity).padding(.vertical, 14)
            .background(vm.isAnalyzing ? Color.gray : Color.accentColor)
            .foregroundStyle(.white)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .disabled(vm.isAnalyzing)  // 分析中禁用按钮
    }

    // MARK: - 结构化对话区

    /// 可展开的结构化对话区域。
    ///
    /// 交互：
    /// - 标题栏可点击，点击切换 `showStructure` 展开/折叠
    /// - 标题栏显示参与人名称（以 " & " 连接）
    /// - 右侧箭头图标随状态旋转（展开向下，折叠向右）
    /// - 展开后显示逐条消息：时间（HH:mm:ss 格式）| 发言人 | 消息内容
    private var structureSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            // 标题栏（可点击展开/折叠）
            Button {
                withAnimation { showStructure.toggle() }
            } label: {
                HStack {
                    Label("结构化对话", systemImage: "text.bubble")
                        .font(.subheadline.bold())
                    Spacer()
                    Text(vm.structure?.participants.joined(separator: " & ") ?? "")
                        .font(.caption).foregroundStyle(.secondary)
                    Image(systemName: showStructure ? "chevron.down" : "chevron.right")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            // 消息列表（展开时显示）
            if showStructure, let sp = vm.structure {
                ForEach(sp.messages, id: \.time) { msg in
                    HStack(alignment: .top, spacing: 8) {
                        // 时间列（取后 8 位，即 HH:mm:ss）
                        Text(msg.time.suffix(8)).font(.caption2).foregroundStyle(.secondary)
                            .frame(width: 50, alignment: .trailing)
                        // 发言人列
                        Text(msg.speaker).font(.caption).foregroundStyle(.blue)
                            .frame(width: 60, alignment: .leading)
                        // 消息内容列（自适应宽度）
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

    // MARK: - 分析结果区

    /// 动作卡片结果列表。
    ///
    /// 每张卡片使用 `ActionCardView` 渲染，传入类型中文标签（`vm.typeLabel`）
    /// 以及确认/取消回调（`vm.confirm` / `vm.cancel`）。
    ///
    /// 分析中但卡片尚未返回时，仅显示「分析结果」标题。
    private var resultSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("分析结果").font(.headline)
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

    // MARK: - 洞察建议区

    /// AI 洞察/建议展示卡片。
    ///
    /// 视觉：黄色灯泡图标 + 洞察文本，浅灰背景圆角容器。
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

#Preview { ContentView() }
