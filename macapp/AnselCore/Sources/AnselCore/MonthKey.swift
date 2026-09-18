import Foundation

/// A `YYYY-MM` bucket key for a date, in the given calendar. Mirrors the Python
/// `_month_key`. Photos with no date bucket under `"unknown"` at the call site.
public func monthKey(for date: Date, calendar: Calendar = .current) -> String {
    let c = calendar.dateComponents([.year, .month], from: date)
    return String(format: "%04d-%02d", c.year ?? 0, c.month ?? 0)
}

/// True if `string` is a well-formed `YYYY-MM` month key. Mirrors the Python
/// `_MONTH_RE` validation used by `chunk --month`.
public func isValidMonthKey(_ string: String) -> Bool {
    guard string.count == 7 else { return false }
    let parts = string.split(separator: "-")
    guard parts.count == 2, parts[0].count == 4, parts[1].count == 2 else { return false }
    return parts.allSatisfy { $0.allSatisfy(\.isNumber) }
}
