import SwiftUI
import UIKit

// MARK: - 系统相机/相册拍照组件
///
/// 使用 `UIImagePickerController` 封装系统拍照功能，
/// 通过 `UIViewControllerRepresentable` 桥接到 SwiftUI。

/// 系统相机拍照组件，将拍摄的照片以 JPEG Data 形式回传。
///
/// 使用方式：
/// ```swift
/// @State private var imageData: Data?
/// @State private var showCamera = false
///
/// .sheet(isPresented: $showCamera) {
///     CameraPicker(imageData: $imageData)
/// }
/// ```
///
/// - Note: 若设备不支持相机（如模拟器），自动降级为相册选择。
/// - Note: 照片以 JPEG 格式压缩至 80% 质量后回传。
struct CameraPicker: UIViewControllerRepresentable {
    /// 拍摄/选择的照片数据（JPEG 格式，压缩质量 0.8）
    @Binding var imageData: Data?
    /// SwiftUI 环境值：用于在选取完成后关闭 Sheet
    @Environment(\.dismiss) private var dismiss

    // MARK: - UIViewControllerRepresentable

    /// 创建 UIImagePickerController 实例并配置为相机模式。
    ///
    /// 若设备不支持相机（如模拟器），自动降级为相册选择模式。
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        // 检测设备是否支持相机：支持则用相机，否则降级为相册
        picker.sourceType = UIImagePickerController.isSourceTypeAvailable(.camera) ? .camera : .photoLibrary
        picker.delegate = context.coordinator
        return picker
    }

    /// SwiftUI 更新回调（无需更新，留空）
    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    /// 创建协调器实例，负责处理 UIImagePickerController 的回调事件
    func makeCoordinator() -> Coordinator { Coordinator(self) }

    // MARK: - 协调器

    /// UIKit 与 SwiftUI 之间的桥接协调器。
    ///
    /// 遵循 `UIImagePickerControllerDelegate` 处理照片选取结果，
    /// 遵循 `UINavigationControllerDelegate` 满足 UIImagePickerController 要求。
    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        /// 持有父组件引用，用于回传数据
        let parent: CameraPicker
        init(_ parent: CameraPicker) { self.parent = parent }

        /// 用户选取照片后的回调。
        ///
        /// 将原始 UIImage 转换为 JPEG Data（压缩质量 0.8），
        /// 写入父组件的 `imageData` 绑定，并关闭 Sheet。
        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage {
                // JPEG 压缩：平衡图片质量与网络传输大小
                parent.imageData = image.jpegData(compressionQuality: 0.8)
            }
            parent.dismiss()
        }

        /// 用户取消选取后的回调：直接关闭 Sheet
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            parent.dismiss()
        }
    }
}