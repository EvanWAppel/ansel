// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "AnselCore",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "AnselCore", type: .static, targets: ["AnselCore"]),
        .executable(name: "ansel-core-check", targets: ["AnselCoreCheck"]),
    ],
    targets: [
        .target(
            name: "AnselCore",
            linkerSettings: [.linkedLibrary("sqlite3")]
        ),
        // A dependency-free check runner so the pure logic is verifiable under
        // Command Line Tools (XCTest/swift-testing need full Xcode). Once Xcode
        // is installed these become idiomatic `import Testing` tests.
        .executableTarget(
            name: "AnselCoreCheck",
            dependencies: ["AnselCore"]
        ),
    ]
)
