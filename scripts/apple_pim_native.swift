// Compile with: swiftc -swift-version 5 -parse-as-library apple_pim_native.swift -o calendar-cli
// Install the same executable as reminder-cli in a separate private adapter directory.
import Foundation
import EventKit
import CoreLocation
import CryptoKit
import MapKit
import CoreFoundation

enum BridgeError: String, Error {
    case invalid_fields, item_not_found, revision_conflict, read_only
    case unsupported_capability, verification_failed, receiver_unavailable
    case route_unavailable, ambiguous_destination, location_stale
}

let store = EKEventStore()
let iso = ISO8601DateFormatter()
var privateStage = ""
var privateWriteStarted: Bool?

func drivingEstimate(_ fields: [String: Any]) async throws -> [String: Any] {
    guard let origin = fields["origin"] as? [String: Any], let latitude = origin["latitude"] as? Double,
          let longitude = origin["longitude"] as? Double, latitude.isFinite, longitude.isFinite,
          (-90...90).contains(latitude), (-180...180).contains(longitude) else { throw BridgeError.invalid_fields }
    let observed = try date(origin["observed_at"])
    guard (-30...300).contains(Date().timeIntervalSince(observed)) else { throw BridgeError.location_stale }
    let destination = try string(fields["destination"])
    let places = try await CLGeocoder().geocodeAddressString(destination)
    guard places.count == 1, let place = places.first, let location = place.location,
          location.horizontalAccuracy <= 1000, place.thoroughfare != nil || !(place.areasOfInterest ?? []).isEmpty else {
        throw BridgeError.ambiguous_destination
    }
    let request = MKDirections.Request()
    request.source = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: latitude, longitude: longitude)))
    request.destination = MKMapItem(placemark: MKPlacemark(coordinate: location.coordinate))
    request.transportType = .automobile
    request.arrivalDate = try date(fields["arrival_at"])
    let eta = try await MKDirections(request: request).calculateETA()
    let seconds = Int(ceil(eta.expectedTravelTime))
    guard seconds > 0 && seconds <= 604800 else { throw BridgeError.route_unavailable }
    return ["seconds": seconds, "computed_at": iso.string(from: Date()), "origin_observed_at": iso.string(from: observed),
            "latitude": location.coordinate.latitude, "longitude": location.coordinate.longitude, "destination": destination]
}

func date(_ value: Any?) throws -> Date {
    guard let value = value as? String else { throw BridgeError.invalid_fields }
    if let result = iso.date(from: value) { return result }
    let fractional = ISO8601DateFormatter()
    fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    guard let result = fractional.date(from: value) else { throw BridgeError.invalid_fields }
    return result
}

func string(_ value: Any?) throws -> String {
    guard let result = value as? String else { throw BridgeError.invalid_fields }
    return result
}

func encoded(_ object: Any) throws -> Data {
    try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
}

func destination(_ kind: String, _ wanted: String?) throws -> EKCalendar {
    let type: EKEntityType = kind == "calendar" ? .event : .reminder
    let calendars = store.calendars(for: type)
    var target: EKCalendar?
    if let wanted = wanted, !wanted.isEmpty {
        let exact = calendars.filter { $0.calendarIdentifier == wanted }
        let matches = exact.isEmpty ? calendars.filter { $0.title.caseInsensitiveCompare(wanted) == .orderedSame } : exact
        guard matches.count == 1 else { throw BridgeError.invalid_fields }
        target = matches[0]
    } else {
        target = kind == "calendar" ? store.defaultCalendarForNewEvents : store.defaultCalendarForNewReminders()
    }
    guard let calendar = target else { throw BridgeError.invalid_fields }
    guard calendar.allowsContentModifications else { throw BridgeError.read_only }
    return calendar
}

func findEvent(_ fields: [String: Any]) throws -> EKEvent {
    let id = try string(fields["item_id"])
    let start = try date(fields["occurrence_start_at"])
    let predicate = store.predicateForEvents(withStart: start.addingTimeInterval(-1),
                                            end: start.addingTimeInterval(1), calendars: nil)
    let events = store.events(matching: predicate).filter {
        $0.eventIdentifier == id && abs($0.startDate.timeIntervalSince(start)) < 0.5
    }
    guard events.count == 1 else { throw BridgeError.item_not_found }
    return events[0]
}

func findItem(_ kind: String, _ fields: [String: Any]) throws -> EKCalendarItem {
    if kind == "calendar" { return try findEvent(fields) }
    guard let item = store.calendarItem(withIdentifier: try string(fields["item_id"])) as? EKReminder else {
        throw BridgeError.item_not_found
    }
    return item
}

