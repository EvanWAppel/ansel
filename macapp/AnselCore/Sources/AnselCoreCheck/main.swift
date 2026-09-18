import Foundation
import AnselCore

// A tiny dependency-free check harness. Verifies the pure logic ported from the
// Python CLI. Exits non-zero if any check fails, so it can gate commits/CI even
// without Xcode. Replace with `import Testing` suites once Xcode is installed.

var failures = 0
var checks = 0

@MainActor func expect(
    _ condition: Bool, _ message: String,
    file: StaticString = #file, line: UInt = #line
) {
    checks += 1
    if !condition {
        failures += 1
        print("  ✗ FAIL: \(message) (\(file):\(line))")
    }
}

@MainActor func expectEqual<T: Equatable>(
    _ a: T, _ b: T, _ message: String,
    file: StaticString = #file, line: UInt = #line
) {
    expect(a == b, "\(message) — got \(a), expected \(b)", file: file, line: line)
}

@MainActor func section(_ name: String, _ body: () throws -> Void) {
    print("• \(name)")
    do { try body() } catch { failures += 1; print("  ✗ threw: \(error)") }
}

// MARK: - Deterministic PRNG for random-batch checks

struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { state = seed &+ 0x9E3779B97F4A7C15 }
    mutating func next() -> UInt64 {
        state = state &+ 0x9E3779B97F4A7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }
}

let utcCalendar: Calendar = {
    var c = Calendar(identifier: .gregorian)
    c.timeZone = TimeZone(identifier: "UTC")!
    return c
}()

func utcDate(_ y: Int, _ m: Int, _ d: Int, _ h: Int = 12) -> Date {
    var c = DateComponents()
    c.year = y; c.month = m; c.day = d; c.hour = h
    return utcCalendar.date(from: c)!
}

func photo(_ uuid: String, date: Date? = nil, filename: String = "IMG.jpg") -> PhotoRef {
    PhotoRef(uuid: uuid, localIdentifier: "\(uuid)/L0/001", filename: filename, date: date)
}

func tempDBURL() -> URL {
    FileManager.default.temporaryDirectory
        .appendingPathComponent("ansel-check-\(UUID().uuidString)")
        .appendingPathComponent("progress.db")
}

// MARK: - Keywords

section("Keywords") {
    let s = Config.defaults.shortcuts
    expectEqual(expandKeywords("g, beach day, t", shortcuts: s),
                ["guitar", "beach day", "travel"], "mixes shortcuts + freeform")
    expectEqual(expandKeywords("g, guitar, g, f", shortcuts: s),
                ["guitar", "food"], "dedupes after expansion")
    expectEqual(expandKeywords("  ,  , ", shortcuts: s), [], "drops empty tokens")
    expectEqual(expandKeywords("xyz", shortcuts: s), ["xyz"], "unknown passes through")
    expectEqual(expandKeywords("  g ,   food ", shortcuts: s),
                ["guitar", "food"], "trims whitespace")
}

// MARK: - Models

section("Models") {
    expectEqual(PhotoRef.bareUUID(fromLocalIdentifier: "ABCD-1234/L0/001"),
                "ABCD-1234", "bare UUID from local identifier")
}

// MARK: - MonthKey

section("MonthKey") {
    expectEqual(monthKey(for: utcDate(2024, 5, 9), calendar: utcCalendar), "2024-05", "format")
    expectEqual(monthKey(for: utcDate(999, 12, 1), calendar: utcCalendar), "0999-12", "zero pad")
    expect(isValidMonthKey("2024-05"), "valid month key")
    expect(!isValidMonthKey("2024-5"), "rejects single-digit month")
    expect(!isValidMonthKey("2024/05"), "rejects slash")
    expect(!isValidMonthKey("2024-05-01"), "rejects full date")
}

// MARK: - SessionSelector

section("SessionSelector") {
    let a = photo("a", date: utcDate(2024, 5, 2))
    let b = photo("b", date: utcDate(2024, 5, 1))
    let c = photo("c", date: nil)
    expectEqual(SessionSelector.sortedByDate([a, c, b]).map(\.uuid),
                ["b", "a", "c"], "sorts ascending, dateless last")

    let d = photo("d", date: utcDate(2024, 5, 3))
    expectEqual(SessionSelector.reviewQueue([a, b, d], reviewed: ["b"]).map(\.uuid),
                ["a", "d"], "review queue excludes reviewed, oldest first")

    let may1 = photo("m1", date: utcDate(2024, 5, 10))
    let jun = photo("j", date: utcDate(2024, 6, 10))
    let may2 = photo("m2", date: utcDate(2024, 5, 1))
    expectEqual(
        SessionSelector.chunkQueue([may1, jun, may2], month: "2024-05",
                                   reviewed: [], calendar: utcCalendar).map(\.uuid),
        ["m2", "m1"], "chunk filters to month, oldest first")

    let pool = (0..<10).map { photo("p\($0)") }
    var g1 = SeededGenerator(seed: 42), g2 = SeededGenerator(seed: 42)
    let batch1 = SessionSelector.randomBatch(pool, count: 3, using: &g1)
    let batch2 = SessionSelector.randomBatch(pool, count: 3, using: &g2)
    expectEqual(batch1.count, 3, "random batch caps at count")
    expectEqual(batch1.map(\.uuid), batch2.map(\.uuid), "random batch deterministic per seed")
    var g3 = SeededGenerator(seed: 1)
    expectEqual(SessionSelector.randomBatch([photo("a"), photo("b")], count: 20, using: &g3).count,
                2, "random batch clamps to pool size")
}

