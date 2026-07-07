import SwiftUI
import PhotosUI

/// 输入区域：图片选择 + 补充文字 + 分析按钮。
struct InputSection: View {

    @Binding var imageData: Data?
    @Binding var supplementText: String
    let isAnalyzing: Bool
    let onAnalyze: () -> Void

    @State private var pickerItem: PhotosPickerItem?
    @State private var showCamera = false

    var body: some View {
        VStack(spacing: 16) {
            // 图片预览
            if let data = imageData, let uiImage = UIImage(data: data) {
                Image(uiImage: uiImage)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }

            // 相册 + 拍照双入口
            HStack(spacing: 12) {
                PhotosPicker(selection: $pickerItem, matching: .images) {
                    Label("相册", systemImage: "photo.on.rectangle")
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                Button { showCamera = true } label: {
                    Label("拍照", systemImage: "camera")
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
            }

            // 补充说明
            VStack(alignment: .leading, spacing: 8) {
                Text("补充说明").font(.subheadline).foregroundStyle(.secondary)
                TextEditor(text: $supplementText)
                    .frame(height: 60).padding(8)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }

            // 分析按钮
            Button(action: onAnalyze) {
                HStack {
                    if isAnalyzing {
                        ProgressView().tint(.white)
                    }
                    Text(isAnalyzing ? "分析中…" : "开始分析")
                }
                .font(.headline)
                .frame(maxWidth: .infinity).padding(.vertical, 14)
                .background(isAnalyzing ? Color.gray : Color.accentColor)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .disabled(isAnalyzing)
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
}
