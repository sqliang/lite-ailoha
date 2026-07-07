import SwiftUI
import CoreData

// MARK: - 应用入口
///
/// LiteAilohaApp — 智能截图分析 App
///
/// 应用启动时通过本入口注入 Core Data 依赖：
/// - 将 PersistenceController 的 viewContext 写入 SwiftUI 环境，
///   使所有子视图可通过 `@Environment(\.managedObjectContext)` 访问。
///
/// 核心功能：
/// 1. 用户选择截图（相册/拍照）或输入补充文字
/// 2. 点击"开始分析"后通过 SSE 流式接收 AI 分析结果
/// 3. 结果以可交互的动作卡片展示，支持确认/取消
/// 4. 确认的卡片持久化到 Core Data

@main
struct ActionCardsApp: App {
    /// 全局持久化控制器单例
    let persistence = PersistenceController.shared

    var body: some Scene {
        WindowGroup {
            AnalysisView()
                // 将 Core Data 托管上下文注入环境，供子视图持久化使用
                .environment(\.managedObjectContext, persistence.container.viewContext)
        }
    }
}