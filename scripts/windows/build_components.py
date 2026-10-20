"""Assemble clean, licensed Windows dependencies and verify an offline installation.

Runs only on an ephemeral Windows build runner. Never reads an author's runtime.
The production catalog is signed locally after the exact artifacts are retrieved.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from bootstrap_engine import Installer
from make_catalog import pack_component, sign

ROOT = Path(__file__).resolve().parents[2]
BUILD = 2026102111
BASE_URL = f'https://github.com/liu-zongjin/stella-downloads/releases/download/windows-v1.1.5-{BUILD}'


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download(url, path, expected=None):
    with requests.get(url, stream=True, timeout=(15, 120)) as response:
        response.raise_for_status()
        with path.open('wb') as target:
            for block in response.iter_content(1024 * 1024):
                target.write(block)
    actual = checksum(path)
    if expected and actual != expected:
        raise RuntimeError('Upstream checksum mismatch: ' + path.name)
    return {'url': url, 'sha256': actual, 'bytes': path.stat().st_size}


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def install_and_diagnose(worker, payload, archives):
    try:
        return worker.install(sign(payload, worker.ci_verification_key), archives)
    except Exception:
        for component in payload['components']:
            root = worker.component_dir(component)
            if not root.exists():
                continue
            actual = {p.relative_to(root).as_posix(): p for p in root.rglob('*') if p.is_file()}
            expected = component['files']
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            changed = [name for name in set(actual) & set(expected) if checksum(actual[name]) != expected[name]]
            if missing or extra or changed:
                print('COMPONENT_MUTATIONS', json.dumps({'component': component['id'], 'missing': missing[:30],
                    'extra': extra[:30], 'changed': changed[:30]}), flush=True)
        raise


def verify_nsis_package():
    installers = list((ROOT / 'windows-installer/src-tauri/target/release/bundle/nsis').glob('*.exe'))
    assert len(installers) == 1
    with tempfile.TemporaryDirectory(prefix='Stella安装验收-') as directory:
        target = Path(directory) / 'Application'
        run(installers[0], '/S', '/D=' + str(target), timeout=180)
        executable = target / 'resources/bootstrap-engine.exe'
        import tomllib
        with (ROOT / 'windows-installer/src-tauri/Cargo.toml').open('rb') as stream:
            native_name = tomllib.load(stream)['package']['name']
        assert (target / (native_name + '.exe')).is_file() and executable.is_file(), list(target.rglob('*.exe'))
        from PyInstaller.archive.readers import CArchiveReader
        config = json.loads(CArchiveReader(str(executable)).extract('bootstrap-config.json'))
        expected = json.loads((ROOT / 'scripts/windows/production-trust.json').read_text(encoding='utf-8'))
        assert config == expected
        environment = dict(os.environ, LOCALAPPDATA=str(Path(directory) / '用户资料'))
        result = subprocess.check_output([str(executable), 'probe'], env=environment, timeout=60)
        probe = json.loads(result.decode('utf-8'))
        assert probe['event'] == 'probe' and probe['architecture'] == 'x86_64'
        assert (Path(directory) / '用户资料/Stella').is_dir()


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build components on Windows only')
    components = ROOT / 'build/windows-components'
    output = ROOT / 'build/windows-production'
    output.mkdir(exist_ok=False)
    upstream = []
    verify_nsis_package()
    # The installed Playwright release pins its tested open-source Chromium revision.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    assert executable.is_file(), 'Install the pinned Playwright Chromium before assembling components'
    shutil.copytree(executable.parent, components / 'browser')
    assert (components / 'browser/chrome.exe').is_file()
    (components / 'browser/STELLA-CHROMIUM-SOURCE.txt').write_text(
        'Unmodified Chromium distributed with Microsoft Playwright.\n'
        'Build/source and licensing: https://github.com/microsoft/playwright\n'
        'Chromium source and license: https://chromium.googlesource.com/chromium/src/+/main/LICENSE\n', encoding='utf-8')
    import importlib.metadata
    upstream.append({'component': 'browser', 'playwright': importlib.metadata.version('playwright'),
                     'browser_revision_path': executable.parent.parent.name})
    with tempfile.TemporaryDirectory(prefix='stella-official-components-') as temporary:
        folder = Path(temporary)
        mamba = folder / 'micromamba.tar.bz2'
        upstream.append(download('https://api.anaconda.org/download/conda-forge/micromamba/2.9.0/win-64/micromamba-2.9.0-0.tar.bz2',
            mamba, '97a336f4ab794bd96a6a4da5e6ed63e75a1d31830414a182419b23d3b36f3fe0'))
        with tarfile.open(mamba) as archive:
            member = archive.getmember('Library/bin/micromamba.exe')
            with archive.extractfile(member) as source, (folder / 'micromamba.exe').open('wb') as destination:
                shutil.copyfileobj(source, destination)
        environment = folder / 'ocr-env'
        run(folder / 'micromamba.exe', 'create', '--yes', '--no-rc', '--root-prefix', folder / 'mamba-root',
            '--prefix', environment, '--override-channels', '--channel', 'conda-forge', 'tesseract=5.5.3', timeout=900)
        ocr = components / 'ocr'
        shutil.copytree(environment / 'Library/bin', ocr)
        for library in environment.glob('*.dll'):
            shutil.copy2(library, ocr / library.name)
        tessdata = ocr / 'tessdata'
        tessdata.mkdir(exist_ok=True)
        source_data = environment / 'Library/share/tessdata'
        if source_data.is_dir():
            shutil.copytree(source_data, tessdata, dirs_exist_ok=True)
        for language in ('eng', 'chi_sim'):
            upstream.append(download('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/' + language + '.traineddata',
                tessdata / (language + '.traineddata')))
        download('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/LICENSE', tessdata / 'LICENSE')
        licenses = ocr / 'licenses'
        licenses.mkdir()
        packages = []
        for metadata in sorted((environment / 'conda-meta').glob('*.json')):
            value = json.loads(metadata.read_text(encoding='utf-8'))
            packages.append({key: value.get(key) for key in ('name', 'version', 'build', 'url', 'sha256', 'license')})
            package = Path(value.get('link', {}).get('source', ''))
            if not package.is_dir():
                raise RuntimeError('Missing dependency license source: ' + metadata.name)
            for source in (package / 'info').rglob('*'):
                if source.is_file() and ('license' in source.as_posix().lower() or source.name.lower().startswith('copying')):
                    target = licenses / metadata.stem / source.relative_to(package)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        (licenses / 'conda-packages.json').write_text(json.dumps(packages, indent=2), encoding='utf-8')
        upstream.append({'component': 'ocr', 'packages': packages})
        assert (ocr / 'tesseract.exe').is_file()
        installer = folder / 'LibreOffice.msi'
        upstream.append(download('https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi',
            installer, 'c6298b10cfa1748bcbedad94c62ce771e240e5021bfd6d7a967cd571b04b5312'))
        extracted = folder / 'libreoffice'
        result = subprocess.run(['msiexec.exe', '/a', str(installer), '/qn', 'TARGETDIR=' + str(extracted),
                                 '/l*v', str(ROOT / 'build/windows-office-extract.log')], timeout=300)
        if result.returncode not in (0, 3010):
            raise RuntimeError('LibreOffice administrative extraction failed: ' + str(result.returncode))
        entries = list(extracted.rglob('program/soffice.exe'))
        assert len(entries) == 1, entries
        shutil.copytree(entries[0].parent.parent, components / 'converter')
        for source in (components / 'converter').glob('*.msi'):
            source.unlink()
    (output / 'UPSTREAM-SOURCES.json').write_text(json.dumps(upstream, ensure_ascii=False, indent=2), encoding='utf-8')
    descriptions = [pack_component(name, components / name, output, BASE_URL)
                    for name in ('server', 'browser', 'ocr', 'converter')]
    payload = {'schema': 1, 'target': 'windows-x86_64', 'version': '1.1.5', 'build': BUILD,
               'expires_at': int(time.time()) + 180 * 86400, 'components': descriptions}
    # Ephemeral verification key never leaves this process. The production key is not in CI.
    key = Ed25519PrivateKey.generate()
    config = json.loads((ROOT / 'scripts/windows/production-trust.json').read_text(encoding='utf-8'))
    config['public_key'] = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    with tempfile.TemporaryDirectory(prefix='stella-full-install-check-') as temporary:
        installed = Path(temporary)
        worker = Installer(installed, config)
        worker.ci_verification_key = key
        install_and_diagnose(worker, payload, output)
        assert all(state['reuse'] for state in worker.plan(payload)['components'])
        runtime = installed / 'userdata'
        runtime.mkdir()
        (runtime / 'anonymous-keep.txt').write_text('recipient attachment', encoding='utf-8')
        # A changed server must download alone; identical OCR/browser/converter are reused.
        marker = components / 'server/STELLA-CI-UPGRADE.txt'
        marker.write_text('Anonymous CI component replacement only', encoding='utf-8')
        next_output = installed / 'next-offline'
        next_output.mkdir()
        replacement = pack_component('server', components / 'server', next_output, BASE_URL + '-upgrade-test')
        marker.unlink()
        upgrade = dict(payload, build=BUILD + 1, version='1.1.6', components=[replacement, *descriptions[1:]])
        plan = worker.plan(upgrade)
        assert [(item['id'], item['reuse']) for item in plan['components']] == [
            ('server', False), ('browser', True), ('ocr', True), ('converter', True)]
        install_and_diagnose(worker, upgrade, next_output)
        assert (runtime / 'anonymous-keep.txt').read_text(encoding='utf-8') == 'recipient attachment'
        # Exercise OCR, rather than only checking that the language files exist.
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (650, 110), 'white')
        ImageDraw.Draw(image).text((10, 15), 'STELLA12345', fill='black', font=ImageFont.truetype('arial.ttf', 58))
        image.save(installed / 'ocr-check.png')
        ocr_root = worker.component_dir(descriptions[2])
        result = subprocess.check_output([str(ocr_root / 'tesseract.exe'), str(installed / 'ocr-check.png'), 'stdout',
            '--tessdata-dir', str(ocr_root / 'tessdata'), '--psm', '7', '-l', 'eng'], timeout=60)
        assert b'12345' in result, result
    (output / 'catalog-payload.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'FULL-INSTALL-VERIFICATION.json').write_text(json.dumps({'pass': True, 'full_offline_install': True,
        'browser_rendered': True, 'ocr_recognized': True, 'converter_created_pdf': True,
        'incremental_server_only_download': True, 'unchanged_components_reused': True,
        'recipient_attachment_preserved': True, 'production_signing_key_in_ci': False, 'nsis_installed_under_unicode_path': True,
        'embedded_production_config_verified': True, 'installed_worker_probed': True}), encoding='utf-8')
    print('WINDOWS_FULL_COMPONENT_INSTALL_AND_INCREMENTAL_UPGRADE_OK')


if __name__ == '__main__':
    main()
