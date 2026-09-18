import Foundation
import SQLite3

/// Errors surfaced by the progress store. We never swallow SQLite failures —
/// the Python original follows the same "do not hide errors" rule.
public enum ProgressStoreError: Error, CustomStringConvertible {
    case open(String)
    case exec(String)
    case prepare(String)
    case step(String)

    public var description: String {
        switch self {
        case .open(let m): return "sqlite open failed: \(m)"
        case .exec(let m): return "sqlite exec failed: \(m)"
        case .prepare(let m): return "sqlite prepare failed: \(m)"
        case .step(let m): return "sqlite step failed: \(m)"
        }
    }
}

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

/// SQLite progress tracking, keyed by bare Photos UUID. Schema-compatible with
/// the Python CLI's `photo_review.db`, so existing progress carries over.
///
/// Each write commits immediately (autocommit), so an interrupted session never
/// loses work — the same guarantee the Python version makes.
public final class ProgressStore {
    private var db: OpaquePointer?

    /// The database file backing this store.
    public let url: URL

    private static let schema = """
        CREATE TABLE IF NOT EXISTS reviews (
            uuid        TEXT PRIMARY KEY,
            status      TEXT NOT NULL CHECK (status IN ('done', 'skipped', 'error', 'delete')),
            caption     TEXT,
            keywords    TEXT,
            error       TEXT,
            reviewed_at TEXT NOT NULL
        );
        """

