import AnselCore
import AppKit
import AVFoundation
import Photos

/// Reads the system Photos library via PhotoKit and adapts assets into the pure
/// `PhotoRef` values the core (`SessionSelector`, `buildStats`) works with.
///
/// PhotoKit needs only a Photos-access permission prompt — not Full Disk Access,
/// which the Python/osxphotos path required. Caption/keyword *reads* still go
/// through `PhotosWriter` (AppleScript), since PhotoKit can't read those fields.
@MainActor
final class PhotoLibrary {
    /// Live `PHAsset`s keyed by localIdentifier, for image/metadata requests on
    /// the currently-displayed photo.
    private var assetsByLocalID: [String: PHAsset] = [:]

    /// Prompt for (or return existing) Photos access. `.readWrite` so AppleScript
    /// edits and any future PhotoKit changes are permitted.
    func requestAccess() async -> PHAuthorizationStatus {
        await PHPhotoLibrary.requestAuthorization(for: .readWrite)
    }

    var authorizationStatus: PHAuthorizationStatus {
        PHPhotoLibrary.authorizationStatus(for: .readWrite)
    }

    /// Fetch every photo and video, oldest first, as lightweight `PhotoRef`s.
    /// Filenames and album membership are filled lazily per displayed photo, so
    /// this stays fast even on large libraries.
    func loadAll() -> [PhotoRef] {
        let options = PHFetchOptions()
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: true)]
        let result = PHAsset.fetchAssets(with: options)

        assetsByLocalID.removeAll(keepingCapacity: true)
        var refs: [PhotoRef] = []
        refs.reserveCapacity(result.count)
        result.enumerateObjects { asset, _, _ in
            self.assetsByLocalID[asset.localIdentifier] = asset
            refs.append(
                PhotoRef(
                    uuid: PhotoRef.bareUUID(fromLocalIdentifier: asset.localIdentifier),
                    localIdentifier: asset.localIdentifier,
                    filename: "",
                    date: asset.creationDate,
                    isVideo: asset.mediaType == .video
                )
            )
        }
        return refs
    }

    func asset(for ref: PhotoRef) -> PHAsset? { assetsByLocalID[ref.localIdentifier] }

    /// The photo's original filename (e.g. `IMG_1234.HEIC`).
    func originalFilename(for asset: PHAsset) -> String {
        PHAssetResource.assetResources(for: asset).first?.originalFilename ?? "(unknown)"
    }

    /// Names of user albums the photo belongs to.
    func albumNames(for asset: PHAsset) -> [String] {
        let collections = PHAssetCollection.fetchAssetCollectionsContaining(
            asset, with: .album, options: nil
        )
        var names: [String] = []
        collections.enumerateObjects { collection, _, _ in
            if let title = collection.localizedTitle { names.append(title) }
        }
        return names.sorted()
    }

    /// Load a playable item for a video asset (downloading from iCloud if needed).
    func requestPlayerItem(for asset: PHAsset) async -> AVPlayerItem? {
        await withCheckedContinuation { continuation in
            let options = PHVideoRequestOptions()
            options.isNetworkAccessAllowed = true
            options.deliveryMode = .automatic
            PHImageManager.default().requestPlayerItem(forVideo: asset, options: options) { item, _ in
                continuation.resume(returning: item)
            }
        }
    }

    /// Load a display image for a photo or a poster frame for a video.
    func requestImage(for asset: PHAsset, targetSize: CGSize) async -> NSImage? {
        await withCheckedContinuation { continuation in
            let options = PHImageRequestOptions()
            options.deliveryMode = .highQualityFormat
            options.isNetworkAccessAllowed = true  // download iCloud originals if needed
            options.resizeMode = .fast
            var resumed = false
            PHImageManager.default().requestImage(
                for: asset,
                targetSize: targetSize,
                contentMode: .aspectFit,
                options: options
            ) { image, info in
                // The manager may call back twice (a fast thumbnail then the full
                // image); resume once, on the first non-degraded result or the last.
                let isDegraded = (info?[PHImageResultIsDegradedKey] as? Bool) ?? false
                if resumed { return }
                if !isDegraded || image == nil {
                    resumed = true
                    continuation.resume(returning: image)
                }
            }
        }
    }
}
