"""Build bundle metadata; install the persistent audio helper only when requested."""
import argparse
import plistlib
from pathlib import Path

LABEL = 'io.github.daanveerh.roomtone.media'

def bundle_info():
    return {
        'CFBundleExecutable': 'Roomtone',
        'CFBundleIdentifier': 'io.github.daanveerh.roomtone',
        'CFBundleName': 'Roomtone',
        'CFBundleDisplayName': 'Roomtone',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '1',
        'CFBundleIconFile': 'AppIcon.icns',
        'LSMinimumSystemVersion': '13.0',
        'NSHighResolutionCapable': True,
        'NSLocalNetworkUsageDescription': 'Find and control your Sonos speakers on this Wi-Fi network.',
        'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True, 'NSAllowsArbitraryLoads': True},
        'NSHumanReadableCopyright': 'Copyright 2026 Daanveer Hehr. MIT License.',
    }

def write_metadata(app, home, media_agent=False):
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(bundle_info()))
    if not media_agent:
        return
    service = app / 'Contents/Resources/service'
    support = home / 'Library/Application Support/Roomtone'
    support.mkdir(parents=True, exist_ok=True)
    agents = home / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    job = {
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/python3', str(service / 'media.py')],
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 5,
        'WorkingDirectory': str(service),
        'StandardOutPath': str(support / 'media.log'),
        'StandardErrorPath': str(support / 'media.log'),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
    }
    (agents / (LABEL + '.plist')).write_bytes(plistlib.dumps(job))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--media-agent', action='store_true')
    args = parser.parse_args()
    write_metadata(args.app.resolve(), Path.home(), args.media_agent)