func alarmRecord(_ alarm: EKAlarm) -> [String: Any] {
    var result: [String: Any] = ["relative_seconds": alarm.relativeOffset]
    if let absolute = alarm.absoluteDate { result["absolute_at"] = iso.string(from: absolute) }
    if let location = alarm.structuredLocation {
        result["location_title"] = location.title
        result["radius"] = location.radius
        result["proximity"] = alarm.proximity.rawValue
        if let point = location.geoLocation {
            result["latitude"] = point.coordinate.latitude
            result["longitude"] = point.coordinate.longitude
        }
    }
    return result
}

func privateNative(_ fields: [String: Any], helper: String) throws -> [String: Any] {
    let binary = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().deletingLastPathComponent().appendingPathComponent(helper)
    guard FileManager.default.isExecutableFile(atPath: binary.path) else { throw BridgeError.unsupported_capability }
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    defer { try? FileManager.default.removeItem(at: directory) }
    let request = directory.appendingPathComponent("request.json")
    try encoded(fields).write(to: request)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: request.path)
    let process = Process()
    process.executableURL = binary
    process.arguments = [request.path]
    let output = Pipe()
    process.standardOutput = output
    process.standardError = FileHandle.nullDevice
    try process.run()
    let data = output.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    guard process.terminationStatus == 0, data.count < 1048576,
          let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw BridgeError.receiver_unavailable }
    if result["success"] as? Bool != true {
        privateStage = result["stage"] as? String ?? ""
        privateWriteStarted = result["write_started"] as? Bool
        throw BridgeError(rawValue: result["error_code"] as? String ?? "") ?? .verification_failed
    }
    return result
}

func privateReminder(_ fields: [String: Any]) throws -> [String: Any] {
    return try privateNative(fields, helper: "reminderkit-helper")
}

func ruleRecord(_ rule: EKRecurrenceRule) -> [String: Any] {
    var result: [String: Any] = ["frequency": rule.frequency.rawValue, "interval": rule.interval,
        "first_weekday": rule.firstDayOfTheWeek,
        "weekdays": (rule.daysOfTheWeek ?? []).map { ["day": $0.dayOfTheWeek.rawValue, "week": $0.weekNumber] },
        "monthdays": rule.daysOfTheMonth ?? [], "months": rule.monthsOfTheYear ?? [],
        "weeks": rule.weeksOfTheYear ?? [], "yeardays": rule.daysOfTheYear ?? [], "positions": rule.setPositions ?? []]
    if let end = rule.recurrenceEnd {
        result["count"] = end.occurrenceCount
        if let date = end.endDate { result["until"] = iso.string(from: date) }
    }
    return result
}

// EventKit represents an all-day end as the final second of its last day.
// The MCP contract uses an exclusive midnight boundary in the Mac's local zone.
func exclusiveEnd(_ event: EKEvent) -> Date {
    let end = event.endDate!
    let next = end.addingTimeInterval(1)
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = event.timeZone ?? .current
    return event.isAllDay && next == calendar.startOfDay(for: next) ? next : end
}

func record(_ item: EKCalendarItem) throws -> [String: Any] {
    var result: [String: Any] = [
        "item_id": (item as? EKEvent)?.eventIdentifier ?? item.calendarItemIdentifier,
        "title": item.title ?? "", "notes": item.notes ?? "", "url": item.url?.absoluteString ?? "",
        "calendar_id": item.calendar.calendarIdentifier, "calendar_title": item.calendar.title,
        "account": item.calendar.source?.title ?? "", "writable": item.calendar.allowsContentModifications,
        "timezone": item.timeZone?.identifier ?? "",
        "alarms": (item.alarms ?? []).map(alarmRecord),
        "recurrence_rules": (item.recurrenceRules ?? []).map(ruleRecord)
    ]
    if let modified = item.lastModifiedDate {
        result["modified_at"] = iso.string(from: modified)
        result["modified_epoch"] = modified.timeIntervalSince1970
    }
    if let event = item as? EKEvent {
        if event.responds(to: NSSelectorFromString("travelTime")) { result["travel_seconds"] = event.value(forKey: "travelTime") }
        if let location = event.structuredLocation?.geoLocation {
            result["latitude"] = location.coordinate.latitude
            result["longitude"] = location.coordinate.longitude
        }
        result["start_at"] = iso.string(from: event.startDate)
        result["end_at"] = iso.string(from: exclusiveEnd(event))
        result["occurrence_start_at"] = iso.string(from: event.startDate)
        result["location"] = event.location ?? ""
        result["all_day"] = event.isAllDay
        result["availability"] = event.availability.rawValue
        result["attendees"] = (event.attendees ?? []).map { $0.url.absoluteString }.sorted()
        result["private_metadata"] = try privateNative(["operation": "inspect", "item_id": event.eventIdentifier ?? "",
            "occurrence_start_at": iso.string(from: event.startDate)], helper: "eventkit-helper")["metadata"]
    }
    if let reminder = item as? EKReminder {
        let extra = try privateReminder(["operation": "inspect", "item_id": reminder.calendarItemIdentifier])
        result["private_metadata"] = extra["metadata"]
        result["priority"] = reminder.priority
        result["completed"] = reminder.isCompleted
        if let components = reminder.dueDateComponents {
            result["due_components"] = ["year": components.year ?? 0, "month": components.month ?? 0,
                "day": components.day ?? 0, "hour": components.hour ?? -1, "minute": components.minute ?? -1,
                "timezone": components.timeZone?.identifier ?? ""] as [String: Any]
            if let due = components.date ?? Calendar(identifier: .gregorian).date(from: components) {
                result["due_at"] = iso.string(from: due)
            }
        } else { result["due_at"] = "" }
    }
    return result
}

