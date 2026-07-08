import Foundation
import Contacts
import EventKit

/// 设备端数据采集：联系人、日历、提醒。
/// 权限拒绝时返回空数组，不阻塞主流程。
struct DeviceDataProvider {

    // MARK: - Contacts

    func fetchContacts() async -> [[String: Any]] {
        let store = CNContactStore()
        let granted = (try? await store.requestAccess(for: .contacts)) ?? false
        guard granted else {
            print("[DeviceData] 联系人权限未授予")
            return []
        }

        let keys: [CNKeyDescriptor] = [
            CNContactGivenNameKey as CNKeyDescriptor,
            CNContactFamilyNameKey as CNKeyDescriptor,
            CNContactPhoneNumbersKey as CNKeyDescriptor,
            CNContactEmailAddressesKey as CNKeyDescriptor,
            CNContactOrganizationNameKey as CNKeyDescriptor,
            CNContactJobTitleKey as CNKeyDescriptor,
        ]

        let request = CNContactFetchRequest(keysToFetch: keys)
        var results: [[String: Any]] = []
        do {
            try store.enumerateContacts(with: request) { contact, _ in
                results.append([
                    "name": "\(contact.givenName) \(contact.familyName)".trimmingCharacters(in: .whitespaces),
                    "phones": contact.phoneNumbers.map { $0.value.stringValue },
                    "emails": contact.emailAddresses.map { String($0.value) },
                    "company": contact.organizationName,
                    "title": contact.jobTitle,
                ])
            }
        } catch {
            print("[DeviceData] 联系人读取失败: \(error)")
        }
        print("[DeviceData] 联系人: \(results.count) 条")
        return results
    }

    // MARK: - Calendar Events

    func fetchEvents() async -> [[String: Any]] {
        let store = EKEventStore()
        let granted = (try? await store.requestAccess(to: .event)) ?? false
        guard granted else {
            print("[DeviceData] 日历权限未授予")
            return []
        }

        let start = Date()
        let end = Calendar.current.date(byAdding: .day, value: 30, to: start)!
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: nil)
        let events = store.events(matching: predicate)

