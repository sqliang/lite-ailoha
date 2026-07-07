import SwiftUI

/// 卡片类型 → UI 映射工具。
///
/// 从 AnalysisViewModel 中提取，纯函数无状态。
enum CardIconHelper {

    /// 根据卡片类型返回对应的 SF Symbol 图标名称。
    static func icon(for type: String) -> String {
        switch type {
        case "create_meeting": return "calendar.badge.plus"
        case "create_contact": return "person.crop.circle.badge.plus"
        case "update_contact": return "person.text.rectangle"
        case "create_reminder": return "bell.badge"
        default: return "square.and.pencil"
        }
    }

    /// 根据卡片类型返回中文标签。
    static func label(for type: String) -> String {
        switch type {
        case "create_meeting": return "创建会议"
        case "create_contact": return "创建联系人"
        case "update_contact": return "更新联系人"
        case "create_reminder": return "创建提醒"
        default: return "动作"
        }
    }
}