func revision(_ item: EKCalendarItem) throws -> String {
    // Set ordering is not stable across EventKit fetches.
    var value = try record(item)
    value["alarms"] = try (item.alarms ?? []).map { String(data: try encoded(alarmRecord($0)), encoding: .utf8)! }.sorted()
    value["recurrence_rules"] = try (item.recurrenceRules ?? []).map { String(data: try encoded(ruleRecord($0)), encoding: .utf8)! }.sorted()
    return SHA256.hash(data: try encoded(value)).map { String(format: "%02x", $0) }.joined()
}

func recurrenceCutoff(_ raw: Any?, startingAt start: Date) throws -> Date {
    guard let value = raw as? [String: Any], Set(value.keys) == ["date", "timezone"],
          let text = value["date"] as? String, text.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil,
          let name = value["timezone"] as? String, let zone = TimeZone(identifier: name) else { throw BridgeError.invalid_fields }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.timeZone = zone
    formatter.dateFormat = "yyyy-MM-dd"
    formatter.isLenient = false
    guard let day = formatter.date(from: text), formatter.string(from: day) == text else { throw BridgeError.invalid_fields }
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = zone
    guard let next = calendar.date(byAdding: .day, value: 1, to: day),
          calendar.startOfDay(for: next) == next else { throw BridgeError.invalid_fields }
    guard let maximum = calendar.date(byAdding:.year,value:4,to:start), next <= maximum else { throw BridgeError.unsupported_capability }
    let cutoff = next.addingTimeInterval(-1)
    guard cutoff >= start else { throw BridgeError.invalid_fields }
    return cutoff
}

// Snapshot actual occurrences, not reconstructed RRULE expansions. Deleted
// occurrences stay absent and detached/edited exceptions keep their own content.
func occurrenceSnapshot(_ events: [EKEvent]) throws -> [String] {
    guard events.count <= 10000 else { throw BridgeError.unsupported_capability }
    let values = try events.map { event -> String in
        let value: [String: Any] = ["start": iso.string(from:event.startDate), "end":iso.string(from:exclusiveEnd(event)),
            "title":event.title ?? "", "notes":event.notes ?? "", "url":event.url?.absoluteString ?? "",
            "location":event.location ?? "", "calendar":event.calendar.calendarIdentifier,
            "all_day":event.isAllDay, "timezone":event.timeZone?.identifier ?? "", "availability":event.availability.rawValue,
            "alarms":try (event.alarms ?? []).map { String(data:try encoded(alarmRecord($0)),encoding:.utf8)! }.sorted(),
            "attendees":(event.attendees ?? []).map { $0.url.absoluteString }.sorted()]
        return String(data:try encoded(value),encoding:.utf8)!
    }.sorted()
    guard values.reduce(0, { $0 + $1.utf8.count }) <= 8388608 else { throw BridgeError.unsupported_capability }
    return values
}

func verifyOccurrenceSnapshot(_ before: [String], _ after: [String]) throws {
    guard before == after else { throw BridgeError.verification_failed }
}

func requireInvitationConsent(_ hasAttendees: Bool, _ consent: Any?) throws {
    if hasAttendees && consent as? Bool != true { throw BridgeError.unsupported_capability }
}

func endRecurrence(_ raw: Any?, _ event: EKEvent) throws {
    guard !event.isDetached, let rules = event.recurrenceRules, !rules.isEmpty else { throw BridgeError.unsupported_capability }
    let cutoff = try recurrenceCutoff(raw, startingAt: event.startDate)
    // Mutate only recurrenceEnd on the existing native rule objects. Never
    // remove/add/reconstruct rules: that discards selectors and can lose exceptions.
    for rule in rules { rule.recurrenceEnd = EKRecurrenceEnd(end: cutoff) }
}

