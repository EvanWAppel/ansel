import Foundation

/// A photo's review outcome. Mirrors the Python `STATUSES` tuple and the
/// SQLite CHECK constraint: done / skipped / error / delete.
public enum ReviewStatus: String, CaseIterable, Sendable {
    case done
    case skipped
    case error
    case delete
}

/// A photo to review, as seen by the pure-logic core.
///
/// The app layer builds these from PhotoKit `PHAsset`s. Two identifiers matter:
/// - `uuid` — the bare Photos UUID, the stable progress-DB key (compatible with
///   the existing `photo_review.db` written by the Python CLI).
/// - `localIdentifier` — PhotoKit's `"<uuid>/L0/001"` form, which is exactly the
///   string Photos' AppleScript wants for `media item id`.
public struct PhotoRef: Sendable, Equatable, Identifiable {
    public let uuid: String
    public let localIdentifier: String
    public let filename: String
    public let date: Date?
    public let isVideo: Bool

    public var id: String { uuid }

    public init(
        uuid: String,
        localIdentifier: String,
        filename: String,
        date: Date?,
        isVideo: Bool = false
    ) {
        self.uuid = uuid
        self.localIdentifier = localIdentifier
        self.filename = filename
        self.date = date
        self.isVideo = isVideo
    }

    /// Derive the bare UUID from a PhotoKit local identifier (`"<uuid>/L0/001"`).
    public static func bareUUID(fromLocalIdentifier localIdentifier: String) -> String {
        String(localIdentifier.split(separator: "/", maxSplits: 1).first ?? "")
    }
}
