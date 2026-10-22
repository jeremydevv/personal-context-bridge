// In-memory regression tests. Never authorize, fetch, save, or remove Calendar records.
import Foundation
import EventKit

@main struct NativeTests {
    static func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
        if try !condition() { throw NSError(domain: message, code: 1) }
    }
    static func event(_ start: String, _ end: String) throws -> EKEvent {
        let value = EKEvent(eventStore: store)
        value.calendar = EKCalendar(for: .event, eventStore: store)
        value.startDate = try date(start)
        value.endDate = try date(end)
        return value
    }
    static func main() throws {
        for (start, end) in [
            ("2032-01-01T00:00:00-05:00", "2032-01-02T00:00:00-05:00"),
            ("2032-03-14T00:00:00-05:00", "2032-03-15T00:00:00-04:00"),
            ("2032-11-07T00:00:00-04:00", "2032-11-08T00:00:00-05:00")
        ] {
            let item = try event(start, end)
            try applyFields(["start_at":start, "end_at":end, "timezone":"America/New_York", "all_day":true], item, "calendar")
            try require(item.isAllDay, "all-day flag lost")
            try require(item.startDate == (try date(start)), "start shifted")
            try require(exclusiveEnd(item) == (try date(end)), "exclusive end shifted")
            // End-only edits of existing all-day objects must stay exclusive too.
            try applyFields(["end_at":end], item, "calendar")
        }
        try require(try date("2032-01-01T00:00:00.123456-05:00").timeIntervalSince(date("2032-01-01T05:00:00Z")) > 0.12, "fractional timestamp rejected")
        for days: [EKWeekday] in [[.tuesday,.wednesday,.thursday,.friday],[.monday]] {
            let item = try event("2026-10-20T08:00:00-04:00", "2026-10-20T09:00:00-04:00")
            item.timeZone = TimeZone(identifier:"America/New_York")
            let rule = EKRecurrenceRule(recurrenceWith:.weekly, interval:1,
                daysOfTheWeek:days.map { EKRecurrenceDayOfWeek($0) }, daysOfTheMonth:nil,
                monthsOfTheYear:nil, weeksOfTheYear:nil, daysOfTheYear:nil, setPositions:nil, end:nil)
            item.addRecurrenceRule(rule)
            var before = ruleRecord(item.recurrenceRules![0])
            let cutoff:[String:Any] = ["recurrence_end":["date":"2027-05-28", "timezone":"America/New_York"]]
            try applyFields(cutoff,item,"calendar")
            let updated = item.recurrenceRules![0]
            try require(updated.recurrenceEnd?.endDate == (try date("2027-05-28T23:59:59-04:00")), "inclusive end mismatch")
            var after = ruleRecord(updated)
            before.removeValue(forKey:"until"); before.removeValue(forKey:"count")
            after.removeValue(forKey:"until"); after.removeValue(forKey:"count")
            try require(try encoded(before) == encoded(after), "weekday or other selector changed")
            try require(item.startDate == (try date("2026-10-20T08:00:00-04:00")), "ordinary start changed")
            try require(item.endDate == (try date("2026-10-20T09:00:00-04:00")), "ordinary end changed")
            try applyFields(cutoff,item,"calendar")
            try require(item.recurrenceRules![0].recurrenceEnd?.endDate == updated.recurrenceEnd?.endDate, "end-only replay drifted")
        }
        let complex = try event("2026-10-20T08:00:00-04:00","2026-10-20T09:00:00-04:00")
        complex.addRecurrenceRule(EKRecurrenceRule(recurrenceWith:.yearly,interval:2,
            daysOfTheWeek:[EKRecurrenceDayOfWeek(.monday,weekNumber:2)],
            daysOfTheMonth:[5],monthsOfTheYear:[5],weeksOfTheYear:[20],daysOfTheYear:[140],setPositions:[1],end:nil))
        var complexBefore = ruleRecord(complex.recurrenceRules![0])
        try applyFields(["recurrence_end":["date":"2027-05-28","timezone":"America/New_York"]],complex,"calendar")
        var complexAfter = ruleRecord(complex.recurrenceRules![0])
        complexBefore.removeValue(forKey:"until"); complexBefore.removeValue(forKey:"count")
        complexAfter.removeValue(forKey:"until"); complexAfter.removeValue(forKey:"count")
        try require(try encoded(complexBefore) == encoded(complexAfter),"complex selector lost")
        let weekly = try event("2026-10-20T08:00:00-04:00","2026-10-20T09:00:00-04:00")
        try applyFields(["recurrence":["frequency":"weekly","weekdays":["tuesday","wednesday","thursday","friday"]]],weekly,"calendar")
        try require(weekly.recurrenceRules!.first!.daysOfTheWeek!.map { $0.dayOfTheWeek.rawValue } == [3,4,5,6],"weekly creation selectors lost")
        // JSON bridge decoding must preserve the approved all-day fields too.
        let fields:[String:Any] = ["start_at":"2032-01-01T00:00:00-05:00", "end_at":"2032-01-02T00:00:00-05:00", "timezone":"America/New_York", "all_day":true]
        let decoded = try JSONSerialization.jsonObject(with:encoded(["kind":"calendar","fields":fields])) as! [String:Any]
        let decodedFields = decoded["fields"] as! [String:Any]
        let decodedEvent = try event(fields["start_at"] as! String,fields["end_at"] as! String)
        try applyFields(decodedFields,decodedEvent,"calendar")
        try require(decodedEvent.isAllDay && exclusiveEnd(decodedEvent) == (try date(fields["end_at"])),"JSON all-day round trip failed")
        // End dates use local calendar arithmetic, including 23/25-hour days.
        for (day, expected) in [("2032-03-14","2032-03-14T23:59:59-04:00"),
                                ("2032-11-07","2032-11-07T23:59:59-05:00")] {
            let cutoff = try recurrenceCutoff(["date":day,"timezone":"America/New_York"], startingAt:date("2030-01-01T00:00:00Z"))
            try require(cutoff == (try date(expected)), "DST cutoff shifted")
        }
        for raw: [String:Any] in [["date":"2027-02-30","timezone":"UTC"],
                                   ["date":"2027-5-28","timezone":"UTC"],
                                   ["date":"2027-05-28","timezone":"No/Zone"]] {
            var rejected = false
            do { _ = try recurrenceCutoff(raw,startingAt:date("2026-01-01T00:00:00Z")) } catch { rejected = true }
            try require(rejected,"invalid end accepted")
        }
        // A broad field patch on an unsaved ordinary event, with no participants.
        let item = try event("2032-01-01T12:00:00-05:00","2032-01-01T13:00:00-05:00")
        try applyFields(["title":"Fictional", "notes":"Literal notes", "url":"https://example.com/a", "location":"Fictional place", "timezone":"America/New_York", "alerts":[0,30], "recurrence":["frequency":"weekly","interval":2,"count":4]],item,"calendar")
        try require(item.title == "Fictional" && item.notes == "Literal notes" && item.location == "Fictional place", "text fields lost")
        try require(item.url?.absoluteString == "https://example.com/a","URL/availability lost")
        var availabilityDenied = false
        do { try applyFields(["availability":"free"],item,"calendar") } catch BridgeError.unsupported_capability { availabilityDenied = true }
        try require(availabilityDenied,"unsupported account availability was accepted")
        try require(item.alarms?.count == 2 && item.recurrenceRules?.first?.interval == 2,"alerts/recurrence lost")
        try applyFields(["notes":"", "url":"", "location":"", "alerts":[], "recurrence":NSNull()],item,"calendar")
        try require((item.alarms ?? []).isEmpty && (item.recurrenceRules ?? []).isEmpty,"explicit clears lost")
        try require(item.notes == "" && item.url == nil && item.location == "","text clears lost")
        // Mock storage contains ordinary occurrences, one edited exception, and
        // a deleted occurrence represented by its absence. Compare the actual
        // production snapshot checker, without authorizing/fetching/saving.
        let ordinary = try event("2027-05-25T08:00:00-04:00","2027-05-25T09:00:00-04:00")
        let exception = try event("2027-05-27T10:00:00-04:00","2027-05-27T11:00:00-04:00")
        exception.title = "Edited fictional occurrence"
        ordinary.timeZone = TimeZone(identifier:"America/New_York")
        ordinary.addRecurrenceRule(EKRecurrenceRule(recurrenceWith:.weekly,interval:1,end:nil))
        let snapshot = try occurrenceSnapshot([ordinary,exception])
        try applyFields(["recurrence_end":["date":"2027-05-28","timezone":"America/New_York"]],ordinary,"calendar")
        try require(ordinary.recurrenceRules!.first!.recurrenceEnd!.endDate == (try date("2027-05-28T23:59:59-04:00")),"mock stored rule end unchanged")
        try verifyOccurrenceSnapshot(snapshot,occurrenceSnapshot([exception,ordinary]))
        let resurrected = try event("2027-05-26T08:00:00-04:00","2027-05-26T09:00:00-04:00")
        var rejected = false
        do { try verifyOccurrenceSnapshot(snapshot,occurrenceSnapshot([ordinary,resurrected,exception])) } catch { rejected = true }
        try require(rejected,"deleted occurrence resurrected without detection")
        rejected = false
        exception.title = "Unexpected edit"
        do { try verifyOccurrenceSnapshot(snapshot,occurrenceSnapshot([ordinary,exception])) } catch { rejected = true }
        try require(rejected,"exception edit lost without detection")
        try requireInvitationConsent(false,nil)
        try requireInvitationConsent(true,true)
        var denied = false
        do { try requireInvitationConsent(true,false) } catch { denied = true }
        try require(denied,"existing attendees did not require explicit delivery consent")
        let travel = try event("2031-11-02T17:00:00Z", "2031-11-02T18:00:00Z")
        travel.title = "Fictional travel fixture"
        travel.notes = "Preserve these notes"
        travel.location = "Fictional location"
        travel.addAlarm(EKAlarm(relativeOffset: -1800))
        for seconds in [2400, 2700, 0, 604800] {
            try applyFields(["travel_seconds":seconds], travel, "calendar")
            try require((travel.value(forKey:"travelTime") as? NSNumber)?.intValue == seconds, "explicit duration lost")
            try require(travel.title == "Fictional travel fixture" && travel.notes == "Preserve these notes", "duration changed text")
            try require(travel.startDate == (try date("2031-11-02T17:00:00Z")) && travel.endDate == (try date("2031-11-02T18:00:00Z")), "duration shifted event")
            try require(travel.location == "Fictional location" && travel.alarms?.count == 1 && !travel.hasRecurrenceRules, "duration changed unrelated fields")
        }
        for invalid: Any in [true, -60, 1, 2400.5, "2400", NSNull(), 604860] {
            var denied = false
            do { try applyFields(["travel_seconds":invalid], travel, "calendar") } catch { denied = true }
            try require(denied, "invalid explicit duration accepted")
        }
        var mixedDenied = false
        do { try applyFields(["travel_seconds":2400, "notes":"Wrong"], travel, "calendar") } catch { mixedDenied = true }
        try require(mixedDenied && travel.notes == "Preserve these notes", "mixed patch mutated event")
        travel.addRecurrenceRule(EKRecurrenceRule(recurrenceWith:.weekly, interval:1, end:nil))
        var recurringDenied = false
        do { try applyFields(["travel_seconds":2400], travel, "calendar") } catch { recurringDenied = true }
        try require(recurringDenied && travel.hasRecurrenceRules, "recurring travel write accepted")
        travel.recurrenceRules = nil
        travel.isAllDay = true
        var allDayDenied = false
        do { try applyFields(["travel_seconds":2400], travel, "calendar") } catch { allDayDenied = true }
        try require(allDayDenied, "all-day travel write accepted")
        print("Native dates, DST, all-day, fields, clears, recurrence and explicit travel regressions passed (unsaved objects only).")
    }
}
