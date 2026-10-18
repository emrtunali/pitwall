#!/bin/bash
# Builds "Pitwall Widget.app" next to this script. Needs the Swift toolchain (Xcode or Command Line Tools).
set -euo pipefail
cd "$(dirname "$0")"
APP="Pitwall Widget.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
swiftc -O -parse-as-library PitwallWidget.swift -o "$APP/Contents/MacOS/PitwallWidget"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Pitwall Widget</string>
  <key>CFBundleIdentifier</key><string>io.github.emrtunali.pitwall.widget</string>
  <key>CFBundleExecutable</key><string>PitwallWidget</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "Built $(pwd)/$APP"
