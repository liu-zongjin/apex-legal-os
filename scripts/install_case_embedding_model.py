#!/usr/bin/env python3
"""Explicit, hash-checked public model installation; never runs during a query."""
import hashlib
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend.case_embeddings import model_directory,MODEL_SHA256,VOCAB_SHA256,MODEL_REPO,MODEL_REVISION
import httpx


def main():
    folder=model_directory(for_install=True);folder.mkdir(parents=True,exist_ok=True)
    for name in ['vocab.txt','onnx/model_quantized.onnx']:
        target=folder/Path(name).name
        expected=VOCAB_SHA256 if name=='vocab.txt' else MODEL_SHA256
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:continue
        last=None
        for host in ('https://huggingface.co','https://hf-mirror.com'):
            temp=target.with_suffix('.part')
            try:
                with httpx.Client(timeout=httpx.Timeout(25,connect=8),follow_redirects=True,trust_env=False) as client:
                    with client.stream('GET',f'{host}/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}') as response:
                        response.raise_for_status();size=0
                        with temp.open('wb') as output:
                            for chunk in response.iter_bytes():
                                size+=len(chunk)
                                if size>35_000_000:raise ValueError('模型文件超出大小限制')
                                output.write(chunk)
                if hashlib.sha256(temp.read_bytes()).hexdigest()!=expected:raise ValueError('模型或词表哈希不匹配')
                temp.replace(target);print('installed',target.name,flush=True);break
            except Exception as exc:
                last=exc;temp.unlink(missing_ok=True)
        else:raise RuntimeError('模型下载未完成：'+str(last))
    print('local model ready',folder)
if __name__=='__main__':main()
