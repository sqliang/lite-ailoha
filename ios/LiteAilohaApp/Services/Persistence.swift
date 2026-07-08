import CoreData

// MARK: - Core Data 持久化栈
///
/// 本文件以纯代码方式构建 Core Data 模型并管理持久化容器，
/// 不依赖 `.xcdatamodeld` 文件，方便项目直接导入和版本管理。
///
/// 数据模型仅包含一个实体：
/// - SavedCard：用户确认后的动作卡片持久化记录

// MARK: - 持久化控制器

/// 全局单例持久化控制器，管理 Core Data 容器及其托管上下文。
///
/// 使用方式：
/// ```swift
/// let context = PersistenceController.shared.container.viewContext
/// ```
struct PersistenceController {
    /// 全局共享实例
    static let shared = PersistenceController()

    /// 持久化容器，持有托管对象模型和持久化存储协调器
    let container: NSPersistentContainer

    /// 初始化持久化栈。
    ///
    /// - Parameter inMemory: 为 `true` 时使用内存存储（`/dev/null`），
    ///   用于单元测试或 SwiftUI Preview，数据不会写入磁盘。
    init(inMemory: Bool = false) {
        // 使用自定义托管对象模型创建容器
        container = NSPersistentContainer(name: "ActionCards", managedObjectModel: Self.model)
        if inMemory {
            // 内存模式：将 SQLite 文件指向 /dev/null，数据仅存于内存
            container.persistentStoreDescriptions.first?.url = URL(fileURLWithPath: "/dev/null")
        }
        // 加载持久化存储
        container.loadPersistentStores { _, error in
            if let error = error { fatalError("Core Data 加载失败: \(error)") }
        }
        // 开启自动合并：父上下文变更会自动同步到 viewContext
        container.viewContext.automaticallyMergesChangesFromParent = true
    }

    /// 以代码方式构建托管对象模型，避免依赖 .xcdatamodeld 文件。
    ///
    /// 定义一个实体 `SavedCard`，包含以下属性：
    /// - id (String, 必填)：卡片唯一标识
    /// - type (String, 可选)：动作类型
    /// - summary (String, 可选)：动作摘要
    /// - status (String, 可选)：确认状态
    /// - createdAt (Date, 可选)：确认时间
    ///
    /// - Warning: 使用 `nonisolated(unsafe)` 标记，因为 NSManagedObjectModel 未能自动
    ///   遵循 Sendable 协议。该模型在构造后即不可变（Core Data 在使用后将其锁定），
    ///   因此并发访问是安全的。
    nonisolated(unsafe) static let model: NSManagedObjectModel = {
        let model = NSManagedObjectModel()

        // 创建 SavedCard 实体描述
        let entity = NSEntityDescription()
        entity.name = "SavedCard"
        // 使用 NSStringFromClass 确保类名包含模块前缀，避免运行时找不到类
        entity.managedObjectClassName = NSStringFromClass(SavedCard.self)

        /// 便捷方法：创建属性描述
        func attr(_ name: String, _ type: NSAttributeType, optional: Bool = true) -> NSAttributeDescription {
            let a = NSAttributeDescription()
            a.name = name
            a.attributeType = type
            a.isOptional = optional
            return a
        }

        // 定义实体属性列表
        entity.properties = [
            attr("id", .stringAttributeType, optional: false),   // 主键，必填
            attr("type", .stringAttributeType),
            attr("summary", .stringAttributeType),
            attr("fields", .stringAttributeType),
            attr("status", .stringAttributeType),
            attr("createdAt", .dateAttributeType)
        ]

        model.entities = [entity]
        return model
    }()
}

// MARK: - 持久化实体

/// 已确认动作卡片的 Core Data 持久化记录。
///
/// 当用户在分析结果中点击"确认"按钮时，对应的 ActionCard 会被转换为 SavedCard
/// 并存入 Core Data，用于后续历史查询和统计分析。
///
/// - Note: 使用 `@objc(SavedCard)` 确保 Objective-C 运行时能正确解析类名。
@objc(SavedCard)
final class SavedCard: NSManagedObject {
    /// 卡片唯一标识（对应 ActionCard.id）
    @NSManaged var id: String
    /// 动作类型（对应 ActionCard.type）
    @NSManaged var type: String?
    /// 动作摘要（对应 ActionCard.summary）
    @NSManaged var summary: String?
    /// 结构化字段（对应 ActionCard.fields，JSON 字符串）
    @NSManaged var fields: String?
    /// 确认状态（通常为 CardStatus.confirmed.rawValue）
    @NSManaged var status: String?
    /// 用户确认的时间戳
    @NSManaged var createdAt: Date?
}

// MARK: - 抓取请求

extension SavedCard {
    /// 创建针对 SavedCard 实体的 NSFetchRequest。
    ///
    /// 使用示例：
    /// ```swift
    /// let request = SavedCard.fetchRequest()
    /// request.sortDescriptors = [NSSortDescriptor(key: "createdAt", ascending: false)]
    /// let results = try context.fetch(request)
    /// ```
    static func fetchRequest() -> NSFetchRequest<SavedCard> {
        NSFetchRequest<SavedCard>(entityName: "SavedCard")
    }
}