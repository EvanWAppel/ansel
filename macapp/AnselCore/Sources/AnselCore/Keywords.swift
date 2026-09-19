import Foundation

/// Split comma-separated keyword entry, expanding shortcuts and deduping in order.
///
/// Direct port of the Python `expand_keywords`: tokens matching a shortcut key
/// are replaced by the shortcut's expansion; everything else passes through as a
/// freeform keyword. Empty tokens are dropped; order is preserved; duplicates
/// (after expansion) are removed.
public func expandKeywords(_ raw: String, shortcuts: [String: String]) -> [String] {
    var keywords: [String] = []
    for token in raw.split(separator: ",", omittingEmptySubsequences: false) {
        let trimmed = token.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { continue }
        let keyword = shortcuts[trimmed] ?? trimmed
        if !keywords.contains(keyword) {
            keywords.append(keyword)
        }
    }
    return keywords
}
