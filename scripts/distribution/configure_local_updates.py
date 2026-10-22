"""Configure the local native shell with the shared, public update trust root."""
import argparse
import plistlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build_private_preview import public_bundle_info
from scripts.distribution.sparkle_tools import tools, public_key, swift_annotation_flags


def configure(info_path, sdk, architecture):
    info = plistlib.loads(info_path.read_bytes())
    shared = public_bundle_info('1.0.0', '1', public_key(sdk), 'https://stella-admin.pages.dev/v1/events', architecture)
    for name in ('SUFeedURL', 'SUPublicEDKey', 'SUEnableAutomaticChecks',
                 'SUAutomaticallyUpdate', 'SUAllowsAutomaticUpdates', 'SUEnableSystemProfiling',
                 'SUVerifyUpdateBeforeExtraction', 'LSMinimumSystemVersion', 'StellaArchitecture'):
        info[name] = shared[name]
    # Preserve the source-connected identity, paths and version; never attach
    # telemetry or a bundled-backend runtime to the local developer's shell.
    info_path.write_bytes(plistlib.dumps(info))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('info', type=Path, nargs='?')
    parser.add_argument('--arch', default='arm64')
    parser.add_argument('--swift-flags', action='store_true')
    args = parser.parse_args()
    if args.swift_flags:
        print('\n'.join(swift_annotation_flags()))
        return
    if args.info is None:
        parser.error('a staged Info.plist is required')
    sdk = tools()
    configure(args.info, sdk, args.arch)
    print(sdk)


if __name__ == '__main__':
    main()
