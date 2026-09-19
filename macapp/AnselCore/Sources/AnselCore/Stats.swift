import Foundation

/// Per-month progress counts.
public struct MonthStats: Equatable, Sendable {
    public var total = 0
    public var counts: [ReviewStatus: Int] = [:]

    public func count(_ status: ReviewStatus) -> Int { counts[status] ?? 0 }
    /// Photos in this month with no recorded status yet.
    public var left: Int { total - ReviewStatus.allCases.reduce(0) { $0 + count($1) } }
}

/// Overall + per-month progress. Direct port of the aggregation the Python
/// `stats` command prints; kept pure so text/JSON renderers can share it (the
/// `build_stats` helper called for in the backlog).
public struct StatsReport: Equatable, Sendable {
    public var total = 0
    public var overall: [ReviewStatus: Int] = [:]
    public var months: [String: MonthStats] = [:]

    public func count(_ status: ReviewStatus) -> Int { overall[status] ?? 0 }
    /// Photos with no recorded status yet.
    public var remaining: Int { total - ReviewStatus.allCases.reduce(0) { $0 + count($1) } }
    /// Month keys in ascending order (`"unknown"` sorts last, like the Python output).
    public var sortedMonthKeys: [String] {
        months.keys.sorted { a, b in
            if a == "unknown" { return false }
            if b == "unknown" { return true }
            return a < b
        }
    }
}

/// Aggregate a library plus recorded statuses into a `StatsReport`.
public func buildStats(
    photos: [PhotoRef],
    statuses: [String: ReviewStatus],
    calendar: Calendar = .current
) -> StatsReport {
    var report = StatsReport()
    report.total = photos.count
    for photo in photos {
        let key = photo.date.map { monthKey(for: $0, calendar: calendar) } ?? "unknown"
        var bucket = report.months[key] ?? MonthStats()
        bucket.total += 1
        if let status = statuses[photo.uuid] {
            report.overall[status, default: 0] += 1
            bucket.counts[status, default: 0] += 1
        }
        report.months[key] = bucket
    }
    return report
}
