# Roomtone

A lightweight macOS controller for Sonos, with a built-in silent video player.
Your speakers play the sound. Video sits above the controls in the same window.

- Play local music and videos; search by name, with typo tolerance.
- Control rooms, groups, volume, playback, and saved moments.
- Show or hide video with **⌘⇧V**, without stopping the music.
- Native macOS player, plain HTML/CSS/JS controls, Python standard library. No Electron, accounts, cloud, or IINA.

## Install

Requires macOS 13+, Apple Command Line Tools (`xcode-select --install`), and [Homebrew](https://brew.sh).

```sh
brew install ffmpeg
git clone https://github.com/DaanveerH/roomtone.git
cd roomtone
./install.sh
open ~/Applications/Roomtone.app
```

Use the same network as your Sonos. Allow local network access if macOS asks.
Add a music folder under **Your music**, choose your rooms, then play a file.

Video follows the speaker clock; use **Video timing** to adjust it. Sync is approximate.
Some video formats need preparation or are unsupported. First audio playback can take time to prepare.

Everything stays local. An audio helper keeps music playing after you quit.
It serves prepared audio on port 8775 to your network: use a trusted network.
Settings and cached media live in `~/Library/Application Support/Roomtone`.
To stop the helper: `launchctl bootout gui/$(id -u)/io.github.daanveerh.roomtone.media`.
To prevent it restarting at login, remove `~/Library/LaunchAgents/io.github.daanveerh.roomtone.media.plist`.

Build only: `./build.sh`. Test: `python3 -m unittest discover -v`.

MIT licensed. Independent project; not affiliated with Sonos.
