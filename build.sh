#!/bin/zsh
set -euo pipefail
root="${0:A:h}"
app="$root/dist/Roomtone.app"
builddir=$(mktemp -d)
trap 'rm -rf "$builddir"' EXIT
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/service/web"
cp "$root/App.swift" "$builddir/main.swift"
/usr/bin/swiftc -target "$(uname -m)-apple-macos13.0" -O "$builddir/main.swift" "$root/NativeVideo.swift" -o "$app/Contents/MacOS/Roomtone" -framework Cocoa -framework WebKit -framework AVFoundation
for file in server sonos library media video; do
  cp "$root/$file.py" "$app/Contents/Resources/service/"
done
cp "$root/web/"* "$app/Contents/Resources/service/web/"
/usr/bin/swift "$root/icon.swift" "$builddir"
/usr/bin/iconutil -c icns "$builddir/Roomtone.iconset" -o "$app/Contents/Resources/AppIcon.icns"
/usr/bin/python3 "$root/install.py" "$app"
/usr/bin/codesign --force --deep --sign - "$app"
echo "Built $app"
