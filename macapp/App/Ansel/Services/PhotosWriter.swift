import Foundation

/// Writes captions/keywords and deletion-album membership to Photos via
/// AppleScript — the only interface Apple exposes for these fields (PhotoKit
/// has no API to set a photo's description or keywords). This mirrors what the
/// Python `photoscript` bridge did, called straight from Swift.
///
/// The Photos AppleScript object is addressed by `media item id "<localIdentifier>"`,
/// where `<localIdentifier>` is PhotoKit's `PHAsset.localIdentifier` (`"<uuid>/L0/001"`)
/// — exactly the id form Photos expects, so no transformation is needed.
///
/// Every method throws on failure; callers log status `.error` rather than crash,
/// matching the Python session's behavior. We never swallow AppleScript errors.
public struct PhotosWriter {
    public static let deletionAlbum = "Marked for Deletion"

    public enum WriteError: Error, CustomStringConvertible {
        case applescript(String)
        public var description: String {
            switch self {
            case .applescript(let m): return m
            }
        }
    }

    public init() {}

    /// Set a photo's caption (Photos "description") and merge keywords with any
    /// it already has, storing the union sorted — identical to the Python
    /// `write_metadata`.
    public func writeMetadata(localIdentifier id: String, caption: String?, keywords: [String]) throws {
        if let caption, !caption.isEmpty {
            try run("""
                tell application "Photos"
                    set description of media item id \(quote(id)) to \(quote(caption))
                end tell
                """)
        }
        guard !keywords.isEmpty else { return }
        let existing = try readKeywords(localIdentifier: id)
        let merged = Set(existing).union(keywords).sorted()
        try run("""
            tell application "Photos"
                set keywords of media item id \(quote(id)) to \(list(merged))
            end tell
            """)
    }

    /// Add a photo to the deletion album (creating it if needed). Photos'
    /// AppleScript interface can't delete media items, so — as in the Python
    /// version — deletion is staged in an album the user batch-deletes by hand.
    public func markForDeletion(localIdentifier id: String) throws {
        try run("""
            tell application "Photos"
                if not (exists album \(quote(Self.deletionAlbum))) then
                    make new album named \(quote(Self.deletionAlbum))
                end if
                add {media item id \(quote(id))} to album \(quote(Self.deletionAlbum))
            end tell
            """)
    }

    // MARK: - Reads (existing metadata, to display before editing)

    /// The photo's current caption/description, or nil if unset.
    public func readDescription(localIdentifier id: String) throws -> String? {
        let descriptor = try eval("""
            tell application "Photos"
                get description of media item id \(quote(id))
            end tell
            """)
        let value = descriptor.stringValue
        return (value?.isEmpty ?? true) ? nil : value
    }

    /// The photo's current keywords (empty if none).
    public func readKeywords(localIdentifier id: String) throws -> [String] {
        let descriptor = try eval("""
            tell application "Photos"
                get keywords of media item id \(quote(id))
            end tell
            """)
        // A `missing value` or empty list decodes to no usable string items.
        guard descriptor.numberOfItems > 0 else {
            if let single = descriptor.stringValue, !single.isEmpty { return [single] }
            return []
        }
        return (1...descriptor.numberOfItems).compactMap {
            descriptor.atIndex($0)?.stringValue
        }
    }

    // MARK: - AppleScript plumbing

    @discardableResult
    private func run(_ source: String) throws -> NSAppleEventDescriptor {
        try eval(source)
    }

    private func eval(_ source: String) throws -> NSAppleEventDescriptor {
        var errorInfo: NSDictionary?
        guard let script = NSAppleScript(source: source) else {
            throw WriteError.applescript("could not compile AppleScript")
        }
        let result = script.executeAndReturnError(&errorInfo)
        if let errorInfo {
            let message = errorInfo[NSAppleScript.errorMessage] as? String
                ?? "AppleScript error \(errorInfo)"
            throw WriteError.applescript(message)
        }
        return result
    }

    /// Quote a Swift string as an AppleScript string literal (escape `\` and `"`),
    /// matching the Python `_applescript_str`.
    private func quote(_ text: String) -> String {
        "\"" + text.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }

    /// An AppleScript list literal of quoted strings: `{"a", "b"}`.
    private func list(_ items: [String]) -> String {
        "{" + items.map(quote).joined(separator: ", ") + "}"
    }
}
