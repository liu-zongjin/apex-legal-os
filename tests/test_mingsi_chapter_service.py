import asyncio
import datetime as dt
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException, UploadFile

from backend.document_bundle_artifacts import get_document_bundle_artifact, store_document_bundle_artifact
from backend.migrations import migrate_database
from backend.mingsi_chapter_service import _quick_selected_type, _quick_type_options, register_mingsi_chapter_routes


class FakeApp:
    def __init__(self):
        self.routes = {}

    def _register(self, path):
        def decorator(fn):
            self.routes[path] = fn
            return fn
        return decorator

    def get(self, path):
        return self._register(path)

    def post(self, path):
        return self._register(path)


class FakeMingsiClient:
    def __init__(self, *, person_name="示上某", approval=True):
        self.person_name = person_name
        self.approval = approval
        self.calls = []
        self.uploaded = None
        self.approved_body = None

    def status(self):
        return {"configured": True, "connected": True, "account": "18********00", "account_id": "acct-test"}

    async def profile(self):
        return {"personid": "applicant-1", "personname": self.person_name, "departmentid": "dept-1"}

    async def authenticated(self, path, *, data=None, params=None, files=None):
        self.calls.append((path, data, params, files))
        if path == "/sys/syscommondataCasetype/chapterTypeList":
            return {"code": 0, "data": {"list": [{
                "commondataid": "BIG-NON-BUSINESS", "commondataname": "非业务用章",
                "children": [{"commondataid": "SMALL-SUOHAN-NON-BUSINESS", "commondataname": "所函"}],
            }, {
                "commondataid": "BIG-OTHER", "commondataname": "业务用章",
                "children": [{"commondataid": "SMALL-SUOHAN", "commondataname": "所函"}],
            }]}}
        if path == "/sys/syscommondata/paymentList":
            return {"code": 0, "data": {"list": [{"commondataid": "FILE-SUOHAN", "commondataname": "所函"}]}}
        if path == "/sys/syscommondataCasetype/getChapterDetailed":
            category_id = str((params or {}).get("casetypeid"))
            return {"code": 0, "data": {"chapterDetailed": {
                "casetypeid": category_id,
                "isrecase": "REQUIRED" if category_id == "SMALL-SUOHAN" else "NOTDISPLAY",
            }}}
        if path == "/sys/syscommondata/getSealTypeList":
            return {"code": 0, "data": {"sealtypelist": [{"sealtypeid": "SEAL-OFFICIAL", "sealtypename": "公章"}]}}
        if path == "/case/chapter/getAuditor":
            return {"code": 0, "data": {"person": {"epmsPersonEntityList": [
                {"personid": "HUANG-1", "personname": "示上某"},
            ]}}}
        if path == "/sys/oss/upload":
            self.uploaded = files
            return {"code": 0, "file": [{"fileid": "file-1", "filename": "所函.docx"}]}
        if path == "/case/chapter/saveChapter":
            # MingSi currently returns the new application ID as a scalar.
            return {"code": 0, "data": "chapter-1"}
        if path == "/case/chapter/getChapterAudit":
            return {"code": 0, "chapterForm": {
                "epmsChapterEntity": {
                    "chapterid": "chapter-1", "chapterbigtype": "BIG-OTHER", "chaptertype": "SMALL-SUOHAN",
                    "caseid": "case-1", "chapterapplypsnid": "applicant-1", "chapterapplypsnname": self.person_name,
                    "chapterapplydate": "2026-09-12", "chaptercopies": 1, "approvalstatus": 0,
                    "chapterway": "", "issendsmg": "", "contractamount": 0,
                },
                "chapterfilelist": [{"value": "FILE-SUOHAN", "label": "所函"}],
                "epmsChapterInvolveEntityList": [], "epmsAttachfilesEntityList": [{"fileid": "file-1"}],
                "sealids": ["SEAL-OFFICIAL"], "crossbranchDeptmentList": [], "subjectnameList": [],
                "useChapterTypeList": [], "epmsShimoViewEntityList": [],
                "epmsSubsidiaryAttachfilesEntityList": [], "epmsFxqIndividualAccountEntityList": [],
            }, "processProgressFormList": [{"state": 0, "taskstepnum": 8}]}
        if path == "/case/chapter/getNextAuditor":
            return {"code": 0, "data": {"person": {"epmsPersonEntityList": [
                {"personid": "NEXT-1", "personname": "下一级审批人"},
                {"personid": "NEXT-2", "personname": "备用审批人"},
            ]}}}
        if path == "/case/chapter/chapterApproved":
            self.approved_body = data
            return {"code": 0, "msg": "ok"}
        if path == "/case/filing/getRelatedProjectListPage":
            return {"code": 0, "data": {"list": [{"caseid": "case-1", "casename": "测试项目", "casecode": "（2026）粤01号", "departmentid": "dept-9"}], "total": 1}}
        raise AssertionError(f"unexpected MingSi path: {path}")


