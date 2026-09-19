#!/bin/bash
#
# Build Ansel.app without Xcode, using the Command Line Tools toolchain.
# Compiles the SwiftUI + PhotoKit app sources, links the AnselCore static
# library, assembles a .app bundle, and ad-hoc code-signs it.
#
# Usage:  ./build.sh          then open  build/Ansel.app
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CORE="$HERE/../AnselCore"
BUILD="$HERE/build"
APP="$BUILD/Ansel.app"
SDK="$(xcrun --show-sdk-path)"
ARCH="$(uname -m)"
TARGET="${ARCH}-apple-macosx13.0"

echo "▶ Building AnselCore (static) …"
( cd "$CORE" && swift build -c release --product AnselCore >/dev/null )
CORE_BUILD="$CORE/.build/release"

echo "▶ Compiling app sources …"
rm -rf "$BUILD"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# shellcheck disable=SC2046
swiftc \
  -sdk "$SDK" \
  -target "$TARGET" \
  -parse-as-library \
  -O \
  -I "$CORE_BUILD/Modules" \
  -L "$CORE_BUILD" -lAnselCore -lsqlite3 \
  -o "$APP/Contents/MacOS/Ansel" \
  $(find "$HERE/Ansel" -name '*.swift')

echo "▶ Writing Info.plist …"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>Ansel</string>
    <key>CFBundleDisplayName</key>     <string>Ansel</string>
    <key>CFBundleExecutable</key>      <string>Ansel</string>
    <key>CFBundleIdentifier</key>      <string>com.evanappel.ansel</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleShortVersionString</key> <string>0.1.0</string>
    <key>CFBundleVersion</key>         <string>1</string>
    <key>LSMinimumSystemVersion</key>  <string>13.0</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>NSPrincipalClass</key>        <string>NSApplication</string>
    <key>LSApplicationCategoryType</key> <string>public.app-category.photography</string>
    <key>NSPhotoLibraryUsageDescription</key>
        <string>Ansel reads your photos so you can caption and tag them.</string>
    <key>NSAppleEventsUsageDescription</key>
        <string>Ansel controls Photos to save the captions and keywords you enter.</string>
</dict>
</plist>
PLIST

printf 'APPL????' > "$APP/Contents/PkgInfo"

echo "▶ Ad-hoc code-signing …"
codesign --force --sign - --timestamp=none "$APP" >/dev/null

echo "✓ Built $APP"
echo "  Run it with:  open \"$APP\""
