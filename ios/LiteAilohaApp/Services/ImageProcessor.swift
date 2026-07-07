import Foundation
import UIKit

// MARK: - 图片预处理工具
///
/// 在 OCR 识别之前对图片进行缩放处理。
///
/// **为什么要预处理？**
/// - 全分辨率照片（4000×3000px）对 OCR 没有额外收益
///   ——聊天截图的文字在 1024px 宽度下已完全清晰可辨
/// - 缩小图片可显著降低 Vision 的处理时间（从 >2s 降至 <0.5s）
/// - 减少内存占用，避免在低端设备上触发内存压力
///
/// **API：**
/// - `resize(image:) -> UIImage` — OCR 推荐使用，直接返回 UIImage，
///   跳过 JPEG 编解码，避免 `fopen failed for data file`
/// - `process(_:) -> Data` — 返回 JPEG Data，用于网络传输等场景

struct ImageProcessor {

    /// OCR 预处理的最大边长（像素）
    static let maxDimension: CGFloat = 1024

    /// JPEG 压缩质量
    static let compressionQuality: CGFloat = 0.7

    // MARK: - OCR 专用：返回 UIImage（不经过 JPEG）

    /// 缩放图片到 OCR 友好尺寸，直接返回 UIImage。
    ///
    /// 与 `process()` 的关键区别：不经过 JPEG 编解码，避免 ImageIO
    /// 创建临时文件导致后续 Vision 处理时 `fopen` 失败。
    ///
    /// - Parameter image: 原始 UIImage
    /// - Returns: 缩放后的 UIImage（长边 ≤ 1024px）
    func resize(image: UIImage) -> UIImage {
        let originalSize = image.size
        let maxSide = max(originalSize.width, originalSize.height)

        // 已经足够小，直接返回
        guard maxSide > ImageProcessor.maxDimension else {
            return image
        }

        let scale = ImageProcessor.maxDimension / maxSide
        let newSize = CGSize(
            width: originalSize.width * scale,
            height: originalSize.height * scale
        )

        // UIGraphicsImageRenderer 是 iOS 10+ 的现代 API，
        // 内部使用更可靠的内存管理，渲染结果不会引用临时文件
        let renderer = UIGraphicsImageRenderer(size: newSize)
        return renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: newSize))
        }
    }

    // MARK: - 网络/存储用：返回 JPEG Data

    /// 对图片数据进行缩放 + JPEG 压缩，返回处理后的 Data。
    ///
    /// - Parameter imageData: 原始图片数据（来自相册或相机）
    /// - Returns: 预处理后的 JPEG 数据
    func process(_ imageData: Data) -> Data {
        // 快速路径
        if imageData.count < 200_000 { return imageData }

        guard let uiImage = UIImage(data: imageData) else {
            return imageData
        }

        let maxSide = max(uiImage.size.width, uiImage.size.height)

        if maxSide <= ImageProcessor.maxDimension && imageData.count < 500_000 {
            return imageData
        }

        let resized = resize(image: uiImage)
        return resized.jpegData(compressionQuality: ImageProcessor.compressionQuality) ?? imageData
    }
}
