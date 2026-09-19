import AnselCore
import Photos
import SwiftUI

/// Top-level app state: permission, the loaded library, the chosen session mode,
/// and progress stats. Owns the `ProgressStore`, `PhotoLibrary`, and `PhotosWriter`.
@MainActor
final class AppModel: ObservableObject {
    enum Stage: Equatable {
        case launching
        case permissionDenied
        case loading
        case choosing
        case reviewing
        case failed(String)
    }

    @Published private(set) var stage: Stage = .launching
    @Published private(set) var photos: [PhotoRef] = []
    @Published private(set) var stats: StatsReport?
    @Published private(set) var review: ReviewViewModel?

    let library = PhotoLibrary()
    let writer = PhotosWriter()
    private(set) var config = Config.defaults
    private var store: ProgressStore?

    /// Request Photos access, open the store + config, then load the library.
    func bootstrap() async {
        let status = await library.requestAccess()
        guard status == .authorized || status == .limited else {
            stage = .permissionDenied
            return
        }
        config = Config.load(from: Paths.configURL)
        do {
            store = try ProgressStore(path: Paths.databaseURL)
        } catch {
            stage = .failed("Couldn't open the progress database: \(error)")
            return
        }
        await loadLibrary()
    }

    /// Fetch the library and recompute stats. Returns to the mode chooser.
    func loadLibrary() async {
        stage = .loading
        let refs = library.loadAll()
        photos = refs
        if let store {
            stats = buildStats(photos: refs, statuses: (try? store.allStatuses()) ?? [:])
        }
        stage = .choosing
    }

    /// Build the session queue for `mode` and enter the review loop.
    func startReview(mode: SessionMode) {
        guard let store else { return }
        let reviewed = (try? store.reviewedUUIDs()) ?? []
        let queue: [PhotoRef]
        switch mode {
        case .review:
            queue = SessionSelector.reviewQueue(photos, reviewed: reviewed)
        case .chunk(let month):
            queue = SessionSelector.chunkQueue(photos, month: month, reviewed: reviewed)
        case .random(let count):
            let excluded = (try? store.excludedUUIDs(resurfaceSkipsAfter: skipResurfaceWindow)) ?? []
            let eligible = SessionSelector.randomEligible(photos, excluded: excluded)
            var generator = SystemRandomNumberGenerator()
            queue = SessionSelector.randomBatch(eligible, count: count, using: &generator)
        }
        guard !queue.isEmpty else { return }
        review = ReviewViewModel(queue: queue, library: library, writer: writer,
                                 store: store, config: config)
        stage = .reviewing
    }

    /// Merge an existing `photo_review.db` (from the CLI or a backup) into the
    /// current progress store, then reload so stats reflect it. Returns a short
    /// status message for the UI.
    func importProgress(from url: URL) async -> String {
        guard let store else { return "No progress database is open." }
        do {
            let count = try store.importRows(from: url)
            await loadLibrary()
            return "Imported \(count) record\(count == 1 ? "" : "s")."
        } catch {
            return "Import failed: \(error)"
        }
    }

    /// Leave the review loop, reload the library so stats reflect the session.
    func endReview() async {
        review = nil
        await loadLibrary()
    }

    /// Month keys present in the library, newest first — for the chunk picker.
    var availableMonths: [String] {
        guard let stats else { return [] }
        return stats.sortedMonthKeys.filter { $0 != "unknown" }.reversed()
    }

    /// Count of never-reviewed photos, for the review-mode button subtitle.
    var unreviewedCount: Int {
        guard let store else { return photos.count }
        let reviewed = (try? store.reviewedUUIDs()) ?? []
        return photos.filter { !reviewed.contains($0.uuid) }.count
    }
}