    public init(path: URL) throws {
        self.url = path
        try FileManager.default.createDirectory(
            at: path.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if sqlite3_open(path.path, &db) != SQLITE_OK {
            throw ProgressStoreError.open(lastMessage)
        }
        try exec(Self.schema)
    }

    deinit {
        sqlite3_close(db)
    }

    // MARK: - Reads

    /// UUIDs of all photos with any recorded status.
    public func reviewedUUIDs() throws -> Set<String> {
        var result: Set<String> = []
        try query("SELECT uuid FROM reviews") { stmt in
            result.insert(columnText(stmt, 0))
        }
        return result
    }

    /// UUIDs a review session should exclude.
    ///
    /// Without a resurface window this is every recorded UUID. With one, photos
    /// skipped longer ago than the window become eligible again; done/delete/error
    /// records always stay excluded.
    public func excludedUUIDs(
        resurfaceSkipsAfter: TimeInterval? = nil,
        now: Date = Date()
    ) throws -> Set<String> {
        guard let window = resurfaceSkipsAfter else {
            return try reviewedUUIDs()
        }
        let cutoff = now.addingTimeInterval(-window)
        var result: Set<String> = []
        try query("SELECT uuid, status, reviewed_at FROM reviews") { stmt in
            let uuid = columnText(stmt, 0)
            let status = columnText(stmt, 1)
            let reviewedAt = Self.parseTimestamp(columnText(stmt, 2))
            let resurfaced = status == "skipped"
                && reviewedAt != nil && reviewedAt! <= cutoff
            if !resurfaced { result.insert(uuid) }
        }
        return result
    }

    /// Mapping of photo UUID to recorded status.
    public func allStatuses() throws -> [String: ReviewStatus] {
        var result: [String: ReviewStatus] = [:]
        try query("SELECT uuid, status FROM reviews") { stmt in
            if let status = ReviewStatus(rawValue: columnText(stmt, 1)) {
                result[columnText(stmt, 0)] = status
            }
        }
        return result
    }

    /// Counts of recorded statuses, e.g. `[.done: 12, .skipped: 3]`.
    public func statusCounts() throws -> [ReviewStatus: Int] {
        var result: [ReviewStatus: Int] = [:]
        try query("SELECT status, COUNT(*) FROM reviews GROUP BY status") { stmt in
            if let status = ReviewStatus(rawValue: columnText(stmt, 0)) {
                result[status] = Int(sqlite3_column_int64(stmt, 1))
            }
        }
        return result
    }

    // MARK: - Writes

    /// Record (or overwrite) a photo's review status. Commits immediately.
    public func record(
        uuid: String,
        status: ReviewStatus,
        caption: String? = nil,
        keywords: [String]? = nil,
        error: String? = nil,
        now: Date = Date()
    ) throws {
        try upsert(
            uuid: uuid,
            status: status.rawValue,
            caption: caption,
            keywords: (keywords?.isEmpty ?? true) ? nil : keywords!.joined(separator: ", "),
            error: error,
            reviewedAt: Self.timestamp(now)
        )
    }

    /// Insert or replace a row from already-serialized fields. Shared by `record`
    /// and `importRows`; preserves the exact `reviewedAt` string (so an imported
    /// skip keeps its original age for the resurface rule).
    private func upsert(
        uuid: String, status: String, caption: String?, keywords: String?,
        error: String?, reviewedAt: String
    ) throws {
        let sql = """
            INSERT OR REPLACE INTO reviews
                (uuid, status, caption, keywords, error, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw ProgressStoreError.prepare(lastMessage)
        }
        defer { sqlite3_finalize(stmt) }
        bind(stmt, 1, uuid)
        bind(stmt, 2, status)
        bind(stmt, 3, caption)
        bind(stmt, 4, keywords)
        bind(stmt, 5, error)
        bind(stmt, 6, reviewedAt)
        guard sqlite3_step(stmt) == SQLITE_DONE else {
            throw ProgressStoreError.step(lastMessage)
        }
    }

    /// Merge review rows from another Ansel/CLI progress database into this one,
    /// upserting by UUID (last import wins). Original timestamps are preserved.
    /// Returns the number of rows imported. Throws if the source can't be opened
    /// or lacks a compatible `reviews` table.
    @discardableResult
    public func importRows(from source: URL) throws -> Int {
        var src: OpaquePointer?
        guard sqlite3_open_v2(source.path, &src, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
            let message = src.flatMap { sqlite3_errmsg($0).map { String(cString: $0) } }
                ?? "cannot open \(source.lastPathComponent)"
            sqlite3_close(src)
            throw ProgressStoreError.open(message)
        }
        defer { sqlite3_close(src) }

        let sql = "SELECT uuid, status, caption, keywords, error, reviewed_at FROM reviews"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(src, sql, -1, &stmt, nil) == SQLITE_OK else {
            let message = sqlite3_errmsg(src).map { String(cString: $0) } ?? "no reviews table"
            throw ProgressStoreError.prepare(message)
        }
        defer { sqlite3_finalize(stmt) }

        var count = 0
        while true {
            let rc = sqlite3_step(stmt)
            if rc == SQLITE_ROW {
                try upsert(
                    uuid: columnText(stmt!, 0),
                    status: columnText(stmt!, 1),
                    caption: columnTextOptional(stmt!, 2),
                    keywords: columnTextOptional(stmt!, 3),
                    error: columnTextOptional(stmt!, 4),
                    reviewedAt: columnText(stmt!, 5)
                )
                count += 1
            } else if rc == SQLITE_DONE {
                break
            } else {
                throw ProgressStoreError.step(lastMessage)
            }
        }
        return count
    }

    /// Delete a photo's review record so it comes up again. Returns true if a row existed.
    @discardableResult
    public func clear(uuid: String) throws -> Bool {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "DELETE FROM reviews WHERE uuid = ?", -1, &stmt, nil) == SQLITE_OK
        else { throw ProgressStoreError.prepare(lastMessage) }
        defer { sqlite3_finalize(stmt) }
        bind(stmt, 1, uuid)
        guard sqlite3_step(stmt) == SQLITE_DONE else {
            throw ProgressStoreError.step(lastMessage)
        }
        return sqlite3_changes(db) > 0
    }

    // MARK: - Timestamp coding (compatible with Python `datetime.isoformat`)

    public static func timestamp(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: date)
    }

    public static func parseTimestamp(_ string: String) -> Date? {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = iso.date(from: string) { return d }
        iso.formatOptions = [.withInternetDateTime]
        if let d = iso.date(from: string) { return d }
        // Legacy Python isoformat with microseconds and "+00:00" offset.
        for pattern in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXXXX", "yyyy-MM-dd'T'HH:mm:ssXXXXX"] {
            let df = DateFormatter()
            df.locale = Locale(identifier: "en_US_POSIX")
            df.dateFormat = pattern
            if let d = df.date(from: string) { return d }
        }
        return nil
    }

    // MARK: - SQLite helpers

    private func exec(_ sql: String) throws {
        var errmsg: UnsafeMutablePointer<CChar>?
        if sqlite3_exec(db, sql, nil, nil, &errmsg) != SQLITE_OK {
            let message = errmsg.map { String(cString: $0) } ?? lastMessage
            sqlite3_free(errmsg)
            throw ProgressStoreError.exec(message)
        }
    }

    private func query(_ sql: String, _ row: (OpaquePointer) -> Void) throws {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw ProgressStoreError.prepare(lastMessage)
        }
        defer { sqlite3_finalize(stmt) }
        while true {
            let rc = sqlite3_step(stmt)
            if rc == SQLITE_ROW {
                row(stmt!)
            } else if rc == SQLITE_DONE {
                break
            } else {
                throw ProgressStoreError.step(lastMessage)
            }
        }
    }

    private func bind(_ stmt: OpaquePointer?, _ index: Int32, _ value: String?) {
        if let value {
            sqlite3_bind_text(stmt, index, value, -1, SQLITE_TRANSIENT)
        } else {
            sqlite3_bind_null(stmt, index)
        }
    }

    private func columnText(_ stmt: OpaquePointer, _ index: Int32) -> String {
        guard let c = sqlite3_column_text(stmt, index) else { return "" }
        return String(cString: c)
    }

    private func columnTextOptional(_ stmt: OpaquePointer, _ index: Int32) -> String? {
        guard let c = sqlite3_column_text(stmt, index) else { return nil }
        return String(cString: c)
    }

    private var lastMessage: String {
        guard let db, let c = sqlite3_errmsg(db) else { return "unknown error" }
        return String(cString: c)
    }
}
