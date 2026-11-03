#!/usr/bin/env python3
"""Anonymous cross-domain retrieval experiment; never opens the live database.

These are synthetic retrieval labels, not verified statements of law. Reports
lexical-only and hybrid ranks honestly; no production query rules are installed.
"""
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.knowledge_search import CorpusIndex

SAMPLES = [
    ('劳动', '没签书面合同，单位每天管我上下班，能算员工吗', '确认劳动关系', '劳动关系的认定需要结合实际用工管理、劳动报酬支付等事实。'),
    ('公司', '公司还不起债，股东说出资日期还没到怎么办', '未届期出资', '债权人要求未届出资期限的股东提前缴纳出资，需要核对公司不能清偿债务等适用条件。'),
    ('知识产权', '把别人的照片拿来做商业宣传，要赔钱吗', '图片著作权', '商业广告使用他人摄影作品涉及著作权许可及侵权责任。'),
    ('婚姻家事', '离婚后对方一直不让我见孩子', '探望权', '离婚后不直接抚养子女的一方行使探望权，另一方应当协助；限制或中止需核对法定条件。'),
    ('行政', '行政机关拖着不答复我的申请能起诉吗', '行政不作为', '当事人认为行政机关不履行法定职责，可以依法寻求救济，但须核对申请事项和起诉期限。'),
    ('刑事', '涉嫌犯罪的人主动去派出所交代经过会少判吗', '自首认定', '犯罪嫌疑人自动投案并如实供述的自首认定，以及相应量刑情节，需要核对投案和供述事实。'),
    ('程序', '同一个官司已经判完，对方又告一遍', '重复起诉', '认定重复起诉需比较当事人、诉讼标的与诉讼请求，并核对前诉程序状态。'),
    ('合同', '合同签完突然涨价，卖家不愿交货了', '拒绝履行', '出卖人拒绝交付合同标的物时，买受人可以结合履行可能性请求继续履行或其他违约救济。'),
]


def run():
    with tempfile.TemporaryDirectory(prefix='stella-search-eval-') as folder:
        db = Path(folder) / 'anonymous.db'
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE articles(id INTEGER PRIMARY KEY,title,summary,content)')
        for i, (_, _, title, text) in enumerate(SAMPLES, 1):
            conn.execute('INSERT INTO articles VALUES (?,?,?,?)', (i, title, '', text))
        conn.commit(); conn.close()
        index = CorpusIndex(db, Path(folder) / 'cache')
        start = time.monotonic(); index.refresh(); build = time.monotonic() - start
        measurements = []
        with patch.object(index, 'schedule'):
            for expected, (domain, query, _, _) in enumerate(SAMPLES, 1):
                start = time.monotonic()
                hybrid, info = index.search(query, 'article', range(1, len(SAMPLES) + 1))
                latency = time.monotonic() - start
                def unavailable(_): raise RuntimeError('sparse comparison')
                original = index.encoder; index.encoder = unavailable
                lexical, _ = index.search(query, 'article', range(1, len(SAMPLES) + 1))
                index.encoder = original
                def rank(hits):
                    return next((i for i, h in enumerate(hits, 1) if h['id'] == expected), None)
                measurements.append({'domain': domain, 'query': query, 'keyword_rank': rank(lexical),
                    'hybrid_rank': rank(hybrid), 'hybrid_top3': [h['id'] for h in hybrid[:3]],
                    'latency_ms': round(latency * 1000, 1), 'actual_method': info['method']})
                measurements[-1]['relevance_review'] = info.get('relevance_review')
        negatives = []
        with patch.object(index, 'schedule'):
            for query in ('太空中的黑洞如何形成', '怎样烤出蓬松的面包', '如何给盆栽浇水', '手机充电线坏了怎么修'):
                hits, _ = index.search(query, 'article', range(1, len(SAMPLES) + 1))
                negatives.append({'query': query, 'returned_ids': [h['id'] for h in hits]})
        index.close()
        return {'synthetic_only': True, 'sample_count': len(SAMPLES), 'build_seconds': round(build, 3),
            'keyword_top1': sum(r['keyword_rank'] == 1 for r in measurements),
            'hybrid_top1': sum(r['hybrid_rank'] == 1 for r in measurements),
            'keyword_top3': sum(r['keyword_rank'] is not None and r['keyword_rank'] <= 3 for r in measurements),
            'hybrid_top3': sum(r['hybrid_rank'] is not None and r['hybrid_rank'] <= 3 for r in measurements),
            'measurements': measurements, 'unrelated_queries': negatives}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