func applyFields(_ changes: [String: Any], _ item: EKCalendarItem, _ kind: String) throws {
    let common: Set<String> = ["title", "notes", "url", "alerts", "recurrence", "timezone"]
    let allowed = common.union(kind == "calendar" ? ["start_at", "end_at", "location", "calendar", "all_day", "availability", "driving", "recurrence_end", "travel_seconds"] : ["due_at", "list_name", "priority", "completed", "location_alarm"])
    guard Set(changes.keys).isSubset(of: allowed) else { throw BridgeError.unsupported_capability }
    if let value = changes["travel_seconds"] {
        guard changes.count == 1, let seconds = value as? NSNumber,
              CFGetTypeID(seconds) != CFBooleanGetTypeID(), seconds.doubleValue == Double(seconds.intValue),
              (0...604800).contains(seconds.intValue), seconds.intValue % 60 == 0 else { throw BridgeError.invalid_fields }
        guard let event = item as? EKEvent, !event.isAllDay, !event.hasRecurrenceRules, !event.isDetached,
              !event.hasAttendees, event.responds(to:NSSelectorFromString("setTravelTime:")) else { throw BridgeError.unsupported_capability }
        event.setValue(seconds, forKey:"travelTime")
    }
    if let value = changes["title"] { item.title = try string(value) }
    if let value = changes["notes"] { item.notes = try string(value) }
    if let value = changes["url"] {
        let text = try string(value)
        if text.isEmpty { item.url = nil }
        else {
            guard let url = URL(string: text), ["http", "https"].contains(url.scheme ?? ""), url.host != nil,
                  url.user == nil, url.password == nil else { throw BridgeError.invalid_fields }
            item.url = url
        }
    }
    let event = item as? EKEvent
    let desiredAllDay = changes["all_day"] as? Bool ?? event?.isAllDay ?? false
    let timingChanged = !Set(changes.keys).isDisjoint(with: ["start_at", "end_at", "timezone", "all_day"])
    let originalStart = event?.startDate
    let originalEnd = event.map(exclusiveEnd)
    // Setting either dates or timeZone can clear all-day mode. Restore that mode
    // only after validating the approved exclusive boundaries.
    if let event = event, timingChanged { event.isAllDay = false }
    if let value = changes["timezone"] {
        guard let zone = TimeZone(identifier: try string(value)) else { throw BridgeError.invalid_fields }
        item.timeZone = zone
    }
    if let event = event {
        if let value = changes["start_at"] { event.startDate = try date(value) }
        else if timingChanged { event.startDate = originalStart }
        if let value = changes["end_at"] { event.endDate = try date(value) }
        else if timingChanged { event.endDate = originalEnd }
        guard exclusiveEnd(event) > event.startDate else { throw BridgeError.invalid_fields }
        if let value = changes["location"] { event.location = try string(value) }
        if desiredAllDay {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = event.timeZone ?? .current
            // All-day EventKit objects float in the Mac timezone after the mode
            // setter clears timeZone. Do not silently shift a foreign-zone day.
            guard calendar.timeZone == TimeZone.current else { throw BridgeError.unsupported_capability }
            guard event.startDate == calendar.startOfDay(for: event.startDate),
                  exclusiveEnd(event) == calendar.startOfDay(for: exclusiveEnd(event)) else { throw BridgeError.invalid_fields }
        }
        if timingChanged { event.isAllDay = desiredAllDay }
        if let value = changes["recurrence_end"] {
            guard changes.count == 1 else { throw BridgeError.invalid_fields }
            try endRecurrence(value, event)
        }
        if let value = changes["calendar"] { event.calendar = try destination(kind, try string(value)) }
        if let value = changes["availability"] as? String {
            let values: [String: EKEventAvailability] = ["busy": .busy, "free": .free, "tentative": .tentative, "unavailable": .unavailable]
            guard let availability = values[value] else { throw BridgeError.invalid_fields }
            let masks: [String: EKCalendarEventAvailabilityMask] = ["busy":.busy, "free":.free, "tentative":.tentative, "unavailable":.unavailable]
            guard let mask = masks[value], event.calendar.supportedEventAvailabilities.contains(mask) else { throw BridgeError.unsupported_capability }
            event.availability = availability
        }
        if let value = changes["driving"] {
            guard event.responds(to: NSSelectorFromString("setTravelTime:")) else { throw BridgeError.unsupported_capability }
            if value is NSNull { event.setValue(NSNumber(value: 0), forKey: "travelTime") }
            else {
                guard let route = value as? [String: Any], let seconds = route["seconds"] as? Int,
                      let latitude = route["latitude"] as? Double, let longitude = route["longitude"] as? Double,
                      seconds > 0 && seconds <= 604800 else { throw BridgeError.invalid_fields }
                let computed = try date(route["computed_at"])
                let observed = try date(route["origin_observed_at"])
                guard (-30...300).contains(Date().timeIntervalSince(computed)),
                      (-30...300).contains(Date().timeIntervalSince(observed)) else { throw BridgeError.location_stale }
                let place = EKStructuredLocation(title: try string(route["destination"]))
                place.geoLocation = CLLocation(latitude: latitude, longitude: longitude)
                event.structuredLocation = place
                event.setValue(NSNumber(value: seconds), forKey: "travelTime")
            }
        }
    }
    if let reminder = item as? EKReminder {
        if let value = changes["list_name"] { reminder.calendar = try destination(kind, try string(value)) }
        if let value = changes["priority"] as? Int {
            guard [0, 1, 5, 9].contains(value) else { throw BridgeError.invalid_fields }
            reminder.priority = value
        }
        if let value = changes["completed"] as? Bool { reminder.isCompleted = value }
        if let value = changes["due_at"] {
            let text = try string(value)
            if text.isEmpty { reminder.dueDateComponents = nil; reminder.startDateComponents = nil }
            else {
                let due = try date(text)
                var calendar = Calendar(identifier: .gregorian)
                calendar.timeZone = reminder.timeZone ?? TimeZone.current
                var components = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: due)
                components.calendar = calendar
                components.timeZone = calendar.timeZone
                guard components.second == 0 else { throw BridgeError.invalid_fields }
                let matching = DateComponents(hour: components.hour, minute: components.minute)
                let day = calendar.startOfDay(for: due).addingTimeInterval(-1)
                let first = calendar.nextDate(after: day, matching: matching, matchingPolicy: .strict, repeatedTimePolicy: .first)
                let last = calendar.nextDate(after: day, matching: matching, matchingPolicy: .strict, repeatedTimePolicy: .last)
                if let first = first, let last = last, first != last { throw BridgeError.invalid_fields }
                reminder.dueDateComponents = components
                reminder.startDateComponents = components
            }
        }
        // Retiming an ordinary due alert preserves its relationship to the due date.
        // Explicit absolute/location alarms are otherwise left alone.
        if changes["due_at"] != nil && changes["alerts"] == nil {
            if reminder.dueDateComponents == nil {
                for alarm in reminder.alarms ?? [] where alarm.structuredLocation == nil { reminder.removeAlarm(alarm) }
            }
        }
    }
    if let minutes = changes["alerts"] as? [Int] {
        guard minutes.count <= 5 && minutes.allSatisfy({ (0...10080).contains($0) }) else { throw BridgeError.invalid_fields }
        for alarm in item.alarms ?? [] where alarm.structuredLocation == nil { item.removeAlarm(alarm) }
        if let reminder = item as? EKReminder, !minutes.isEmpty, reminder.dueDateComponents == nil {
            throw BridgeError.invalid_fields
        }
        for value in minutes { item.addAlarm(EKAlarm(relativeOffset: TimeInterval(-value * 60))) }
    }
    if let raw = changes["location_alarm"], let reminder = item as? EKReminder {
        for alarm in reminder.alarms ?? [] where alarm.structuredLocation != nil { reminder.removeAlarm(alarm) }
        if !(raw is NSNull) {
            guard let value = raw as? [String: Any], let latitude = value["latitude"] as? Double,
                  let longitude = value["longitude"] as? Double, let radius = value["radius"] as? Double,
                  let proximity = value["proximity"] as? String, ["arrive", "leave"].contains(proximity),
                  latitude.isFinite, longitude.isFinite, radius.isFinite,
                  (-90...90).contains(latitude), (-180...180).contains(longitude), (1...100000).contains(radius) else {
                throw BridgeError.invalid_fields
            }
            let location = EKStructuredLocation(title: try string(value["title"]))
            location.geoLocation = CLLocation(latitude: latitude, longitude: longitude)
            location.radius = radius
            let alarm = EKAlarm()
            alarm.structuredLocation = location
            alarm.proximity = proximity == "arrive" ? .enter : .leave
            reminder.addAlarm(alarm)
        }
    }
    if let raw = changes["recurrence"] {
        for rule in item.recurrenceRules ?? [] { item.removeRecurrenceRule(rule) }
        if !(raw is NSNull) {
            guard let value = raw as? [String: Any], let frequency = value["frequency"] as? String else { throw BridgeError.invalid_fields }
            let values: [String: EKRecurrenceFrequency] = ["daily": .daily, "weekly": .weekly, "monthly": .monthly, "yearly": .yearly]
            guard let nativeFrequency = values[frequency] else { throw BridgeError.invalid_fields }
            let interval = value["interval"] as? Int ?? 1
            guard (1...999).contains(interval) else { throw BridgeError.invalid_fields }
            var end: EKRecurrenceEnd?
            if let count = value["count"] as? Int {
                guard (1...10000).contains(count), value["until"] == nil else { throw BridgeError.invalid_fields }
                end = EKRecurrenceEnd(occurrenceCount: count)
            }
            if let until = value["until"] { end = EKRecurrenceEnd(end: try date(until)) }
            var days: [EKRecurrenceDayOfWeek]?
            if let rawDays = value["weekdays"] {
                let names: [String: EKWeekday] = ["monday":.monday,"tuesday":.tuesday,"wednesday":.wednesday,"thursday":.thursday,"friday":.friday,"saturday":.saturday,"sunday":.sunday]
                guard frequency == "weekly", let input = rawDays as? [String], (1...7).contains(input.count), Set(input).count == input.count else { throw BridgeError.invalid_fields }
                days = try input.map { name in
                    guard let day = names[name] else { throw BridgeError.invalid_fields }
                    return EKRecurrenceDayOfWeek(day)
                }
            }
            item.addRecurrenceRule(EKRecurrenceRule(recurrenceWith:nativeFrequency,interval:interval,
                daysOfTheWeek:days,daysOfTheMonth:nil,monthsOfTheYear:nil,weeksOfTheYear:nil,daysOfTheYear:nil,setPositions:nil,end:end))
        }
    }
}

