import SwiftUI

/// Switches the whole window between launch/permission/loading/choose/review.
struct RootView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        switch model.stage {
        case .launching:
            ProgressView("Starting…").controlSize(.large)
        case .permissionDenied:
            PermissionDeniedView()
        case .loading:
            ProgressView("Loading your Photos library…").controlSize(.large)
        case .choosing:
            StartView()
        case .reviewing:
            if let review = model.review {
                ReviewView(vm: review)
            } else {
                ProgressView()
            }
        case .failed(let message):
            VStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 48)).foregroundStyle(.orange)
                Text("Something went wrong").font(.title2.bold())
                Text(message).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .padding(40)
        }
    }
}

/// Shown when the user hasn't granted Photos access. Points at System Settings,
/// the native equivalent of the Python README's permission notes.
struct PermissionDeniedView: View {
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "lock.circle")
                .font(.system(size: 56))
                .foregroundStyle(.secondary)
            Text("Ansel needs access to your Photos library")
                .font(.title2.bold())
            Text("Open System Settings → Privacy & Security → Photos and enable Ansel, "
                 + "then quit and reopen the app.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .frame(maxWidth: 420)
            Button("Open Privacy Settings") {
                if let url = URL(string:
                    "x-apple.systempreferences:com.apple.preference.security?Privacy_Photos") {
                    NSWorkspace.shared.open(url)
                }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(40)
    }
}
