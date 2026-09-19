import Foundation

/// Where the app keeps its progress DB and config. Unlike the Python CLI (which
/// used the working directory), a GUI app stores per-user data under
/// Application Support.
enum Paths {
    static var appSupportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Ansel", isDirectory: true)
    }

    /// Schema-compatible with the Python CLI's `photo_review.db`.
    static var databaseURL: URL { appSupportDir.appendingPathComponent("photo_review.db") }

    static var configURL: URL { appSupportDir.appendingPathComponent("config.json") }
}
