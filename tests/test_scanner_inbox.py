import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI

from backend import scanner_inbox
from backend.scanner_inbox import (
    CentreWareClient,
    ScanDocument,
    ScannerAuthenticationError,
    ScannerProtocolError,
    _merge_with_snapshot,
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


class FakeDownloadClient:
    def __init__(self, _credentials):
        pass

    async def download_pdf(self, source_id):
        return f"扫描_{source_id}.pdf", b"%PDF-1.4\n" + source_id.encode() * 128


class ScannerInboxDownloadProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"

        def get_db():
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            return connection

        self.app = FastAPI()
        self.keychain_patch = patch.object(
            scanner_inbox, "_keychain_read", return_value={"username": "test", "password": ""}
        )
        self.keychain_patch.start()
        scanner_inbox.register_scanner_inbox_routes(
            self.app,
            get_db,
            Path(self.temp_dir.name),
            parse_file=lambda *_args: None,
            client_factory=FakeDownloadClient,
        )

    async def asyncTearDown(self):
        self.keychain_patch.stop()
        self.temp_dir.cleanup()

    async def test_zip_download_exposes_exact_content_length_for_progress(self):
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/scanner-inbox/download",
                json={"source_ids": ["101", "102"], "mode": "zip"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(int(response.headers["content-length"]), len(response.content))

    def test_scanner_page_contains_persistent_progress_feedback(self):
        page = (Path(__file__).parents[1] / "frontend" / "scanner-inbox.html").read_text()
        self.assertIn('id="operation-overlay"', page)
        self.assertIn('id="operation-speed"', page)
        self.assertIn("response.body.getReader()", page)
        self.assertIn("预计剩余", page)


if __name__ == "__main__":
    unittest.main()