func verify(_ changes: [String: Any], _ item: EKCalendarItem, _ kind: String,
            expectedRules: [String], expectedLocationAlarms: [String], previousDue: Date?) throws {
    // Comparing each requested property avoids accepting provider-normalized changes silently.
    let value = try record(item)
    if let seconds = changes["travel_seconds"] as? NSNumber {
        guard let event = item as? EKEvent, event.responds(to:NSSelectorFromString("travelTime")),
              (event.value(forKey:"travelTime") as? NSNumber)?.doubleValue == seconds.doubleValue else { throw BridgeError.verification_failed }
    }
    for key in ["title", "notes", "url", "location", "all_day", "completed", "priority"] where changes[key] != nil {
        if key == "completed", changes[key] as? Bool == true, let reminder = item as? EKReminder,
           !reminder.isCompleted, reminder.hasRecurrenceRules, let old = previousDue,
           let components = reminder.dueDateComponents,
           let current = components.date ?? Calendar(identifier: .gregorian).date(from: components), current > old { continue }
        guard NSDictionary(dictionary: [key: value[key] ?? NSNull()]).isEqual(to: [key: changes[key]!]) else { throw BridgeError.verification_failed }
    }
    for key in ["start_at", "end_at", "due_at"] where changes[key] != nil {
        if let text = changes[key] as? String, text.isEmpty {
            guard value[key] as? String == "" else { throw BridgeError.verification_failed }
        } else {
            guard abs(try date(value[key]).timeIntervalSince(date(changes[key]))) < 0.5 else { throw BridgeError.verification_failed }
        }
    }
    for key in ["calendar", "list_name"] where changes[key] != nil {
        let wanted = try destination(kind, try string(changes[key]))
        guard item.calendar.calendarIdentifier == wanted.calendarIdentifier else { throw BridgeError.verification_failed }
    }
    if let alerts = changes["alerts"] as? [Int] {
        let actual = (item.alarms ?? []).filter { $0.structuredLocation == nil }
        guard actual.allSatisfy({ $0.absoluteDate == nil }), actual.map({ Int(-$0.relativeOffset / 60) }).sorted() == alerts.sorted() else {
            throw BridgeError.verification_failed
        }
    }
    if let zone = changes["timezone"] as? String {
        let actual = (item as? EKEvent)?.isAllDay == true ? (item.timeZone ?? .current) : item.timeZone
        guard actual == TimeZone(identifier: zone) else { throw BridgeError.verification_failed }
    }
    if let driving = changes["driving"], let event = item as? EKEvent {
        let expected = (driving as? [String: Any])?["seconds"] as? Int ?? 0
        guard (event.value(forKey: "travelTime") as? NSNumber)?.intValue == expected else { throw BridgeError.verification_failed }
        if let route = driving as? [String: Any] {
            guard let point = event.structuredLocation?.geoLocation,
                  abs(point.coordinate.latitude - (route["latitude"] as? Double ?? 999)) < 0.00001,
                  abs(point.coordinate.longitude - (route["longitude"] as? Double ?? 999)) < 0.00001 else { throw BridgeError.verification_failed }
        }
    }
    if changes["recurrence"] != nil || changes["recurrence_end"] != nil {
        let actual = try (item.recurrenceRules ?? []).map { String(data: try encoded(ruleRecord($0)), encoding: .utf8)! }.sorted()
        guard actual == expectedRules else { throw BridgeError.verification_failed }
    }
    if changes["location_alarm"] != nil {
        let actual = try (item.alarms ?? []).filter { $0.structuredLocation != nil }.map { String(data: try encoded(alarmRecord($0)), encoding: .utf8)! }.sorted()
        guard actual == expectedLocationAlarms else { throw BridgeError.verification_failed }
    }
    if let name = changes["availability"] as? String, let event = item as? EKEvent {
        let values: [String: EKEventAvailability] = ["busy": .busy, "free": .free, "tentative": .tentative, "unavailable": .unavailable]
        guard event.availability == values[name] else { throw BridgeError.verification_failed }
    }
}

