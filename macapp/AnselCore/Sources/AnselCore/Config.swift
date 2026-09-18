import Foundation

/// Keyword shortcuts, keyed by abbreviation. Mirrors the Python `[shortcuts]`
/// TOML table; here persisted as JSON in the app's Application Support dir.
public struct Config: Codable, Equatable, Sendable {
    public var shortcuts: [String: String]

    public init(shortcuts: [String: String]) {
        self.shortcuts = shortcuts
    }

    /// The same defaults the Python `DEFAULT_CONFIG` seeds on first run.
    public static let defaults = Config(shortcuts: [
        "g": "guitar",
        "f": "food",
        "t": "travel",
        "n": "nature",
        "p": "people",
        "w": "work",
    ])

    /// Load config from `url`, seeding (and writing) defaults if absent or unreadable.
    public static func load(from url: URL) -> Config {
        guard let data = try? Data(contentsOf: url),
              let config = try? JSONDecoder().decode(Config.self, from: data)
        else {
            let defaults = Config.defaults
            try? defaults.save(to: url)
            return defaults
        }
        return config
    }

    /// Persist config to `url` as pretty-printed JSON, creating parent dirs.
    public func save(to url: URL) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(self).write(to: url)
    }
}
