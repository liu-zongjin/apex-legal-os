"""Local cross-encoder relevance checks. No downloads or external inference."""
import hashlib
import os
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

REPO = 'Xenova/bge-reranker-base'
REVISION = '280bcc27a84e0b898c251e06fddb25171bd9b101'
FILES = {
    'onnx/model_quantized.onnx': 'dd98f3e67837d23210a6b7550c08cced4f61845b940ac45be3565840a10f3244',
    'tokenizer.json': '48564c5c7d3fa64d85d95e65414a542385f88b0f128fd8d4163fd7a57f2be05c',
}
_LOCK = threading.Lock()
_MODEL = None
_IDLE_TIMER = None
_LAST_USED = 0.0


def _unload_idle():
    global _MODEL, _IDLE_TIMER
    if _LOCK.acquire(blocking=False):
        try:
            if time.monotonic() - _LAST_USED >= 295:
                _MODEL = None
                _IDLE_TIMER = None
        finally:
            _LOCK.release()


def directory():
    if os.environ.get('STELLA_KNOWLEDGE_RERANKER_DIR'):
        return Path(os.environ['STELLA_KNOWLEDGE_RERANKER_DIR']).expanduser()
    from .knowledge_search import cache_directory
    return cache_directory().parent / 'models' / 'bge-reranker-base'


class Reranker:
    def __init__(self):
        import onnxruntime as ort
        folder = directory()
        for name, expected in FILES.items():
            if hashlib.sha256((folder / Path(name).name).read_bytes()).hexdigest() != expected:
                raise ValueError('本地相关性模型校验失败')
        try:
            from tokenizers import Tokenizer
        except ImportError:
            # Explicit local installer can isolate this small native dependency.
            local = folder / 'python'
            if not local.is_dir():
                raise
            sys.path.insert(0, str(local))
            from tokenizers import Tokenizer
        self.tokenizer = Tokenizer.from_file(str(folder / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=384)
        self.tokenizer.enable_padding(pad_id=1, pad_token='<pad>')
        options = ort.SessionOptions(); options.intra_op_num_threads = 2; options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(folder / 'model_quantized.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.cache = OrderedDict()

    def score(self, query, texts):
        import numpy as np
        scores = [None] * len(texts); missing = []
        for i, text in enumerate(texts):
            key = hashlib.sha256((query + '\0' + text).encode()).hexdigest()
            if key in self.cache:
                scores[i] = self.cache[key]; self.cache.move_to_end(key)
            else:
                missing.append((i, key, text))
        for start in range(0, len(missing), 4):
            batch = missing[start:start + 4]
            tokens = self.tokenizer.encode_batch([(query[:240], text[:1800]) for _, _, text in batch])
            feed = {'input_ids': np.array([t.ids for t in tokens], dtype=np.int64),
                    'attention_mask': np.array([t.attention_mask for t in tokens], dtype=np.int64),
                    'token_type_ids': np.array([t.type_ids for t in tokens], dtype=np.int64)}
            output = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0].reshape(-1)
            if len(output) != len(batch) or not np.isfinite(output).all():
                raise ValueError('相关性模型输出无效')
            for (i, key, _), value in zip(batch, output):
                scores[i] = float(value); self.cache[key] = float(value)
                while len(self.cache) > 256:
                    self.cache.popitem(last=False)
        return scores


def relevance_scores(query, texts):
    global _MODEL, _IDLE_TIMER, _LAST_USED
    if not _LOCK.acquire(timeout=.5):
        raise RuntimeError('local relevance model busy')
    try:
        if _MODEL is None:
            _MODEL = Reranker()
        result = _MODEL.score(query, texts)
        _LAST_USED = time.monotonic()
        if _IDLE_TIMER:
            _IDLE_TIMER.cancel()
        _IDLE_TIMER = threading.Timer(300, _unload_idle)
        _IDLE_TIMER.daemon = True
        _IDLE_TIMER.start()
        return result
    finally:
        _LOCK.release()


def shutdown():
    global _MODEL, _IDLE_TIMER
    if _IDLE_TIMER:
        _IDLE_TIMER.cancel()
    if _LOCK.acquire(timeout=.5):
        try:
            _MODEL = None; _IDLE_TIMER = None
        finally:
            _LOCK.release()
