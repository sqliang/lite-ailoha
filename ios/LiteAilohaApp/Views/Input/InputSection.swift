import SwiftUI
import PhotosUI

/// AI Native 输入区域 — 📎 附件按钮 + 文本 + 分析按钮。
struct InputSection: View {

    @Binding var imageData: Data?
    @Binding var supplementText: String
    let isAnalyzing: Bool
    let sessionState: String?
    let onAnalyze: () -> Void
    let onCancel: () -> Void

    @State private var pickerItem: PhotosPickerItem?
    @State private var showCamera = false
    @State private var showPhotoPicker = false

    var body: some View {
        VStack(spacing: 10) {
            // 输入栏
            HStack(spacing: 8) {
                // 📎 附件按钮 → Menu
                Menu {
                    Button { showPhotoPicker = true } label: {
                        Label("从相册选择", systemImage: "photo.on.rectangle")
                    }
                    Button { showCamera = true } label: {
                        Label("拍照", systemImage: "camera")
                    }
                    if imageData != nil {
                        Divider()
                        Button(role: .destructive) { imageData = nil } label: {
                            Label("移除截图", systemImage: "trash")
                        }
                    }
                } label: {
                    Image(systemName: imageData != nil ? "photo.fill" : "paperclip")
                        .font(.body)
                        .foregroundColor(imageData != nil ? .accentColor : .secondary)
                        .frame(width: 36, height: 36)
                }

                // 图片 chip
                if imageData != nil {
                    HStack(spacing: 4) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption2)
                            .foregroundColor(.green)
                        Text("截图已添加")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.quaternary, in: Capsule())
                }

                TextField("补充说明...", text: $supplementText, axis: .vertical)
                    .font(.body)
                    .lineLimit(1...4)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20))
            .photosPicker(isPresented: $showPhotoPicker, selection: $pickerItem, matching: .images)

            // 分析 / 停止 / 洞察中按钮
            if isAnalyzing {
                Button(action: onCancel) {
                    HStack(spacing: 8) {
                        Image(systemName: "stop.fill")
                        Text("Agent 分析中…")
                            .font(.headline)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 14)
                    .background(Color.red).foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                }
            } else if sessionState == "GENERATING" {
                Button(action: {}) {
                    HStack(spacing: 8) {
                        ProgressView().scaleEffect(0.8).tint(.white)
                        Text("正在生成洞察…")
                            .font(.headline)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 14)
                    .background(Color.orange).foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                }
                .disabled(true)
            } else {
                Button(action: onAnalyze) {
                    HStack(spacing: 8) {
                        Image(systemName: "sparkles")
                        Text("开始分析")
                            .font(.headline)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 14)
                    .background(canAnalyze ? Color.accentColor : Color(.systemGray4))
                    .foregroundStyle(canAnalyze ? .white : .secondary)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                }
                .disabled(!canAnalyze)
            }
        }
        .onChange(of: pickerItem) { _, newItem in
            Task {
                if let data = try? await newItem?.loadTransferable(type: Data.self) {
                    imageData = ImageProcessor().process(data)
                }
            }
        }
        .sheet(isPresented: $showCamera) { CameraPicker(imageData: $imageData) }
    }

    private var canAnalyze: Bool {
        imageData != nil
    }
}
