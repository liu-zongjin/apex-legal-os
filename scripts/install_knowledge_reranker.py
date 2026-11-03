#!/usr/bin/env python3
"""Explicit pinned local model/dependency install, outside source and business DB."""
import hashlib
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from backend.knowledge_reranker import directory, FILES, REPO, REVISION
from backend.public_case_transport import case_proxy


def main():
    folder = directory(); folder.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        target = folder / Path(name).name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            continue
        failure = None
        for host in ('https://hf-mirror.com', 'https://huggingface.co'):
            part = target.with_suffix('.part')
            try:
                with httpx.Client(proxy=case_proxy(), trust_env=False, timeout=httpx.Timeout(40, connect=12), follow_redirects=True) as client:
                    with client.stream('GET', f'{host}/{REPO}/resolve/{REVISION}/{name}') as response:
                        response.raise_for_status(); size = 0; digest = hashlib.sha256()
                        with part.open('wb') as stream:
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > 300_000_000:
                                    raise ValueError('模型文件超出大小上限')
                                digest.update(chunk); stream.write(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError('下载模型哈希不匹配')
                part.replace(target); print('installed', target.name, flush=True); break
            except Exception as exc:
                failure = type(exc).__name__; part.unlink(missing_ok=True)
        else:
            raise RuntimeError('相关性模型下载失败：' + str(failure))
    try:
        import tokenizers
    except ImportError:
        if not (folder / 'python' / 'tokenizers').is_dir():
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--target', str(folder / 'python'), 'tokenizers==0.20.3'], check=True)
    print('local relevance model ready', flush=True)


if __name__ == '__main__':
    main()
