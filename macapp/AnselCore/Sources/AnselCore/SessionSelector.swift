import Foundation

/// The three review modes, matching the Python CLI commands.
public enum SessionMode: Sendable, Equatable {
    /// All unreviewed photos, oldest first.
    case review
    /// One `YYYY-MM` month only — a natural finish line.
    case chunk(month: String)
    /// A random batch; skips older than a week resurface.
    case random(count: Int)
}

/// The window after which a skipped photo becomes eligible again in `random`
/// mode. Matches the Python `SKIP_RESURFACE_WINDOW` of 7 days.
public let skipResurfaceWindow: TimeInterval = 7 * 24 * 60 * 60

/// Pure selection of the photos a session should present, given the library and
/// the set of UUIDs to exclude (computed from `ProgressStore`).
public enum SessionSelector {
    /// Sort by date ascending; dateless photos sort last, preserving input order.
    public static func sortedByDate(_ photos: [PhotoRef]) -> [PhotoRef] {
        photos.enumerated().sorted { lhs, rhs in
            switch (lhs.element.date, rhs.element.date) {
            case let (l?, r?): return l == r ? lhs.offset < rhs.offset : l < r
            case (nil, _?): return false
            case (_?, nil): return true
            case (nil, nil): return lhs.offset < rhs.offset
            }
        }.map(\.element)
    }

    /// Photos for `review`: not yet reviewed, oldest first.
    public static func reviewQueue(_ photos: [PhotoRef], reviewed: Set<String>) -> [PhotoRef] {
        sortedByDate(photos).filter { !reviewed.contains($0.uuid) }
    }

    /// Photos for `chunk`: one month, not yet reviewed, oldest first.
    public static func chunkQueue(
        _ photos: [PhotoRef],
        month: String,
        reviewed: Set<String>,
        calendar: Calendar = .current
    ) -> [PhotoRef] {
        let inMonth = photos.filter { photo in
            guard let date = photo.date else { return false }
            return monthKey(for: date, calendar: calendar) == month
        }
        return reviewQueue(inMonth, reviewed: reviewed)
    }

    /// Eligible photos for `random`, before sampling: not excluded.
    public static func randomEligible(_ photos: [PhotoRef], excluded: Set<String>) -> [PhotoRef] {
        photos.filter { !excluded.contains($0.uuid) }
    }

    /// A random batch of up to `count` from the eligible set.
    /// `generator` is injectable so tests are deterministic.
    public static func randomBatch<G: RandomNumberGenerator>(
        _ eligible: [PhotoRef],
        count: Int,
        using generator: inout G
    ) -> [PhotoRef] {
        Array(eligible.shuffled(using: &generator).prefix(max(0, count)))
    }
}
