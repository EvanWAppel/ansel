import AnselCore
import AppKit
import Photos
import SwiftUI

/// Drives one review session: the queue, the current photo's display state, and
/// the caption/keyword writes. Ports the Python `run_session` loop into a GUI
/// view model — one photo at a time, progress committed after each.
@MainActor
final class ReviewViewModel: ObservableObject {
    // Session queue
    @Published private(set) var queue: [PhotoRef] = []
    @Published private(set) var index = 0

    // Current photo display state
    @Published private(set) var image: NSImage?
    @Published private(set) var filename = ""
    @Published private(set) var albums: [String] = []
    @Published private(set) var existingCaption: String?
    @Published private(set) var existingKeywords: [String] = []
    @Published private(set) var isLoadingImage = false

    // Input fields
    @Published var captionField = ""
    @Published var keywordsField = ""

    // Feedback for the last action (mirrors the CLI's per-photo echo).
    @Published private(set) var lastMessage: String?
    @Published private(set) var finished = false

    let shortcuts: [String: String]

    private let library: PhotoLibrary
    private let writer: PhotosWriter
    private let store: ProgressStore

    init(queue: [PhotoRef], library: PhotoLibrary, writer: PhotosWriter,
         store: ProgressStore, config: Config) {
        self.queue = queue
        self.library = library
        self.writer = writer
        self.store = store
        self.shortcuts = config.shortcuts
    }

    var current: PhotoRef? { index < queue.count ? queue[index] : nil }
    var progressText: String { "\(min(index + 1, queue.count)) / \(queue.count)" }

    /// Load the current photo's image and existing metadata for display.
    func loadCurrent() async {
        guard let ref = current, let asset = library.asset(for: ref) else {
            finished = true
            return
        }
        captionField = ""
        keywordsField = ""
        filename = library.originalFilename(for: asset)
        albums = library.albumNames(for: asset)
        existingCaption = (try? writer.readDescription(localIdentifier: ref.localIdentifier)) ?? nil
        existingKeywords = (try? writer.readKeywords(localIdentifier: ref.localIdentifier)) ?? []

        isLoadingImage = true
        image = nil
        let size = CGSize(width: 1600, height: 1600)
        let loaded = await library.requestImage(for: asset, targetSize: size)
        // Guard against a stale load if the user advanced quickly.
        if current?.localIdentifier == ref.localIdentifier {
            image = loaded
            isLoadingImage = false
        }
    }

    /// Save caption + expanded keywords, like the CLI's `write_metadata` path.
    func save() async {
        guard let ref = current else { return }
        let caption = captionField.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !caption.isEmpty else { return }
        let keywords = expandKeywords(keywordsField, shortcuts: shortcuts)
        do {
            try writer.writeMetadata(localIdentifier: ref.localIdentifier,
                                     caption: caption, keywords: keywords)
            try store.record(uuid: ref.uuid, status: .done, caption: caption, keywords: keywords)
            lastMessage = keywords.isEmpty ? "✓ saved" : "✓ saved (\(keywords.joined(separator: ", ")))"
        } catch {
            try? store.record(uuid: ref.uuid, status: .error, caption: caption,
                              keywords: keywords, error: "\(error)")
            lastMessage = "! write failed — logged as error: \(error)"
        }
        advance()
    }

    /// Skip: record status `.skipped` and move on.
    func skip() {
        guard let ref = current else { return }
        try? store.record(uuid: ref.uuid, status: .skipped)
        lastMessage = "· skipped"
        advance()
    }

    /// Mark for deletion: add to the deletion album, record status `.delete`.
    func markForDeletion() {
        guard let ref = current else { return }
        do {
            try writer.markForDeletion(localIdentifier: ref.localIdentifier)
            try store.record(uuid: ref.uuid, status: .delete)
            lastMessage = "✗ added to “\(PhotosWriter.deletionAlbum)” album — batch-delete it in Photos"
        } catch {
            try? store.record(uuid: ref.uuid, status: .error, error: "\(error)")
            lastMessage = "! marking failed — logged as error: \(error)"
        }
        advance()
    }

    private func advance() {
        index += 1
        if current == nil { finished = true }
    }
}
