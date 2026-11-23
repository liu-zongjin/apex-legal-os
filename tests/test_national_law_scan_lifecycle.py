import asyncio, sqlite3, tempfile, unittest
from unittest.mock import patch
from backend import main
class NationalLawScanLifecycleTests(unittest.IsolatedAsyncioTestCase):
 async def test_interrupted_stop_restart(self):
  with tempfile.TemporaryDirectory() as d:
   path=d+'/test.db'
   def db():
    c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
   with db() as c:
    c.executescript('''CREATE TABLE articles(id INTEGER PRIMARY KEY,title TEXT,source_filename TEXT,content TEXT); CREATE TABLE national_law_articles(article_id INTEGER,bbbs TEXT,official_title TEXT,status_code INTEGER,status_label TEXT,category TEXT,issuer TEXT,published_at TEXT,effective_at TEXT,official_content_hash TEXT,last_checked_at TEXT); CREATE TABLE national_law_update_scans(id INTEGER PRIMARY KEY,mode TEXT,status TEXT,total INTEGER DEFAULT 0,processed INTEGER DEFAULT 0,pending_matches INTEGER DEFAULT 0,updates_found INTEGER DEFAULT 0,current_count INTEGER DEFAULT 0,failed_count INTEGER DEFAULT 0,error TEXT,created_at TEXT,started_at TEXT,completed_at TEXT); CREATE TABLE national_law_update_items(id INTEGER PRIMARY KEY,scan_id INTEGER,article_id INTEGER,status TEXT,local_title TEXT,matched_bbbs TEXT,candidates_json TEXT,detail_json TEXT,error TEXT,confirmed INTEGER,action TEXT,created_at TEXT,updated_at TEXT); INSERT INTO articles VALUES(1,'示例条例','','示例'); INSERT INTO national_law_update_scans(id,mode,status) VALUES(1,'manual','running');''')
   entered=asyncio.Event()
   async def stalled(*args,**kwargs):
    entered.set();await asyncio.Event().wait()
   with patch.object(main,'get_db',db),patch.object(main,'search_national_laws',stalled):
    item=await main.create_national_law_update_scan({'article_ids':[1]})
    assert item['scan_id']==2
    await asyncio.wait_for(entered.wait(),5)
    assert (await main.stop_national_law_scan(2))['status']=='stopped'
    await asyncio.sleep(0)
    assert main.get_national_law_update_scan(2)['scan']['status']=='stopped'
    item=await main.create_national_law_update_scan({'article_ids':[1]})
    assert item['scan_id']==3
    await main.stop_national_law_scan(3)
    await asyncio.sleep(0)
    with db() as c: assert c.execute('select status from national_law_update_scans where id=1').fetchone()[0]=='interrupted'
 
