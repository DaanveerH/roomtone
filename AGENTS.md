# Roomtone

Purpose: a small macOS Sonos controller with optional silent video above its controls.
Keep it lightweight. No Electron, web framework, cloud service, account, or AI search.

- `App.swift`: AppKit window, WKWebView, menu, and local controller lifecycle.
- `NativeVideo.swift`: retained AVPlayer, speaker-clock sync, fast show/hide.
- `web/`: plain HTML, CSS, and JavaScript controls.
- `server.py`, `sonos.py`: authenticated loopback API (8776), discovery, speaker commands.
- `media.py`: network audio server (8775), registered files only, byte-range seeking.
- `library.py`, `video.py`: local search and cached FFmpeg preparation.
- `build.sh`: builds `dist/Roomtone.app`; `install.sh` installs it and its audio helper.

Checks: `python3 -m unittest discover -v` and `./build.sh` on macOS with FFmpeg.
Tests use temporary data and mock speakers. Never change real speaker playback in automated tests.
Keep video muted with audio tracks disabled. Hiding video must not stop Sonos or reload the player.
Keep controller authentication and registered-file restrictions. Do not commit media, settings, logs, or personal paths.
Use only system frameworks and the Python standard library; FFmpeg stays an external dependency.
