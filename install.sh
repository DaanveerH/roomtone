#!/bin/zsh
set -euo pipefail
root="${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg first: brew install ffmpeg'; exit 1; }
command -v ffprobe >/dev/null || { echo 'Install FFmpeg first: brew install ffmpeg'; exit 1; }
"$root/build.sh"
app="$HOME/Applications/Roomtone.app"
job="$HOME/Library/LaunchAgents/io.github.daanveerh.roomtone.media.plist"
osascript -e 'if application "Roomtone" is running then tell application "Roomtone" to quit' 2>/dev/null || true
launchctl bootout "gui/$(id -u)/io.github.daanveerh.roomtone.media" 2>/dev/null || true
mkdir -p "$HOME/Applications"
ditto "$root/dist/Roomtone.app" "$app"
/usr/bin/python3 "$root/install.py" "$app" --media-agent
launchctl bootstrap "gui/$(id -u)" "$job"
echo "Installed. Open Roomtone from ~/Applications."
