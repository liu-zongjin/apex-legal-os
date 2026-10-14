import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from backend.case_automation import ensure_case_automation_schema
from urllib.parse import parse_qs

import httpx

from backend.scanner_inbox import (
    CentreWareClient,
    ScanDocument,
    ScannerAuthenticationError,
    ScannerProtocolError,
    _merge_with_snapshot,
    register_scanner_inbox_routes,
)


LIST_HTML = """
<html><body><h1>信箱文件列表</h1><form action="PBDOCOUT.cmd">
  <input type="hidden" name="mailbox" value="001">
  <table><tr><th>文件号码</th></tr>
  <tr><td><input type="checkbox" name="doc" value="5590"></td><td>5590</td><td>20260824104351</td><td>2026/08/24 10:43</td><td>JPEG</td><td>4</td><td>扫描</td><td>有</td></tr>
  </table><select name="format"><option value="jpg">JPEG</option><option value="pdf">PDF</option></select>
  <input type="submit" name="extract" value="文件取出"></form></body></html>
"""

LIST_SCRIPT_HTML = """
<html><body><script>
var box=[1,'device-session-token','DD',1,'mailbox-user',0];
var lst=[[5590,'2026/08/24 10:43',5,4,2,'20260824104351',1,0,1]];
</script></body></html>
"""

RETRIEVE_RELAY_HTML = """
<html><body><script>
var info=[[1,5590,0,'20260824104351','/box/one-time-token/20260824104351.pdf']];
</script></body></html>
"""


class ScannerInboxParserTests(unittest.TestCase):
    def test_centreware_rows_keep_digit_only_filename_out_of_page_count(self):
        rows, _ = CentreWareClient._documents_from_html(LIST_HTML)
        self.assertEqual(len(rows), 1)
        item = rows[0]
        self.assertEqual(item.source_id, "5590")
        self.assertEqual(item.name, "20260824104351")
        self.assertEqual(item.pages, 4)
        self.assertEqual(item.compression, "JPEG")
        self.assertEqual(item.selection_name, "doc")
        self.assertEqual(item.selection_value, "5590")

    def test_unrecognised_page_is_rejected_instead_of_returning_guesswork(self):
        with self.assertRaises(ScannerProtocolError):
            CentreWareClient._documents_from_html("<html><body>unexpected appliance page</body></html>")

    def test_login_failure_is_not_misreported_as_empty_mailbox(self):
        with self.assertRaises(ScannerAuthenticationError):
            CentreWareClient._documents_from_html("<html><body>Login failed.</body></html>")

    def test_javascript_mailbox_list_is_parsed(self):
        rows, _ = CentreWareClient._documents_from_html(LIST_SCRIPT_HTML)
        self.assertEqual(len(rows), 1)
        item = rows[0]
        self.assertEqual(item.source_id, "5590")
        self.assertEqual(item.name, "20260824104351")
        self.assertEqual(item.scanned_at, "2026/08/24 10:43")
        self.assertEqual(item.pages, 4)
        self.assertEqual(item.compression, "JPEG")
        self.assertEqual(item.document_type, "扫描")


class ScanSnapshotMergeTests(unittest.TestCase):
    def _doc(self, source_id: str, name: str = "doc.pdf") -> ScanDocument:
        return ScanDocument(
            source_id=source_id,
            name=name,
            scanned_at="2026/08/24 10:43",
            compression="JPEG",
            pages=1,
            document_type="扫描",
            selection_name="DOC",
            selection_value=source_id,
        )

    def test_merge_flags_new_and_deleted_files(self):
        snapshot = [self._doc("1"), self._doc("2")]
        latest = [self._doc("2"), self._doc("3")]
        items, new_count, deleted_count = _merge_with_snapshot(latest, snapshot, {}, {})

        self.assertEqual(new_count, 1)
        self.assertEqual(deleted_count, 1)
        self.assertEqual([item.get("status") for item in items], [None, "new", "deleted"])
        self.assertEqual([item["source_id"] for item in items], ["2", "3", "1"])
        self.assertNotIn("status", items[0])

    def test_merge_with_empty_snapshot_marks_everything_new(self):
        latest = [self._doc("1"), self._doc("2")]
        items, new_count, deleted_count = _merge_with_snapshot(latest, [], {}, {})
        self.assertEqual(new_count, 2)
        self.assertEqual(deleted_count, 0)
        self.assertTrue(all(item["status"] == "new" for item in items))

    def test_merge_unchanged_lists_have_no_status(self):
        snapshot = [self._doc("1"), self._doc("2")]
        latest = [self._doc("1"), self._doc("2")]
        items, new_count, deleted_count = _merge_with_snapshot(latest, snapshot, {}, {})
        self.assertEqual(new_count, 0)
        self.assertEqual(deleted_count, 0)
        self.assertTrue(all("status" not in item for item in items))

    def test_merge_keeps_notes_and_import_labels(self):
        snapshot = [self._doc("1")]
        latest = [self._doc("1")]
        items, _, _ = _merge_with_snapshot(latest, snapshot, {"1": ["已归入案件 7"]}, {"1": "卷宗备份"})
        self.assertEqual(items[0]["imported_to"], ["已归入案件 7"])
        self.assertEqual(items[0]["note"], "卷宗备份")


class FreshApexSessionTransport(httpx.AsyncBaseTransport):
    """A printer fixture: no browser cookie or existing session is accepted."""

    def __init__(self):
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        if request.url.path == "/scan.htm":
            return httpx.Response(200, text="<html>scan home</html>", request=request)
        if request.url.path == "/scpblst.htm":
            return httpx.Response(200, text="<html>mailboxes</html>", request=request)
        if request.url.path == "/PBDOCLST.cmd":
            return httpx.Response(200, text=LIST_HTML, request=request)
        return httpx.Response(404, request=request)


class ScannerInboxFreshSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_apex_reads_mailbox_from_a_fresh_http_session(self):
        transport = FreshApexSessionTransport()
        client = CentreWareClient({"username": "scanner-user", "password": "secret"}, transport=transport)

        rows = await client.list_documents()

        self.assertEqual([item.source_id for item in rows], ["5590"])
        self.assertEqual([item.url.path for item in transport.requests], ["/scan.htm", "/scpblst.htm", "/PBDOCLST.cmd"])
        self.assertEqual(transport.requests[2].method, "POST")
        self.assertEqual(parse_qs(transport.requests[2].content.decode())["BOX"], ["1"])
        self.assertTrue(all("cookie" not in request.headers for request in transport.requests))
        self.assertTrue(all(request.headers.get("authorization", "").startswith("Basic ") for request in transport.requests))


class DownloadRelayTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        if request.url.path == "/scan.htm":
            return httpx.Response(200, text="<html>scan home</html>", request=request)
        if request.url.path == "/scpblst.htm":
            return httpx.Response(200, text="<html>mailboxes</html>", request=request)
        if request.url.path == "/PBDOCLST.cmd":
            return httpx.Response(200, text=LIST_SCRIPT_HTML, request=request)
        if request.url.path == "/PBDOCLNK.cmd":
            return httpx.Response(200, text=RETRIEVE_RELAY_HTML, request=request)
        if request.url.path == "/box/one-time-token/20260824104351.pdf":
            return httpx.Response(200, content=b"%PDF-1.4\nmock pdf", request=request)
        return httpx.Response(404, request=request)


class ScannerInboxDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_download_follows_centreware_relay_link(self):
        client = CentreWareClient(
            {"username": "scanner-user", "password": "secret"}, transport=DownloadRelayTransport()
        )
        filename, content = await client.download_pdf("5590")

        self.assertEqual(filename, "扫描_5590_20260824104351.pdf")
        self.assertTrue(content.startswith(b"%PDF-"))


class ScannerCaseImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.folder = self.root / "case"
        self.folder.mkdir()
        self.calls = []

        def get_db():
            conn = sqlite3.connect(self.root / "test.db")
            conn.row_factory = sqlite3.Row
            return conn

        self.get_db = get_db
        with get_db() as conn:
            conn.execute("CREATE TABLE case_manager_cases(id INTEGER PRIMARY KEY,title TEXT)")
            conn.execute("INSERT INTO case_manager_cases VALUES(1,'匿名案件')")
        ensure_case_automation_schema(get_db)
        stat = self.folder.stat()
        with get_db() as conn:
            conn.execute("""INSERT INTO case_manager_folder_bindings
                (case_id,folder_path,real_path,device_id,inode,status,subdirs_json,created_at,updated_at)
                VALUES(1,?,?,?,?, 'active','{}','2026-10-14','2026-10-14')""",
                (str(self.folder), str(self.folder), stat.st_dev, stat.st_ino))
        calls = self.calls

        class Printer:
            async def download_pdf(self, source_id):
                calls.append(source_id)
                return "扫描.pdf", b"%PDF-fixture"

        self.printer_type = Printer
        app = FastAPI()
        register_scanner_inbox_routes(app, get_db, self.root, parse_file=lambda *args: None,
                                     client_factory=lambda _: Printer())
        self.keychain = patch("backend.scanner_inbox._keychain_read", return_value={"username": "fixture", "password": "fixture"})
        self.keychain.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.keychain.stop()
        self.temporary.cleanup()

    async def import_scans(self, ids=None):
        return await self.client.post("/api/scanner-inbox/import", json={
            "source_ids": ids or ["9554"], "destination": "case", "case_id": 1})

    async def test_case_import_saves_pdf_and_indexes_source_without_overwriting(self):
        directory = self.folder / "#下载材料"
        directory.mkdir()
        (directory / "扫描.pdf").write_bytes(b"existing")
        response = await self.import_scans(["9554", "9553"])
        self.assertEqual(response.status_code, 200, response.text)
        paths = [Path(item["path"]) for item in response.json()["items"]]
        self.assertEqual([p.name for p in paths], ["扫描_2.pdf", "扫描_3.pdf"])
        self.assertTrue(all(p.parent == directory and p.read_bytes() == b"%PDF-fixture" for p in paths))
        self.assertEqual((directory / "扫描.pdf").read_bytes(), b"existing")
        with self.get_db() as conn:
            rows = conn.execute("SELECT * FROM case_manager_files ORDER BY id").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["source_type"], "scanner_inbox")
            self.assertIn('9554', rows[0]["metadata_json"])
            self.assertEqual(rows[0]["relative_path"], "#下载材料/扫描_2.pdf")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scanner_inbox_imports").fetchone()[0], 2)

    async def test_duplicate_is_rejected_before_printer_download(self):
        self.assertEqual((await self.import_scans()).status_code, 200)
        self.calls.clear()
        response = await self.import_scans()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.calls, [])

    async def test_unbound_or_unavailable_folder_is_rejected_before_download(self):
        self.folder.rmdir()
        self.assertEqual((await self.import_scans()).status_code, 409)
        with self.get_db() as conn:
            conn.execute("DELETE FROM case_manager_folder_bindings")
        self.assertEqual((await self.import_scans()).status_code, 409)
        self.assertEqual(self.calls, [])

    async def test_binding_is_revalidated_after_printer_download(self):
        async def changed_download(source_id):
            self.folder.rmdir()
            return "扫描.pdf", b"%PDF-fixture"

        with patch.object(self.printer_type, "download_pdf", lambda _self, source_id: changed_download(source_id)):
            self.assertEqual((await self.import_scans()).status_code, 409)
        with self.get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scanner_inbox_imports").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
