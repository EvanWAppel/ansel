import AVKit
import SwiftUI

/// The full-window review loop: photo on the left, metadata + caption/keyword
/// entry on the right. Ports the Python `run_session` prompts to a GUI form.
struct ReviewView: View {
    @ObservedObject var vm: ReviewViewModel
    @EnvironmentObject private var model: AppModel
    @FocusState private var captionFocused: Bool

    var body: some View {
        Group {
            if vm.finished {
                SessionDoneView(message: vm.lastMessage) {
                    Task { await model.endReview() }
                }
            } else {
                HStack(spacing: 0) {
                    photoPane
                    Divider()
                    editorPane.frame(width: 360)
                }
            }
        }
        .task(id: vm.index) { await vm.loadCurrent() }
    }

    // MARK: - Photo

    private var photoPane: some View {
        ZStack {
            Color.black.opacity(0.9)
            if let player = vm.player {
                VideoPlayer(player: player).padding(12)
            } else if let image = vm.image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(12)
            } else if vm.isLoadingImage {
                ProgressView().controlSize(.large).tint(.white)
            } else {
                VStack {
                    Image(systemName: vm.current?.isVideo == true ? "video.slash" : "photo")
                        .font(.system(size: 48))
                    Text("Preview unavailable")
                }
                .foregroundStyle(.white.opacity(0.6))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Editor

    private var editorPane: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text(vm.progressText).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("End session") { Task { await model.endReview() } }
                    .buttonStyle(.link)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(vm.filename).font(.headline).lineLimit(1).truncationMode(.middle)
                Text(dateText).font(.caption).foregroundStyle(.secondary)
                if !vm.albums.isEmpty {
                    Text("Albums: \(vm.albums.joined(separator: ", "))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }

            if vm.existingCaption != nil || !vm.existingKeywords.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    if let c = vm.existingCaption {
                        Text("Current caption: \(c)").font(.caption)
                    }
                    if !vm.existingKeywords.isEmpty {
                        Text("Current keywords: \(vm.existingKeywords.joined(separator: ", "))")
                            .font(.caption)
                    }
                }
                .foregroundStyle(.secondary)
            }

            Divider()

            VStack(alignment: .leading, spacing: 6) {
                Text("Caption").font(.subheadline.bold())
                TextField("Describe this photo…", text: $vm.captionField, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...5)
                    .focused($captionFocused)
                    .onSubmit { Task { await save() } }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Keywords").font(.subheadline.bold())
                TextField("g, beach day, t", text: $vm.keywordsField)
                    .textFieldStyle(.roundedBorder)
                Text(shortcutHint).font(.caption2).foregroundStyle(.secondary)
            }

            Spacer()

            if let message = vm.lastMessage {
                Text(message).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }

            actionButtons
        }
        .padding(20)
        .onAppear { captionFocused = true }
        .onChange(of: vm.index) { _ in captionFocused = true }
    }

    private var actionButtons: some View {
        HStack {
            Button("Delete", role: .destructive) { vm.markForDeletion() }
                .keyboardShortcut(.delete, modifiers: .command)
            Button("Skip") { vm.skip() }
                .keyboardShortcut(.rightArrow, modifiers: .command)
            Spacer()
            Button("Save") { Task { await save() } }
                .keyboardShortcut(.return, modifiers: .command)
                .buttonStyle(.borderedProminent)
                .disabled(vm.captionField.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private func save() async {
        await vm.save()
    }

    private var dateText: String {
        guard let date = vm.current?.date else { return "unknown date" }
        return date.formatted(date: .abbreviated, time: .shortened)
    }

    private var shortcutHint: String {
        let pairs = vm.shortcuts.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }
            .joined(separator: ", ")
        return pairs.isEmpty ? "Comma-separated; merged with existing." : "Shortcuts: \(pairs)"
    }
}

struct SessionDoneView: View {
    let message: String?
    let onDone: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 56)).foregroundStyle(.green)
            Text("Session complete 🎉").font(.title2.bold())
            if let message { Text(message).foregroundStyle(.secondary) }
            Button("Back to start", action: onDone).buttonStyle(.borderedProminent)
        }
        .padding(40)
    }
}