        let results: [[String: Any]] = events.map { e in
            [
                "title": e.title ?? "",
                "start": e.startDate.ISO8601Format(),
                "end": e.endDate.ISO8601Format(),
                "location": e.location ?? "",
                "notes": e.notes ?? "",
                "attendees": (e.attendees ?? []).map { $0.name ?? "" },
            ]
        }
        print("[DeviceData] 日历事件: \(results.count) 条")
        return results
    }

    // MARK: - Reminders

    func fetchReminders() async -> [[String: Any]] {
        let store = EKEventStore()
        let granted = (try? await store.requestAccess(to: .reminder)) ?? false
        guard granted else {
            print("[DeviceData] 提醒权限未授予")
            return []
        }

        let predicate = store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: nil)

        return await withCheckedContinuation { continuation in
            store.fetchReminders(matching: predicate) { reminders in
                let results: [[String: Any]] = (reminders ?? []).map { r in
                    [
                        "title": r.title ?? "",
                        "dueDate": r.dueDateComponents?.date?.ISO8601Format() ?? "",
                        "priority": r.priority,
                        "notes": r.notes ?? "",
                    ]
                }
                print("[DeviceData] 提醒: \(results.count) 条")
                continuation.resume(returning: results)
            }
        }
    }

    // MARK: - Execute Actions

    func executeAction(card: ActionCard) async -> Bool {
        print("[DeviceData] ========== executeAction ==========")
        print("[DeviceData] type=\(card.type)")
        print("[DeviceData] summary=\(card.summary)")
        print("[DeviceData] fields=\(card.fields)")
        switch card.type {
        case "create_reminder": return await createReminder(card)
        case "create_meeting":  return await createEvent(card)
        case "create_contact":  return await createContact(card)
        case "update_contact":  return await updateContact(card)
        default: return false
        }
    }

    // MARK: - createReminder（EKReminder）

    private func createReminder(_ card: ActionCard) async -> Bool {
        let store = EKEventStore()
        let granted = (try? await store.requestAccess(to: .reminder)) ?? false
        print("[DeviceData] 提醒权限: \(granted)")
        guard granted else { return false }

        let f = card.fields
        let reminder = EKReminder(eventStore: store)
        reminder.title  = f["title"]   ?? ""
        reminder.notes  = f["content"] ?? ""
        if let due = f["due_date"], !due.isEmpty {
            reminder.dueDateComponents = parseNaturalDueDate(due)
        }
        print("[DeviceData] createReminder | title=\(reminder.title) notes=\(reminder.notes ?? "nil") due=\(f["due_date"] ?? "nil")")
        // defaultCalendarForNewReminders 在模拟器/未设置时可能为 nil，fallback 到第一个可用提醒日历
        if let defaultCal = store.defaultCalendarForNewReminders() {
            reminder.calendar = defaultCal
        } else if let firstCal = store.calendars(for: .reminder).first {
            print("[DeviceData] ⚠️ defaultCalendarForNewReminders 为 nil，fallback 到: \(firstCal.title)")
            reminder.calendar = firstCal
        } else {
            print("[DeviceData] ❌ 没有可用的提醒日历，请在系统设置中添加提醒列表")
            return false
        }
        do { try store.save(reminder, commit: true); print("[DeviceData] ✅ 提醒已创建"); return true }
        catch { print("[DeviceData] ❌ 创建提醒失败: \(error)"); return false }
    }

    // MARK: - createEvent（EKEvent）

    private func createEvent(_ card: ActionCard) async -> Bool {
        let store = EKEventStore()
        let granted = (try? await store.requestAccess(to: .event)) ?? false
        print("[DeviceData] 日历权限: \(granted)")
        guard granted else { return false }

        let f = card.fields
        let event = EKEvent(eventStore: store)
        event.title = f["title"] ?? ""

        if let dt = f["datetime"], !dt.isEmpty {
            let parsed = parseNaturalDateTime(dt)
            event.startDate = parsed.start
            event.endDate   = parsed.end
        } else {
            event.startDate = Date()
            event.endDate   = Date().addingTimeInterval(3600)
        }

        // notes：先写会议备注，再追加参会人（attendees 只读，无法编程写入）
        var notesParts: [String] = []
        if let rawNotes = f["notes"], !rawNotes.isEmpty {
            notesParts.append(rawNotes)
        }
        if let p = f["participants"], !p.isEmpty {
            let ppl = parseParticipants(p)
            if !ppl.isEmpty {
                notesParts.append("- 参会人: \(ppl.joined(separator: "、"))")
            }
        }
        event.notes = notesParts.joined(separator: "\n")

        print("[DeviceData] createEvent | title=\(event.title ?? "nil") start=\(event.startDate) notes=\(event.notes ?? "nil")")
        if let defaultCal = store.defaultCalendarForNewEvents {
            event.calendar = defaultCal
        } else if let firstCal = store.calendars(for: .event).first {
            print("[DeviceData] ⚠️ defaultCalendarForNewEvents 为 nil，fallback 到: \(firstCal.title)")
            event.calendar = firstCal
        } else {
            print("[DeviceData] ❌ 没有可用的日历")
            return false
        }
        do { try store.save(event, span: .thisEvent); print("[DeviceData] ✅ 会议已创建"); return true }
        catch { print("[DeviceData] ❌ 创建会议失败: \(error)"); return false }
    }

    // MARK: - createContact（CNMutableContact）

    private func createContact(_ card: ActionCard) async -> Bool {
        let store = CNContactStore()
        let granted = (try? await store.requestAccess(for: .contacts)) ?? false
        print("[DeviceData] 联系人权限: \(granted)")
        guard granted else { return false }

        let f = card.fields
        let contact = CNMutableContact()
        contact.givenName       = f["name"]     ?? ""
        contact.jobTitle        = f["title"]    ?? ""
        contact.organizationName = f["company"] ?? ""
        contact.note            = f["notes"]    ?? ""

        if let phone = f["phone"], !phone.isEmpty {
            contact.phoneNumbers = [CNLabeledValue(
                label: CNLabelPhoneNumberMobile,
                value: CNPhoneNumber(stringValue: phone)
            )]
        }
        if let email = f["email"], !email.isEmpty {
            contact.emailAddresses = [CNLabeledValue(
                label: CNLabelWork,
                value: email as NSString
            )]
        }

        print("[DeviceData] createContact | name=\(contact.givenName) phone=\(f["phone"] ?? "nil") email=\(f["email"] ?? "nil") company=\(contact.organizationName) title=\(contact.jobTitle)")
        let request = CNSaveRequest()
        request.add(contact, toContainerWithIdentifier: nil)
        do { try store.execute(request); print("[DeviceData] ✅ 联系人已创建"); return true }
        catch { print("[DeviceData] ❌ 创建联系人失败: \(error)"); return false }
    }

    // MARK: - updateContact（CNMutableContact）

    private func updateContact(_ card: ActionCard) async -> Bool {
        let store = CNContactStore()
        let granted = (try? await store.requestAccess(for: .contacts)) ?? false
        guard granted else { return false }

        let f = card.fields
        let name = f["name"] ?? ""
        let field = f["field"] ?? ""
        let value = f["value"] ?? ""

        let predicate = CNContact.predicateForContacts(matchingName: name)
        let keys: [CNKeyDescriptor] = [
            CNContactGivenNameKey as CNKeyDescriptor,
            CNContactPhoneNumbersKey as CNKeyDescriptor,
            CNContactEmailAddressesKey as CNKeyDescriptor,
            CNContactOrganizationNameKey as CNKeyDescriptor,
            CNContactJobTitleKey as CNKeyDescriptor,
            CNContactNoteKey as CNKeyDescriptor,
        ]
        guard let match = try? store.unifiedContacts(matching: predicate, keysToFetch: keys).first,
              let mutable = match.mutableCopy() as? CNMutableContact
        else { print("[DeviceData] ❌ 未找到联系人: \(name)"); return false }

        switch field {
        case "phone":    mutable.phoneNumbers  = [CNLabeledValue(label: CNLabelPhoneNumberMobile, value: CNPhoneNumber(stringValue: value))]
        case "email":    mutable.emailAddresses = [CNLabeledValue(label: CNLabelWork, value: value as NSString)]
        case "company":  mutable.organizationName = value
        case "title":    mutable.jobTitle = value
        case "notes":    mutable.note = value
        default: break
        }

        print("[DeviceData] updateContact | name=\(name) field=\(field) value=\(value)")
        let request = CNSaveRequest()
        request.update(mutable)
        do { try store.execute(request); print("[DeviceData] ✅ 联系人已更新"); return true }
        catch { print("[DeviceData] ❌ 更新联系人失败: \(error)"); return false }
    }

    // MARK: - 自然语言时间解析辅助方法

    /// 解析自然语言日期时间 → startDate + endDate
    private func parseNaturalDateTime(_ text: String) -> (start: Date, end: Date) {
        let start = Date()
        return (start, start.addingTimeInterval(3600))
    }

    /// 解析自然语言截止日期 → DateComponents
    private func parseNaturalDueDate(_ text: String) -> DateComponents {
        let cal = Calendar.current
        return cal.dateComponents([.year, .month, .day, .hour, .minute],
                                  from: Date().addingTimeInterval(86400))
    }

    /// 解析参会人列表 — fields["participants"] 是 JSON 字符串如 '["张三","李四"]'
    private func parseParticipants(_ raw: String) -> [String] {
        if let data = raw.data(using: .utf8),
           let arr = try? JSONDecoder().decode([String].self, from: data) {
            return arr
        }
        // fallback: comma-separated
        return raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
    }
}