func preservedTravelFields(_ item: EKCalendarItem) throws -> Data {
    var snapshot = try record(item)
    for key in ["travel_seconds", "modified_at", "modified_epoch"] { snapshot.removeValue(forKey:key) }
    return try encoded(snapshot)
}

func timing(_ item: EKCalendarItem) -> [String: Any] {
    var due: Date?
    if let event = item as? EKEvent { due = event.startDate }
    if let reminder = item as? EKReminder, let components = reminder.dueDateComponents {
        due = components.date ?? Calendar(identifier: .gregorian).date(from: components)
    }
    let alerts = (item.alarms ?? []).filter { $0.structuredLocation == nil }.compactMap { alarm -> Date? in
        alarm.absoluteDate ?? due?.addingTimeInterval(alarm.relativeOffset)
    }
    let first = alerts.min()
    let early = item is EKReminder && due != nil && first != nil && first! < due!
    return ["late": due.map { $0 < Date() } ?? false, "alert_at": first.map { iso.string(from: $0) } ?? "",
            "alert_late": first.map { $0 < Date() } ?? false, "warnings": early ? ["earlier_alarm_display"] : []]
}

#if !APPLE_PIM_TESTS
@main
struct NativeBridge {
    static func main() async {
        var writeStarted = false
        var affectedID: String?
        do {
            guard CommandLine.arguments.count == 3, CommandLine.arguments[1] == "bridge",
                  CommandLine.arguments[2].hasPrefix("--request=") else { throw BridgeError.invalid_fields }
            let path = String(CommandLine.arguments[2].dropFirst("--request=".count))
            let data = try Data(contentsOf: URL(fileURLWithPath: path))
            guard data.count <= 8388608, let request = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let kind = request["kind"] as? String, ["calendar", "reminder"].contains(kind),
                  let fields = request["fields"] as? [String: Any] else { throw BridgeError.invalid_fields }
            if fields["operation"] as? String == "driving_eta" {
                guard kind == "calendar" else { throw BridgeError.invalid_fields }
                output(["success": true, "driving": try await drivingEstimate(fields)])
                return
            }
            let granted: Bool
            if #available(macOS 14.0, *) {
                granted = kind == "calendar" ? try await store.requestFullAccessToEvents() : try await store.requestFullAccessToReminders()
            } else {
                granted = try await store.requestAccess(to: kind == "calendar" ? .event : .reminder)
            }
            guard granted else { throw BridgeError.receiver_unavailable }
            let operation = fields["operation"] as? String ?? "create"
            if operation == "destinations" {
                let type: EKEntityType = kind == "calendar" ? .event : .reminder
                let defaultID = kind == "calendar" ? store.defaultCalendarForNewEvents?.calendarIdentifier : store.defaultCalendarForNewReminders()?.calendarIdentifier
                output(["success": true, "destinations": store.calendars(for: type).map {
                    ["id": $0.calendarIdentifier, "title": $0.title, "account": $0.source?.title ?? "",
                     "writable": $0.allowsContentModifications, "default": $0.calendarIdentifier == defaultID,
                     "availability_mask": $0.supportedEventAvailabilities.rawValue] as [String: Any]
                }])
                return
            }
            let item: EKCalendarItem
            if operation == "create" {
                if kind == "calendar" {
                    let event = EKEvent(eventStore: store)
                    event.startDate = try date(fields["start_at"])
                    event.endDate = try date(fields["end_at"])
                    item = event
                } else { item = EKReminder(eventStore: store) }
                item.calendar = try destination(kind, fields[kind == "calendar" ? "calendar" : "list_name"] as? String)
            } else { item = try findItem(kind, fields) }
            if operation == "inspect" {
                output(["success": true, "item": try record(item), "revision": try revision(item)])
                return
            }
            guard item.calendar.allowsContentModifications else { throw BridgeError.read_only }
            guard ["create", "update", "delete", "update_private"].contains(operation) else { throw BridgeError.invalid_fields }
            if operation != "create" {
                guard try revision(item) == string(fields["expected_revision"]) else { throw BridgeError.revision_conflict }
            }
            let oldID = (item as? EKEvent)?.eventIdentifier ?? item.calendarItemIdentifier
            affectedID = oldID
            if operation == "update_private" {
                guard let changes = fields["changes"] as? [String: Any] else { throw BridgeError.invalid_fields }
                if changes["urgent"] as? Bool == true {
                    guard let reminder = item as? EKReminder, let due = reminder.dueDateComponents,
                          due.hour != nil, due.minute != nil else { throw BridgeError.invalid_fields }
                }
                writeStarted = true
                let result = try privateNative(fields, helper: kind == "calendar" ? "eventkit-helper" : "reminderkit-helper")
                guard result["verified"] as? Bool == true else { throw BridgeError.verification_failed }
                output(["success": true, "verified": true, "item_id": result["item_id"] as? String ?? oldID])
                return
            }
            if let event = item as? EKEvent {
                try requireInvitationConsent(event.hasAttendees, fields["allow_invitation_delivery"])
            }
            let scope = fields["scope"] as? String ?? "this"
            guard ["this", "future"].contains(scope) else { throw BridgeError.invalid_fields }
            let span: EKSpan = scope == "future" ? .futureEvents : .thisEvent
            if operation == "delete" {
                if let reminder = item as? EKReminder {
                    let metadata = try privateReminder(["operation": "inspect", "item_id": reminder.calendarItemIdentifier])["metadata"] as? [String: Any]
                    if let subtasks = metadata?["subtasks"] as? [Any], !subtasks.isEmpty { throw BridgeError.invalid_fields }
                }
                writeStarted = true
                if let event = item as? EKEvent { try store.remove(event, span: span, commit: true) }
                else { try store.remove(item as! EKReminder, commit: true) }
                store.reset()
                do {
                    _ = try findItem(kind, fields)
                    throw BridgeError.verification_failed
                } catch BridgeError.item_not_found { }
                output(["success": true, "verified": true, "item_id": oldID])
                return
            }
            var changes: [String: Any]
            if operation == "create" {
                changes = fields
                changes.removeValue(forKey: "alarm_minutes_before")
                for key in ["calendar", "list_name"] where changes[key] as? String == "" { changes.removeValue(forKey: key) }
                if changes["alerts"] == nil {
                    if let minutes = fields["alarm_minutes_before"] as? Int { changes["alerts"] = [minutes] }
                    else if kind == "reminder", let due = fields["due_at"] as? String, !due.isEmpty { changes["alerts"] = [0] }
                }
            } else {
                guard let patch = fields["changes"] as? [String: Any], !patch.isEmpty else { throw BridgeError.invalid_fields }
                changes = patch
            }
            if changes["recurrence_end"] != nil && (kind != "calendar" || operation != "update" || scope != "future" || changes.count != 1) {
                throw BridgeError.invalid_fields
            }
            var recurrenceWindow: (Date, Date, String)?
            var previousOccurrences: [String]?
            if let raw = changes["recurrence_end"], let event = item as? EKEvent {
                let cutoff = try recurrenceCutoff(raw, startingAt:event.startDate)
                // EventKit event predicates are bounded to four years. Fail closed
                // instead of silently verifying a truncated window.
                let start = event.startDate.addingTimeInterval(-1)
                let end = cutoff.addingTimeInterval(1)
                recurrenceWindow = (start, end, event.calendar.calendarIdentifier)
                let predicate = store.predicateForEvents(withStart:start, end:end, calendars:[event.calendar])
                previousOccurrences = try occurrenceSnapshot(store.events(matching:predicate))
            }
            var previousDue: Date?
            if let reminder = item as? EKReminder, let components = reminder.dueDateComponents {
                previousDue = components.date ?? Calendar(identifier: .gregorian).date(from: components)
            }
            var travelBaseline: Data?
            if changes["travel_seconds"] != nil {
                guard operation == "update", scope == "this" else { throw BridgeError.invalid_fields }
                travelBaseline = try preservedTravelFields(item)
            }
            try applyFields(changes, item, kind)
            let expectedRules = try (item.recurrenceRules ?? []).map { String(data: try encoded(ruleRecord($0)), encoding: .utf8)! }.sorted()
            let expectedLocationAlarms = try (item.alarms ?? []).filter { $0.structuredLocation != nil }.map { String(data: try encoded(alarmRecord($0)), encoding: .utf8)! }.sorted()
            writeStarted = true
            if let event = item as? EKEvent { try store.save(event, span: span, commit: true) }
            else { try store.save(item as! EKReminder, commit: true) }
            let newID = (item as? EKEvent)?.eventIdentifier ?? item.calendarItemIdentifier
            affectedID = newID
            var target: [String: Any] = ["item_id": newID]
            if let event = item as? EKEvent { target["occurrence_start_at"] = iso.string(from: event.startDate) }
            store.reset()
            let saved = try findItem(kind, target)
            if let window = recurrenceWindow, let before = previousOccurrences,
               let calendar = store.calendar(withIdentifier:window.2) {
                let predicate = store.predicateForEvents(withStart:window.0,end:window.1,calendars:[calendar])
                try verifyOccurrenceSnapshot(before, occurrenceSnapshot(store.events(matching:predicate)))
            } else if recurrenceWindow != nil { throw BridgeError.verification_failed }
            try verify(changes, saved, kind, expectedRules: expectedRules, expectedLocationAlarms: expectedLocationAlarms, previousDue: previousDue)
            if let baseline = travelBaseline {
                guard try preservedTravelFields(saved) == baseline else { throw BridgeError.verification_failed }
            }
            output(["success": true, "verified": true, "item_id": newID, "revision": try revision(saved), "timing": timing(saved)])
        } catch {
            var result: [String: Any] = ["success": false, "error_code": (error as? BridgeError)?.rawValue ?? "native_error", "write_started": privateWriteStarted ?? writeStarted]
            if let id = affectedID { result["item_id"] = id }
            if !privateStage.isEmpty { result["adapter_stage"] = privateStage }
            output(result)
        }
    }

    static func output(_ value: [String: Any]) {
        if let data = try? encoded(value), let text = String(data: data, encoding: .utf8) { print(text) }
    }
}

#endif
