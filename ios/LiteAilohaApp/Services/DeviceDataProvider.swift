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
        print("[DeviceData] executeAction type=\(card.type) summary=\(card.summary)")
        switch card.type {
        case "create_reminder": return await createReminder(card)
        case "create_meeting":  return await createEvent(card)
        case "create_contact", "update_contact": return await createContact(card)
        default: return false
        }
    }

    private func createReminder(_ card: ActionCard) async -> Bool {
        let store = EKEventStore()
        let granted = (try? await store.requestAccess(to: .reminder)) ?? false
        print("[DeviceData] 提醒权限: \(granted)")
        guard granted else { return false }
        let reminder = EKReminder(eventStore: store)
        reminder.title = card.summary
        reminder.calendar = store.defaultCalendarForNewReminders()
        do { try store.save(reminder, commit: true); print("[DeviceData] ✅ 提醒已创建"); return true }
        catch { print("[DeviceData] ❌ 创建提醒失败: \(error)"); return false }
    }

    private func createEvent(_ card: ActionCard) async -> Bool {
        let store = EKEventStore()
        let granted = (try? await store.requestAccess(to: .event)) ?? false
        print("[DeviceData] 日历权限: \(granted)")
        guard granted else { return false }
        let event = EKEvent(eventStore: store)
        event.title = card.summary
        event.startDate = Date()
        event.endDate = Date().addingTimeInterval(3600)
        event.calendar = store.defaultCalendarForNewEvents
        do { try store.save(event, span: .thisEvent); print("[DeviceData] ✅ 会议已创建"); return true }
        catch { print("[DeviceData] ❌ 创建会议失败: \(error)"); return false }
    }

    private func createContact(_ card: ActionCard) async -> Bool {
        let store = CNContactStore()
        let granted = (try? await store.requestAccess(for: .contacts)) ?? false
        print("[DeviceData] 联系人权限: \(granted)")
        guard granted else { return false }
        let contact = CNMutableContact()
        contact.givenName = card.summary
        let request = CNSaveRequest()
        request.add(contact, toContainerWithIdentifier: nil)
        do { try store.execute(request); print("[DeviceData] ✅ 联系人已创建"); return true }
        catch { print("[DeviceData] ❌ 创建联系人失败: \(error)"); return false }
    }
}
