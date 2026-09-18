import SwiftUI

@main
struct AnselApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .frame(minWidth: 920, minHeight: 660)
                .task { await model.bootstrap() }
        }
        .windowResizability(.contentMinSize)
    }
}
