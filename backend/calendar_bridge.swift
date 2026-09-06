import EventKit
import Foundation

struct CalendarInfo: Encodable {
    let title: String
    let sourceTitle: String
    let sourceType: String
}

struct EventSpec: Decodable {
    let calendarName: String
    let title: String
    let start: String
    let end: String
    let notes: String
    let alarms: [String]
    let existingIdentifier: String?
    let recurrence: String?
}

struct BridgeResult: Encodable {
    let ok: Bool
    let calendars: [CalendarInfo]?
    let identifier: String?
    let error: String?
}

func sourceTypeName(_ type: EKSourceType) -> String {
    switch type {
    case .local: return "local"
    case .exchange: return "exchange"
    case .calDAV: return "calDAV"
    case .mobileMe: return "mobileMe"
    case .subscribed: return "subscribed"
    case .birthdays: return "birthdays"
    @unknown default: return "unknown"
    }
}

func isICloudCalendar(_ calendar: EKCalendar) -> Bool {
    guard let source = calendar.source else { return false }
    let sourceTitle = source.title.lowercased()
    return source.sourceType == .calDAV && (sourceTitle.contains("icloud") || sourceTitle.contains("账户") || sourceTitle.contains("account"))
}

func emit(_ result: BridgeResult) -> Never {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    if let data = try? encoder.encode(result), let text = String(data: data, encoding: .utf8) {
        print(text)
    } else {
        print("{\"ok\":false,\"error\":\"无法编码日历桥接结果\"}")
    }
    exit(result.ok ? 0 : 1)
}

func requestAccess(_ store: EKEventStore) {
    let sem = DispatchSemaphore(value: 0)
    var granted = false
    var accessError: Error?
    let completion: @convention(block) (Bool, Error?) -> Void = { ok, error in
        granted = ok
        accessError = error
        sem.signal()
    }
    // The project is intentionally compiled against an older macOS SDK.  Look
    // up the macOS 14 API at runtime so newer systems receive the explicit
    // full-access request while older systems keep using the legacy API.
    let fullAccessSelector = NSSelectorFromString("requestFullAccessToEventsWithCompletion:")
    if store.responds(to: fullAccessSelector), let implementation = store.method(for: fullAccessSelector) {
        typealias FullAccessRequest = @convention(c) (AnyObject, Selector, @escaping @convention(block) (Bool, Error?) -> Void) -> Void
        let request = unsafeBitCast(implementation, to: FullAccessRequest.self)
        request(store, fullAccessSelector, completion)
    } else {
        store.requestAccess(to: .event) { ok, error in
            granted = ok
            accessError = error
            sem.signal()
        }
    }
    sem.wait()
    if !granted {
        emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: accessError?.localizedDescription ?? "未获得日历访问权限，请在系统设置中允许本应用访问日历"))
    }
}

func parseDate(_ value: String) -> Date? {
    let iso = ISO8601DateFormatter()
    iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = iso.date(from: value) {
        return date
    }
    iso.formatOptions = [.withInternetDateTime]
    if let date = iso.date(from: value) {
        return date
    }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone.current
    for format in ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm"] {
        formatter.dateFormat = format
        if let date = formatter.date(from: value) {
            return date
        }
    }
    return nil
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: "缺少日历桥接命令"))
}

let store = EKEventStore()
requestAccess(store)

let command = args[1]
let calendars = store.calendars(for: .event)
let iCloudCalendars = calendars.filter(isICloudCalendar)

if command == "list" {
    let infos = iCloudCalendars
        .sorted { (($0.source?.title ?? ""), $0.title) < (($1.source?.title ?? ""), $1.title) }
        .map { CalendarInfo(title: $0.title, sourceTitle: $0.source?.title ?? "", sourceType: sourceTypeName($0.source?.sourceType ?? .local)) }
    emit(BridgeResult(ok: true, calendars: infos, identifier: nil, error: nil))
}

if command == "delete" {
    guard args.count >= 3 else {
        emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: "缺少要删除的日历事件标识"))
    }
    let identifier = args[2]
    if let event = store.event(withIdentifier: identifier) {
        do {
            try store.remove(event, span: .futureEvents, commit: true)
            emit(BridgeResult(ok: true, calendars: nil, identifier: identifier, error: nil))
        } catch {
            emit(BridgeResult(ok: false, calendars: nil, identifier: identifier, error: error.localizedDescription))
        }
    }
    emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: "未找到日历事件"))
}

if command == "upsert" {
    guard args.count >= 3 else {
        emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: "缺少日历事件 JSON 文件"))
    }
    do {
        let data = try Data(contentsOf: URL(fileURLWithPath: args[2]))
        let spec = try JSONDecoder().decode(EventSpec.self, from: data)
        guard let calendar = iCloudCalendars.first(where: { $0.title == spec.calendarName }) else {
            let available = iCloudCalendars.map { $0.title }.joined(separator: "、")
            emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: "未在 iCloud 分组下找到名为“\(spec.calendarName)”的日历。当前可用 iCloud 日历：\(available.isEmpty ? "无" : available)"))
        }
        guard let startDate = parseDate(spec.start), let endDate = parseDate(spec.end) else {
            emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: "日历事件时间格式无法识别"))
        }
        if let oldIdentifier = spec.existingIdentifier, !oldIdentifier.isEmpty, let oldEvent = store.event(withIdentifier: oldIdentifier) {
            try? store.remove(oldEvent, span: .futureEvents, commit: true)
        }
        let event = EKEvent(eventStore: store)
        event.calendar = calendar
        event.title = spec.title
        event.startDate = startDate
        event.endDate = endDate
        event.notes = spec.notes
        event.alarms = spec.alarms.compactMap { value in
            guard let alarmDate = parseDate(value) else { return nil }
            return EKAlarm(absoluteDate: alarmDate)
        }
        if let recurrence = spec.recurrence {
            let rule: EKRecurrenceRule?
            switch recurrence {
            case "weekly":
                rule = EKRecurrenceRule(recurrenceWith: .weekly, interval: 1, end: nil)
            case "semimonthly":
                rule = EKRecurrenceRule(recurrenceWith: .daily, interval: 15, end: nil)
            case "monthly":
                rule = EKRecurrenceRule(recurrenceWith: .monthly, interval: 1, end: nil)
            case "bimonthly":
                rule = EKRecurrenceRule(recurrenceWith: .monthly, interval: 2, end: nil)
            case "quarterly":
                rule = EKRecurrenceRule(recurrenceWith: .monthly, interval: 3, end: nil)
            case "semiannual":
                rule = EKRecurrenceRule(recurrenceWith: .monthly, interval: 6, end: nil)
            default:
                rule = nil
            }
            if let rule = rule { event.addRecurrenceRule(rule) }
        }
        try store.save(event, span: .thisEvent, commit: true)
        emit(BridgeResult(ok: true, calendars: nil, identifier: event.eventIdentifier, error: nil))
    } catch {
        emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: error.localizedDescription))
    }
}

emit(BridgeResult(ok: false, calendars: nil, identifier: nil, error: "未知日历桥接命令：\(command)"))