class FailingApprovalClient(FakeMingsiClient):
    async def authenticated(self, path, *, data=None, params=None, files=None):
        if path == "/case/chapter/chapterApproved":
            self.calls.append((path, data, params, files))
            raise HTTPException(status_code=504, detail="明思系统响应超时，请稍后重试")
        return await super().authenticated(path, data=data, params=params, files=files)


class SaveWithoutChapterIdClient(FakeMingsiClient):
    async def authenticated(self, path, *, data=None, params=None, files=None):
        if path == "/case/chapter/saveChapter":
            self.calls.append((path, data, params, files))
            return {"code": 0, "msg": "success"}
        if path == "/case/chapter/getChapterListPage":
            self.calls.append((path, data, params, files))
            return {"code": 0, "list": [[{
                "chapterid": "recovered-chapter-1",
                "caseid": "case-1",
                "chaptertype": "所函",
                "chapterapplydate": dt.date.today().isoformat(),
                "chaptercopies": 1,
                "chapterapplypsnname": self.person_name,
            }, {
                # A same-day duplicate is deliberately below the newest row.
                # Reconciliation must follow MingSi's list ordering.
                "chapterid": "older-chapter-0",
                "caseid": "case-1",
                "chaptertype": "所函",
                "chapterapplydate": dt.date.today().isoformat(),
                "chaptercopies": 1,
                "chapterapplypsnname": self.person_name,
            }], [{"current": 1, "total": 1, "pages": 1}]]}
        return await super().authenticated(path, data=data, params=params, files=files)


class QuickReconcileClient(FakeMingsiClient):
    async def authenticated(self, path, *, data=None, params=None, files=None):
        if path == "/case/chapter/getChapterListPage":
            self.calls.append((path, data, params, files))
            return {"code": 0, "list": [[{
                "chapterid": "existing-quick-chapter",
                "caseid": "case-1",
                "chapterbigtype": "BIG-OTHER",
                "chaptertype": "SMALL-SUOHAN",
                "chapterapplydate": dt.date.today().isoformat(),
                "chaptercopies": 1,
                "chapterapplypsnname": self.person_name,
            }], [{"current": 1, "total": 1}]]}
        return await super().authenticated(path, data=data, params=params, files=files)


class OtherQuickTypeClient(FakeMingsiClient):
    async def authenticated(self, path, *, data=None, params=None, files=None):
        if path == "/sys/syscommondataCasetype/chapterTypeList":
            self.calls.append((path, data, params, files))
            return {"code": 0, "data": {"list": [{
                "commondataid": "BIG-OTHER", "commondataname": "业务用章",
                "children": [{"commondataid": "SMALL-OTHER", "commondataname": "其他"}],
            }]}}
        return await super().authenticated(path, data=data, params=params, files=files)


class MingsiChapterServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "apex.sqlite"
        migrate_database(self.db_path)

        def get_db():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn

        self.get_db = get_db

    def tearDown(self):
        self.directory.cleanup()

    def _artifact(self, payload=None):
        return store_document_bundle_artifact(
            self.get_db, b"exact-suohan-bytes", "所函_测试.docx", payload or {"clientName": "测试委托人"}
        )

    def _service(self, client):
        app = FakeApp()
        register_mingsi_chapter_routes(app, self.get_db, lambda: client)
        return app

    def test_bootstrap_and_project_search_resolve_dynamic_values(self):
        client = FakeMingsiClient()
        app = self._service(client)
        bootstrap = asyncio.run(app.routes["/api/mingsi-chapters/bootstrap"]())
        self.assertEqual(bootstrap["file_type"], {"big_id": "BIG-OTHER", "small_id": "SMALL-SUOHAN", "label": "所函"})
        self.assertEqual(bootstrap["seal_type"], {"id": "SEAL-OFFICIAL", "label": "公章"})
        self.assertEqual(bootstrap["first_approver"], {"id": "HUANG-1", "name": "示上某"})
        self.assertTrue(bootstrap["approval_available"])
        projects = asyncio.run(app.routes["/api/mingsi-chapters/projects"]("测试"))
        self.assertEqual(projects["items"][0]["id"], "case-1")
        request = next(call for call in client.calls if call[0] == "/case/filing/getRelatedProjectListPage")
        self.assertEqual(request[1]["casemark"], "CHAPTER")
        self.assertEqual(request[1]["casename"], "测试")

    def test_submit_uploads_exact_artifact_and_approves_with_next_candidates(self):
        client = FakeMingsiClient()
        app = self._service(client)
        artifact = self._artifact()
        result = asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"]({
            "artifact_id": artifact["artifact_id"], "project_id": "case-1", "project_name": "测试项目",
        }))
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["copies"], 1)
        self.assertEqual([item["id"] for item in result["next_approvers"]], ["NEXT-1", "NEXT-2"])
        self.assertEqual(result["next_approver"]["id"], "NEXT-1")
        upload = client.uploaded[0][1]
        self.assertEqual(upload[0], artifact["filename"])
        self.assertEqual(upload[1], b"exact-suohan-bytes")
        save_call = next(call for call in client.calls if call[0] == "/case/chapter/saveChapter")
        save_body = save_call[1]
        self.assertEqual(save_body["chapterfilelist"], [{"commondataid": "FILE-SUOHAN", "commondataname": "所函"}])
        self.assertEqual(save_body["epmsChapterEntity"]["chapterbigtype"], "BIG-OTHER")
        self.assertEqual(save_body["epmsChapterEntity"]["chaptertype"], "SMALL-SUOHAN")
        self.assertEqual(save_body["epmsChapterEntity"]["chaptercopies"], 1)
        self.assertEqual(save_body["sealids"], ["SEAL-OFFICIAL"])
        self.assertEqual(save_body["auditorlist"], ["HUANG-1"])
        self.assertEqual(save_body["epmsAttachfilesEntityList"], [{"fileid": "file-1", "filename": "所函.docx"}])
        self.assertEqual(client.approved_body["auditorlist"], ["NEXT-1"])

        self.assertEqual(client.approved_body["taskstepnum"], 8)
        self.assertEqual(client.approved_body["tasktype"], "用章流程")
        self.assertEqual(client.approved_body["epmsChapterEntity"]["chapterid"], "chapter-1")
        stored = get_document_bundle_artifact(self.get_db, artifact["artifact_id"])
        self.assertEqual(stored["suohan_content"], b"exact-suohan-bytes")
        self.assertEqual(stored["sha256"], artifact["sha256"])

    def test_quick_submit_reuses_recent_accepted_application_without_second_save(self):
        client = QuickReconcileClient()
        app = self._service(client)
        upload = UploadFile(file=io.BytesIO(b"retry-bytes"), filename="重试.pdf")
        result = asyncio.run(app.routes["/api/mingsi-chapters/quick-submit"](
            category_id="BIG-OTHER",
            subtype_id="SMALL-SUOHAN",
            project_id="case-1",
            project_name="测试项目",
            department_id="dept-9",
            copies=1,
            files=[upload],
        ))
        self.assertEqual(result["chapter_id"], "existing-quick-chapter")
        self.assertFalse(any(call[0] == "/case/chapter/saveChapter" for call in client.calls))
        self.assertIsNone(client.uploaded)

    def test_quick_submit_other_does_not_send_additional_file_type(self):
        client = OtherQuickTypeClient()
        app = self._service(client)
        upload = UploadFile(file=io.BytesIO(b"other-bytes"), filename="其他材料.pdf")
        asyncio.run(app.routes["/api/mingsi-chapters/quick-submit"](
            category_id="BIG-OTHER",
            subtype_id="SMALL-OTHER",
            project_id="case-1",
            project_name="测试项目",
            department_id="dept-9",
            copies=1,
            files=[upload],
        ))
        save_call = next(call for call in client.calls if call[0] == "/case/chapter/saveChapter")
        self.assertEqual(save_call[1]["chapterfilelist"], [])
        self.assertEqual(save_call[1]["epmsAttachfilesEntityList"], [{"fileid": "file-1", "filename": "所函.docx"}])

    def test_reconciles_id_from_mingsi_list_when_save_ack_has_no_id(self):
        client = SaveWithoutChapterIdClient()
        app = self._service(client)
        artifact = self._artifact({"reconcile": True})
        result = asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"]({
            "artifact_id": artifact["artifact_id"], "project_id": "case-1", "copies": 1,
        }))
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["chapter_id"], "recovered-chapter-1")
        list_call = next(call for call in client.calls if call[0] == "/case/chapter/getChapterListPage")
        self.assertEqual(list_call[1]["mychapter"], 1)
        self.assertEqual(list_call[1]["caseid"], "case-1")
        self.assertEqual(list_call[1]["chaptertypes"], "SMALL-SUOHAN")

    def test_non_huang_user_submits_but_never_calls_approval(self):
        client = FakeMingsiClient(person_name="李四", approval=False)
        app = self._service(client)
        artifact = self._artifact({"case": "pending"})
        result = asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"]({
            "artifact_id": artifact["artifact_id"], "project_id": "case-1", "copies": 3,
        }))
        self.assertEqual(result["status"], "pending")
        self.assertIn("等待示上某审批", result["message"])
        self.assertEqual(result["copies"], 3)
        self.assertFalse(any(call[0] == "/case/chapter/chapterApproved" for call in client.calls))
        self.assertEqual(result["next_approver"]["id"], "NEXT-1")
        save_call = next(call for call in client.calls if call[0] == "/case/chapter/saveChapter")
        self.assertEqual(save_call[1]["epmsChapterEntity"]["chaptercopies"], 3)

    def test_duplicate_click_returns_existing_record_without_second_remote_save(self):
        client = FakeMingsiClient()
        app = self._service(client)
        artifact = self._artifact()
        body = {"artifact_id": artifact["artifact_id"], "project_id": "case-1", "copies": 2}
        first = asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"](body))
        call_count = len(client.calls)
        second = asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"](body))
        self.assertEqual(first["chapter_id"], second["chapter_id"])
        self.assertEqual(second["status"], "approved")
        self.assertEqual(len(client.calls), call_count)

    def test_consumed_artifact_cannot_be_submitted_to_another_project(self):
        client = FakeMingsiClient()
        app = self._service(client)
        artifact = self._artifact({"case": "consumed"})
        asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"]({
            "artifact_id": artifact["artifact_id"], "project_id": "case-1",
        }))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"]({
                "artifact_id": artifact["artifact_id"], "project_id": "case-2",
            }))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len([call for call in client.calls if call[0] == "/case/chapter/saveChapter"]), 1)

    def test_expired_artifact_is_rejected(self):
        artifact = self._artifact()
        with self.get_db() as conn:
            conn.execute("UPDATE document_bundle_artifacts SET expires_at='2000-01-01T00:00:00+00:00' WHERE artifact_id=?", (artifact["artifact_id"],))
            conn.commit()
        app = self._service(FakeMingsiClient())
        with self.assertRaises(HTTPException) as error:
            asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"]({
                "artifact_id": artifact["artifact_id"], "project_id": "case-1",
            }))
        self.assertEqual(error.exception.status_code, 410)

    def test_approval_timeout_is_recorded_as_unknown_and_not_retried_blindly(self):
        client = FailingApprovalClient()
        app = self._service(client)
        artifact = self._artifact({"case": "approval-timeout"})
        body = {"artifact_id": artifact["artifact_id"], "project_id": "case-1"}
        with self.assertRaises(HTTPException) as error:
            asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"](body))
        self.assertEqual(error.exception.status_code, 502)
        chapter_calls = len([call for call in client.calls if call[0] == "/case/chapter/saveChapter"])
        with self.get_db() as conn:
            row = conn.execute("SELECT status, chapter_id, message FROM mingsi_chapter_submissions WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone()
        self.assertEqual(tuple(row), ("unknown", "chapter-1", "明思系统响应超时，请稍后重试"))
        second = asyncio.run(app.routes["/api/mingsi-chapters/submit-and-approve"](body))
        self.assertEqual(second["status"], "unknown")
        self.assertEqual(len([call for call in client.calls if call[0] == "/case/chapter/saveChapter"]), chapter_calls)

    def test_quick_type_options_preserve_dynamic_category_and_subtype_ids(self):
        chapter_types = {"data": {"list": [
            {"commondataid": "BIG-BUSINESS", "commondataname": "业务用章", "children": [
                {"commondataid": "SMALL-CONTRACT", "commondataname": "业务合同"},
                {"commondataid": "SMALL-OPINION", "commondataname": "法律意见书"},
            ]},
            {"commondataid": "BIG-NON", "commondataname": "非业务用章", "children": [
                {"commondataid": "SMALL-OTHER", "commondataname": "其他"},
            ]},
        ]}}
        file_types = {"data": {"list": [
            {"commondataid": "FILE-CONTRACT", "commondataname": "业务合同"},
            {"commondataid": "FILE-OPINION", "commondataname": "法律意见书"},
            {"commondataid": "FILE-OTHER", "commondataname": "其他"},
        ]}}
        options = _quick_type_options(chapter_types, file_types)
        self.assertEqual([item["name"] for item in options], ["业务用章", "非业务用章"])
        self.assertEqual(options[0]["subtypes"][0]["id"], "SMALL-CONTRACT")
        self.assertEqual(options[0]["subtypes"][0]["file_item"], {"commondataid": "FILE-CONTRACT", "commondataname": "业务合同"})
        self.assertIsNone(_quick_selected_type({"categories": options}, "BIG-NON", "SMALL-OTHER")["file_item"])

    def test_quick_type_without_file_mapping_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            _quick_selected_type({"categories": [{"id": "BIG", "name": "业务用章", "subtypes": [{"id": "SMALL", "name": "法律意见书", "file_item": None}]}]}, "BIG", "SMALL")
        self.assertEqual(error.exception.status_code, 502)

    def test_quick_type_other_does_not_require_additional_file(self):
        options = _quick_type_options(
            {"list": [{"id": 136, "name": "非业务用章", "children": [{"id": 152, "name": "其他"}]}]},
            {"page": {"records": [{"commondataid": 3790, "commondataname": "其他"}, {"commondataid": 3791, "commondataname": "所函"}]}},
        )
        selected = _quick_selected_type({"categories": options}, "136", "152")
        self.assertIsNone(selected["file_item"])
        self.assertFalse(selected["file_item_fallback"])

    def test_quick_type_uses_live_generic_file_mapping_for_other_named_subtype(self):
        options = _quick_type_options(
            {"list": [{"id": 136, "name": "非业务用章", "children": [{"id": 149, "name": "律师函"}]}]},
            {"page": {"records": [{"commondataid": 3790, "commondataname": "所函"}]}},
        )
        selected = _quick_selected_type({"categories": options}, "136", "149")
        self.assertEqual(selected["file_item"], {"commondataid": "3790", "commondataname": "所函"})
        self.assertTrue(selected["file_item_fallback"])

    def test_quick_submit_uploads_selected_type_and_approves(self):
        client = FakeMingsiClient()
        app = self._service(client)
        upload = UploadFile(file=io.BytesIO(b"quick-approval-bytes"), filename="测试合同.pdf")
        result = asyncio.run(app.routes["/api/mingsi-chapters/quick-submit"](
            category_id="BIG-OTHER",
            subtype_id="SMALL-SUOHAN",
            project_id="case-1",
            project_name="测试项目",
            department_id="dept-9",
            copies=2,
            remark="请尽快盖章",
            files=[upload],
        ))
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["chapter_id"], "chapter-1")
        self.assertEqual(client.uploaded[0][0], "files")
        self.assertEqual(client.uploaded[0][1][0], "测试合同.pdf")
        self.assertEqual(client.uploaded[0][1][1], b"quick-approval-bytes")
        save_call = next(call for call in client.calls if call[0] == "/case/chapter/saveChapter")
        self.assertEqual(save_call[1]["chapterfilelist"], [{"commondataid": "FILE-SUOHAN", "commondataname": "所函"}])
        self.assertEqual(save_call[1]["epmsChapterEntity"]["chapterbigtype"], "BIG-OTHER")
        self.assertEqual(save_call[1]["epmsChapterEntity"]["chaptertype"], "SMALL-SUOHAN")
        self.assertEqual(save_call[1]["epmsChapterEntity"]["chaptercopies"], 2)
        self.assertEqual(save_call[1]["epmsChapterEntity"]["chapterremark"], "请尽快盖章")
        self.assertEqual(client.approved_body["auditorlist"], ["NEXT-1"])


if __name__ == "__main__":
    unittest.main()
