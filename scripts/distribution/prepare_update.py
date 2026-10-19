#!/usr/bin/env python3
"""Generate signed Sparkle feed/deltas and an explicit publication plan; never upload."""
import argparse
import hashlib
import json
import plistlib
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparkle_tools import tools, public_key

SPARKLE = '{http://www.andymatuschak.org/xml-namespaces/sparkle}'
DOWNLOAD_ROOT = 'https://github.com/liu-zongjin/stella-downloads/releases/download/'


def archive_info(path):
    with zipfile.ZipFile(path) as archive:
        if any(not name.startswith('Stella.app/') for name in archive.namelist()):
            raise ValueError('Update ZIP must contain only Stella.app')
        info = plistlib.loads(archive.read('Stella.app/Contents/Info.plist'))
    if info.get('CFBundleIdentifier') != 'com.stella.public.native':
        raise ValueError('Wrong application identity')
    if info.get('LSMinimumSystemVersion') != '12.0':
        raise ValueError('Public release must require macOS 12')
    if not str(info.get('CFBundleVersion', '')).isdigit():
        raise ValueError('Invalid build number')
    return info


def validate_feed(path, archives, sdk, tag):
    root = ET.parse(path).getroot()
    uploads = {}
    items = root.findall('./channel/item')
    if not items:
        raise ValueError('Appcast has no updates')
    for item in items:
        full = item.find('enclosure')
        if full is None or not full.get(SPARKLE+'edSignature'):
            raise ValueError('Missing signed full update fallback')
        for enclosure in item.findall('.//enclosure'):
            url = enclosure.get('url', '')
            parsed = urlparse(url)
            if not url.startswith(DOWNLOAD_ROOT) or parsed.query or parsed.fragment:
                raise ValueError('Unexpected update URL')
            name = unquote(parsed.path.rsplit('/', 1)[-1])
            if Path(name).name != name or not name:
                raise ValueError('Invalid asset filename')
            if not url.startswith(DOWNLOAD_ROOT + tag + '/'):
                continue  # Existing immutable release asset; preserve its original URL.
            local = archives / name
            if not local.is_file() or int(enclosure.get('length', '-1')) != local.stat().st_size:
                raise ValueError('Missing asset or length mismatch: ' + name)
            signature = enclosure.get(SPARKLE+'edSignature')
            if not signature:
                raise ValueError('Unsigned update: ' + name)
            subprocess.run([str(sdk/'bin/sign_update'), '--account', 'stella-public', '--verify',
                            str(local), signature], check=True, capture_output=True)
            uploads[name] = {'sha256': hashlib.sha256(local.read_bytes()).hexdigest(), 'bytes': local.stat().st_size}
    return uploads


def prepare(archives, newest, notes):
    archives, newest = archives.resolve(), newest.resolve()
    if newest.parent != archives or newest.suffix != '.zip':
        raise ValueError('Newest ZIP must be directly inside archives directory')
    sdk = tools()
    expected_key = public_key(sdk)
    info = archive_info(newest)
    build = int(info['CFBundleVersion'])
    versions = set()
    for archive in archives.glob('*.zip'):
        old = archive_info(archive)
        old_build = int(old['CFBundleVersion'])
        if old_build in versions or old_build > build:
            raise ValueError('Duplicate build or attempted release downgrade')
        versions.add(old_build)
        if old.get('SUPublicEDKey') != expected_key:
            raise ValueError('Update signing key does not match application')
    feed = archives/'appcast.xml'
    previous_items = {}
    if feed.exists():
        for item in ET.parse(feed).getroot().findall('./channel/item'):
            previous_items[item.findtext(SPARKLE+'version')] = item
    tag = 'v' + info['CFBundleShortVersionString'] + '-' + str(build)
    (archives/(newest.stem+'.md')).write_text(notes.read_text(), encoding='utf-8')
    subprocess.run([str(sdk/'bin/generate_appcast'), '--account', 'stella-public',
        '--download-url-prefix', DOWNLOAD_ROOT+tag+'/', '--embed-release-notes',
        '--maximum-deltas', '5', '--versions', str(build), str(archives)], check=True)
    if previous_items:
        tree = ET.parse(feed)
        channel = tree.getroot().find('channel')
        for index, item in enumerate(list(channel)):
            if item.tag != 'item':
                continue
            item_build = item.findtext(SPARKLE+'version')
            if item_build != str(build) and item_build in previous_items:
                channel.remove(item)
                channel.insert(index, previous_items[item_build])
        ET.register_namespace('sparkle', SPARKLE[1:-1])
        tree.write(feed, encoding='utf-8', xml_declaration=True)
    # Signing after preserving older entries also covers release notes and URLs.
    subprocess.run([str(sdk/'bin/sign_update'), '--account', 'stella-public', str(feed)], check=True)
    subprocess.run([str(sdk/'bin/sign_update'), '--account', 'stella-public', '--verify', str(feed)], check=True)
    uploads = validate_feed(feed, archives, sdk, tag)
    if newest.name not in uploads:
        raise ValueError('New archive missing from feed; a release build may not be reused')
    plan = {'release_tag':tag, 'build':str(build), 'upload_to_release':uploads,
        'feed_sha256':hashlib.sha256(feed.read_bytes()).hexdigest(),
        'publish_order':['Upload immutable ZIP/delta assets to this GitHub Release',
                         'Verify every asset URL and checksum',
                         'Publish appcast.xml to website docs/ only after all assets exist',
                         'Update website download link, macOS requirement and feature notes'],
        'feed_destination':'stella-downloads/docs/appcast.xml'}
    (archives/'release-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--newest', type=Path, required=True)
    parser.add_argument('--notes', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archives, args.newest, args.notes), ensure_ascii=False, indent=2))
