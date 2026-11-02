"""Small local BGE encoder. No API keys, remote text upload or implicit download."""
from __future__ import annotations
import hashlib
import os
import sys
import threading
import unicodedata
from collections import OrderedDict
from pathlib import Path

MODEL_SHA256='15b717c382bcb518ba457b93ea6850ede7f4f1cd8937454aa06972366cd19bcc'
VOCAB_SHA256='45bbac6b341c319adc98a532532882e91a9cefc0329aa57bac9ae761c27b291c'
MODEL_REPO='Xenova/bge-small-zh-v1.5'
MODEL_REVISION='fcecc3c'
_LOCK=threading.RLock()
_ENCODER=None


def model_directory():
    if os.environ.get('STELLA_CASE_EMBEDDING_DIR'):
        return Path(os.environ['STELLA_CASE_EMBEDDING_DIR']).expanduser()
    cache=(Path.home()/'Library'/'Caches') if sys.platform=='darwin' else Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.cache')))
    return cache/'Stella'/'models'/'bge-small-zh-v1.5'


def basic_tokens(text):
    # Standard uncased BERT normalization and Chinese/punctuation isolation.
    words=[];word=''
    for ch in unicodedata.normalize('NFD',text.lower()):
        category=unicodedata.category(ch); code=ord(ch)
        if category=='Mn':continue
        if category.startswith('C') and ch not in '\t\n\r':continue
        chinese=0x3400<=code<=0x9fff or 0x20000<=code<=0x2fa1f
        punctuation=category.startswith('P') or 33<=code<=47 or 58<=code<=64 or 91<=code<=96 or 123<=code<=126
        if ch.isspace() or chinese or punctuation:
            if word:words.append(word);word=''
            if chinese or punctuation:words.append(ch)
        else:word+=ch
    if word:words.append(word)
    return words


class LocalEncoder:
    def __init__(self,directory):
        import onnxruntime as ort
        model=directory/'model_quantized.onnx'
        if hashlib.sha256(model.read_bytes()).hexdigest()!=MODEL_SHA256:
            raise ValueError('本地向量模型校验失败')
        vocab=(directory/'vocab.txt').read_bytes()
        if hashlib.sha256(vocab).hexdigest()!=VOCAB_SHA256:
            raise ValueError('本地向量词表校验失败')
        self.vocab={v:i for i,v in enumerate(vocab.decode('utf-8').splitlines())}
        for token,index in (('[PAD]',0),('[UNK]',100),('[CLS]',101),('[SEP]',102)):
            if self.vocab.get(token)!=index:raise ValueError('模型词表不匹配')
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider'])
        self.inputs={v.name for v in self.session.get_inputs()};self.cache=OrderedDict()
        self.path=str(directory)

    def tokenize(self,text):
        ids=[101]
        for word in basic_tokens(text):
            start=0;pieces=[]
            if len(word)>100:pieces=[100];start=len(word)
            while start<len(word):
                end=len(word);found=None
                while end>start:
                    piece=('##' if start else '')+word[start:end]
                    if piece in self.vocab:found=self.vocab[piece];break
                    end-=1
                if found is None:pieces=[100];break
                pieces.append(found);start=end
            ids.extend(pieces)
            if len(ids)>=255:break
        return ids[:255]+[102]

    def encode(self,texts):
        import numpy as np
        result=[None]*len(texts);missing=[]
        for i,text in enumerate(texts):
            key=hashlib.sha256(text.encode()).hexdigest()
            if key in self.cache:
                result[i]=self.cache[key];self.cache.move_to_end(key)
            else:missing.append((i,key,text))
        for offset in range(0,len(missing),8):
            batch=missing[offset:offset+8];rows=[self.tokenize(text) for _,_,text in batch]
            length=max(map(len,rows)); ids=np.zeros((len(rows),length),dtype=np.int64);mask=ids.copy()
            for i,row in enumerate(rows):ids[i,:len(row)]=row;mask[i,:len(row)]=1
            feed={'input_ids':ids,'attention_mask':mask,'token_type_ids':np.zeros_like(ids)}
            output=self.session.run(None,{k:v for k,v in feed.items() if k in self.inputs})[0]
            vectors=output[:,0,:] if output.ndim==3 else output
            vectors=vectors/np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)
            for (i,key,_),vector in zip(batch,vectors):
                result[i]=vector;self.cache[key]=vector
                while len(self.cache)>512:self.cache.popitem(last=False)
        return np.asarray(result)


def local_embeddings(texts):
    global _ENCODER
    with _LOCK:
        directory=model_directory()
        if not (directory/'model_quantized.onnx').is_file():raise FileNotFoundError('未安装本地向量模型')
        if _ENCODER is None or _ENCODER.path!=str(directory):_ENCODER=LocalEncoder(directory)
        return _ENCODER.encode(texts)
