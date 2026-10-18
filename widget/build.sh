#!/bin/bash
# Builds "Pitwall Widget.app":
#   - the floating desktop panel (PitwallWidget.swift), and
#   - a WidgetKit extension (TitleOddsWidget.swift) you can add to the macOS desktop via "Edit Widgets".
# WidgetKit only loads signed extensions: set SIGN_ID to your "Apple Development: …" identity
# (security find-identity -v -p codesigning). Without it the panel still works, the widget extension won't.
# The first signing shows a keychain prompt ("codesign wants to access key…"): enter your login
# password and choose "Always Allow".
# Usage: widget/build.sh            build only
#        widget/build.sh --install  build, copy to ~/Applications and launch
set -euo pipefail
cd "$(dirname "$0")"
APP="Pitwall Widget.app"
EXT="$APP/Contents/PlugIns/TitleOdds.appex"
SIGN_ID="${SIGN_ID:-$(security find-identity -v -p codesigning 2>/dev/null | sed -n 's/.*"\(Apple Development[^"]*\)".*/\1/p' | head -1)}"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$EXT/Contents/MacOS"

swiftc -O -parse-as-library -target arm64-apple-macos14.0 PitwallWidget.swift -o "$APP/Contents/MacOS/PitwallWidget"
swiftc -O -parse-as-library -application-extension -target arm64-apple-macos14.0 TitleOddsWidget.swift \
  -o "$EXT/Contents/MacOS/TitleOdds"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Pitwall Widget</string>
  <key>CFBundleDisplayName</key><string>Pitwall</string>
  <key>CFBundleIdentifier</key><string>io.github.emrtunali.pitwall.widget</string>
  <key>CFBundleExecutable</key><string>PitwallWidget</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.1</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
cat > "$EXT/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>TitleOdds</string>
  <key>CFBundleDisplayName</key><string>Pitwall</string>
  <key>CFBundleIdentifier</key><string>io.github.emrtunali.pitwall.widget.titleodds</string>
  <key>CFBundleExecutable</key><string>TitleOdds</string>
  <key>CFBundlePackageType</key><string>XPC!</string>
  <key>CFBundleShortVersionString</key><string>1.1</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSExtension</key><dict><key>NSExtensionPointIdentifier</key><string>com.apple.widgetkit-extension</string></dict>
</dict></plist>
PLIST
cat > /tmp/pitwall-ext.entitlements <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.app-sandbox</key><true/>
  <key>com.apple.security.network.client</key><true/>
</dict></plist>
PLIST
if [ -n "$SIGN_ID" ]; then
  codesign --force --sign "$SIGN_ID" --entitlements /tmp/pitwall-ext.entitlements --timestamp=none "$EXT"
  codesign --force --sign "$SIGN_ID" --timestamp=none "$APP"
  echo "Signed with: $SIGN_ID"
else
  codesign --force --sign - "$APP" >/dev/null 2>&1 || true
  echo "No Apple Development identity found: the desktop panel works, the WidgetKit widget will not load."
fi
echo "Built $(pwd)/$APP"
if [ "${1:-}" = "--install" ]; then
  # WidgetKit discovers extensions from installed apps: copy to ~/Applications and launch once.
  mkdir -p "$HOME/Applications"
  pkill -x PitwallWidget 2>/dev/null || true
  rm -rf "$HOME/Applications/$APP" && cp -R "$APP" "$HOME/Applications/"
  open "$HOME/Applications/$APP"
  echo "Installed. Right-click the desktop → Edit Widgets… → search \"Pitwall\"."
fi
