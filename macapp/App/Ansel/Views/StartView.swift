import AnselCore
import SwiftUI
import UniformTypeIdentifiers

/// The mode chooser + progress summary — the GUI equivalent of picking between
/// `ansel review`, `chunk`, `random`, and `stats`.
struct StartView: View {
    @EnvironmentObject private var model: AppModel
    @State private var randomCount = 20
    @State private var selectedMonth = ""
    @State private var importMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header

                if let stats = model.stats {
                    StatsSummary(stats: stats)
                }

                VStack(alignment: .leading, spacing: 12) {
                    Text("Start a session").font(.headline)

                    modeButton(
                        title: "Review",
                        subtitle: "All unreviewed photos, oldest first — \(model.unreviewedCount) left",
                        systemImage: "photo.stack"
                    ) { model.startReview(mode: .review) }

                    HStack {
                        modeButton(
                            title: "One month",
                            subtitle: "A natural finish line",
                            systemImage: "calendar"
                        ) {
                            if !selectedMonth.isEmpty { model.startReview(mode: .chunk(month: selectedMonth)) }
                        }
                        Picker("", selection: $selectedMonth) {
                            Text("Choose…").tag("")
                            ForEach(model.availableMonths, id: \.self) { Text($0).tag($0) }
                        }
                        .labelsHidden()
                        .frame(width: 140)
                    }

                    HStack {
                        modeButton(
                            title: "Random batch",
                            subtitle: "Skips older than a week resurface",
                            systemImage: "shuffle"
                        ) { model.startReview(mode: .random(count: randomCount)) }
                        Stepper("\(randomCount)", value: $randomCount, in: 1...200)
                            .frame(width: 120)
                    }
                }
            }
            .padding(32)
        }
        .alert(
            "Import progress",
            isPresented: Binding(
                get: { importMessage != nil },
                set: { if !$0 { importMessage = nil } }
            )
        ) {
            Button("OK", role: .cancel) { importMessage = nil }
        } message: {
            Text(importMessage ?? "")
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading) {
                Text("Ansel").font(.largeTitle.bold())
                Text("Caption and tag your Photos library, a little at a time.")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                runImport()
            } label: { Label("Import progress…", systemImage: "square.and.arrow.down") }
                .help("Merge an existing photo_review.db into your progress")
            Button {
                Task { await model.loadLibrary() }
            } label: { Image(systemName: "arrow.clockwise") }
                .help("Reload library")
        }
    }

    /// Pick an existing `photo_review.db` and merge it into the current store.
    private func runImport() {
        let panel = NSOpenPanel()
        panel.title = "Import progress database"
        panel.message = "Choose an existing photo_review.db to merge into your progress."
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.allowedContentTypes =
            [UTType(filenameExtension: "db"), .database].compactMap { $0 }
        panel.allowsOtherFileTypes = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { importMessage = await model.importProgress(from: url) }
    }

    private func modeButton(
        title: String, subtitle: String, systemImage: String, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: systemImage).font(.title2).frame(width: 32)
                VStack(alignment: .leading) {
                    Text(title).font(.body.bold())
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.vertical, 4)
            .contentShape(Rectangle())
        }
        .buttonStyle(.bordered)
    }
}

/// Overall + per-month progress table (the GUI form of `ansel stats`).
struct StatsSummary: View {
    let stats: StatsReport

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Progress").font(.headline)
            Text("\(stats.total) photos · \(stats.count(.done)) done · "
                 + "\(stats.count(.skipped)) skipped · \(stats.count(.delete)) to delete · "
                 + "\(stats.count(.error)) errors · \(stats.remaining) remaining")
                .font(.callout)
                .foregroundStyle(.secondary)
            ProgressView(
                value: Double(stats.count(.done)),
                total: Double(max(stats.total, 1))
            )
        }
        .padding()
        .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }
}
