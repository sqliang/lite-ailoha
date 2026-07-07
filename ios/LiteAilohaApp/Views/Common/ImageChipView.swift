import SwiftUI

/// 图片附件 Chip — 紧凑展示已选图片，点击可查看/删除/更换。
struct ImageChipView: View {

    let imageData: Data?
    let onSelectPhoto: () -> Void
    let onTakePhoto: () -> Void
    let onRemove: () -> Void

    @State private var showPreview = false

    var body: some View {
        if let data = imageData, let uiImage = UIImage(data: data) {
            // 已选图片：显示 chip
            HStack(spacing: 8) {
                Button { showPreview = true } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "photo.fill")
                            .font(.caption)
                        Text("已选截图")
                            .font(.subheadline)
                        Image(systemName: "chevron.right")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(.quaternary, in: Capsule())
                }
                .buttonStyle(.plain)

                Button(action: onRemove) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .sheet(isPresented: $showPreview) {
                NavigationStack {
                    VStack {
                        Image(uiImage: uiImage)
                            .resizable()
                            .scaledToFit()
                            .padding()
                    }
                    .navigationTitle("截图预览")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("完成") { showPreview = false }
                        }
                    }
                }
            }
        } else {
            // 未选图片：显示选择按钮
            HStack(spacing: 16) {
                Button(action: onSelectPhoto) {
                    Label("相册", systemImage: "photo.on.rectangle")
                        .font(.subheadline)
                }
                .buttonStyle(.bordered)

                Button(action: onTakePhoto) {
                    Label("拍照", systemImage: "camera")
                        .font(.subheadline)
                }
                .buttonStyle(.bordered)
            }
        }
    }
}