// MARK: - Stats

section("Stats") {
    let photos = [
        photo("a", date: utcDate(2024, 5, 1)),
        photo("b", date: utcDate(2024, 5, 2)),
        photo("c", date: utcDate(2024, 6, 1)),
        photo("d", date: nil),
    ]
    let statuses: [String: ReviewStatus] = ["a": .done, "b": .skipped, "c": .done]
    let r = buildStats(photos: photos, statuses: statuses, calendar: utcCalendar)
    expectEqual(r.total, 4, "total")
    expectEqual(r.count(.done), 2, "overall done")
    expectEqual(r.remaining, 1, "remaining")
    expectEqual(r.months["2024-05"]?.total, 2, "may total")
    expectEqual(r.months["2024-05"]?.left, 0, "may left")
    expectEqual(r.months["unknown"]?.left, 1, "unknown left")
    expectEqual(r.sortedMonthKeys, ["2024-05", "2024-06", "unknown"], "unknown sorts last")
}

// MARK: - Config

section("Config") {
    let url = FileManager.default.temporaryDirectory
        .appendingPathComponent("ansel-cfg-\(UUID().uuidString)")
        .appendingPathComponent("config.json")
    expectEqual(Config.load(from: url), Config.defaults, "missing config seeds defaults")
    expect(FileManager.default.fileExists(atPath: url.path), "defaults persisted to disk")
    let custom = Config(shortcuts: ["x": "xylophone"])
    try? custom.save(to: url)
    expectEqual(Config.load(from: url), custom, "save/load round trip")
}

// MARK: - ProgressStore (SQLite)

section("ProgressStore") {
    let store = try ProgressStore(path: tempDBURL())
    try store.record(uuid: "A", status: .done, caption: "hi", keywords: ["guitar", "food"])
    try store.record(uuid: "B", status: .skipped)
    expectEqual(try store.reviewedUUIDs(), ["A", "B"], "reviewed uuids")
    expectEqual(try store.allStatuses(), ["A": .done, "B": .skipped], "all statuses")
    expectEqual(try store.statusCounts(), [.done: 1, .skipped: 1], "status counts")

    // Overwrite keeps a single row.
    try store.record(uuid: "A", status: .done, keywords: ["guitar"])
    expectEqual(try store.reviewedUUIDs().count, 2, "overwrite keeps one row per uuid")

    // Resurface rules.
    let now = Date()
    let store2 = try ProgressStore(path: tempDBURL())
    try store2.record(uuid: "old", status: .skipped, now: now.addingTimeInterval(-8 * 86400))
    try store2.record(uuid: "recent", status: .skipped, now: now.addingTimeInterval(-1 * 86400))
    try store2.record(uuid: "done", status: .done, now: now.addingTimeInterval(-99 * 86400))
    let excluded = try store2.excludedUUIDs(resurfaceSkipsAfter: skipResurfaceWindow, now: now)
    expect(!excluded.contains("old"), "old skip resurfaces")
    expect(excluded.contains("recent"), "recent skip stays excluded")
    expect(excluded.contains("done"), "done never resurfaces")
    expectEqual(try store2.excludedUUIDs(), ["old", "recent", "done"],
                "no-window excludes everything")

    // Clear.
    expect(try store.clear(uuid: "A"), "clear returns true when row existed")
    expect(!(try store.clear(uuid: "A")), "clear returns false when absent")

    // Timestamp compatibility with Python isoformat.
    expect(ProgressStore.parseTimestamp("2026-09-17T12:34:56.789000+00:00") != nil,
           "parses legacy python isoformat")
    expect(ProgressStore.parseTimestamp(ProgressStore.timestamp(now)) != nil,
           "round-trips our timestamp")
}

section("ProgressStore import") {
    // Build a "source" DB (as the Python CLI would), then merge it into a fresh
    // store and confirm rows, statuses, and preserved timestamps carry over.
    let now = Date()
    let source = try ProgressStore(path: tempDBURL())
    try source.record(uuid: "A", status: .done, caption: "hi", keywords: ["guitar"])
    try source.record(uuid: "B", status: .skipped, now: now.addingTimeInterval(-8 * 86400))

    let dest = try ProgressStore(path: tempDBURL())
    try dest.record(uuid: "A", status: .skipped)  // pre-existing, should be overwritten
    let imported = try dest.importRows(from: source.url)
    expectEqual(imported, 2, "imports all source rows")
    expectEqual(try dest.allStatuses(), ["A": .done, "B": .skipped], "import overwrites by uuid")
    // B's original 8-day-old skip timestamp survives, so it resurfaces.
    let excluded = try dest.excludedUUIDs(resurfaceSkipsAfter: skipResurfaceWindow, now: now)
    expect(!excluded.contains("B"), "imported skip keeps its original age")
}

// MARK: - Summary

print("\n\(checks) checks, \(failures) failure(s)")
if failures > 0 { exit(1) }
print("✓ all AnselCore checks passed")
