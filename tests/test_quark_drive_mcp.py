import json
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend import mcp_manager, quark_drive_mcp
from backend.ai_strategy import DEFAULT_STRATEGY, validate_config


class QuarkDriveMCPTests(unittest.IsolatedAsyncioTestCase):
    def test_manager_exposes_quark_as_local_mcp_adapter(self):
        server = mcp_manager._definition("quark_drive")
        self.assertEqual(server["protocol"], "quark_skill")
        self.assertIn("文件知识问答", server["tools"])

    def test_quark_oauth_folder_fid_character_set(self):
        fid = "~1_TgTYs6P5CoQ1WzCYY-d6ZrK_yoOOX9JgFE"
        self.assertTrue(all(char.isalnum() or char in "-~_" for char in fid))

    def test_v1_strategy_migrates_source_once_and_v2_respects_disable(self):
        old = copy.deepcopy(DEFAULT_STRATEGY)
        old["schema_version"] = 1
        old["routing"]["allowed_sources"].remove("quark_drive")
        migrated = validate_config(old)["normalized_config"]
        self.assertIn("quark_drive", migrated["routing"]["allowed_sources"])

        current = copy.deepcopy(migrated)
        current["routing"]["allowed_sources"].remove("quark_drive")
        preserved = validate_config(current)["normalized_config"]
        self.assertNotIn("quark_drive", preserved["routing"]["allowed_sources"])

    def test_search_keyword_is_bounded_and_keeps_topic(self):
        question = "请根据夸克网盘中的内容，建设工程价款优先受偿权在破产程序中如何行使？" * 2
        keyword = quark_drive_mcp._search_keyword(question)
        self.assertLessEqual(len(keyword), 50)
        self.assertIn("建设工程价款优先受偿权", keyword)

    def test_artifact_fids_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.jsonl"
            path.write_text(
                "\n".join([
                    json.dumps({"fid": "a", "filename": "A.pdf"}),
                    json.dumps({"data": {"file_list": [{"fid": "b"}, {"fid": "a"}]}}),
                ]),
                encoding="utf-8",
            )
            self.assertEqual(quark_drive_mcp._read_artifact_fids(path), ["a", "b"])

    def test_configured_scopes_are_sanitized_and_deduplicated(self):
        value = json.dumps([
            {"fid": "folder-1", "name": "项目资料"},
            {"fid": "folder-1", "name": "重复项"},
            {"fid": "", "name": "无效项"},
        ])
        with patch.dict(os.environ, {quark_drive_mcp.FOLDER_SCOPES_ENV: value}):
            self.assertEqual(
                quark_drive_mcp.configured_scopes(),
                [{"fid": "folder-1", "name": "项目资料"}],
            )

    def test_usage_status_tracks_local_calls_without_claiming_official_balance(self):
        with tempfile.TemporaryDirectory() as folder:
            usage_path = Path(folder) / "usage.json"
            with patch.object(quark_drive_mcp, "_USAGE_PATH", usage_path):
                quark_drive_mcp._record_usage("search", True, "成功")
                quark_drive_mcp._record_usage("qa", False, "文件仍在分析")
                usage = quark_drive_mcp.usage_status()
        self.assertEqual(usage["search_count"], 1)
        self.assertEqual(usage["assistant_count"], 1)
        self.assertEqual(usage["assistant_success_count"], 0)
        self.assertFalse(usage["official_remaining_available"])
        self.assertEqual(usage["max_files_per_question"], 10_000)

    async def test_answer_searches_once_then_asks_with_same_session(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.jsonl"
            path.write_text(json.dumps({"fid": "file-1"}), encoding="utf-8")
            search_rows = [
                {"code": 0, "type": "result", "data": {"total": 1}},
                {"code": 0, "type": "artifact", "data": {"file_path": str(path)}},
            ]
            answer_rows = [{
                "code": 0,
                "type": "result",
                "data": {"text_block": {"title": "RAG答案", "text": "依据网盘文件作答。"}},
            }]
            with patch.dict(os.environ, {quark_drive_mcp.FOLDER_SCOPES_ENV: ""}):
                with patch.object(
                    quark_drive_mcp,
                    "_run_cli",
                    new=AsyncMock(side_effect=[search_rows, answer_rows]),
                ) as run:
                    result = await quark_drive_mcp.answer_from_drive("文件中约定的付款期限是什么？")

        self.assertEqual(result["answer"], "依据网盘文件作答。")
        self.assertEqual(run.await_count, 2)
        first, second = run.await_args_list
        self.assertEqual(first.args[0], "search")
        self.assertEqual(second.args[0], "qa")
        self.assertEqual(first.kwargs["session_id"], second.kwargs["session_id"])

    async def test_scoped_answer_asks_selected_folders_without_whole_drive_search(self):
        scopes = json.dumps([
            {"fid": "folder-a", "name": "A项目"},
            {"fid": "folder-b", "name": "B项目"},
        ])
        answer_rows = [{
            "code": 0,
            "type": "result",
            "data": {"text_block": {"title": "限定范围", "text": "只依据两个项目文件夹。"}},
        }]
        with patch.dict(os.environ, {quark_drive_mcp.FOLDER_SCOPES_ENV: scopes}):
            with patch.object(
                quark_drive_mcp, "_run_cli", new=AsyncMock(return_value=answer_rows)
            ) as run:
                result = await quark_drive_mcp.answer_from_drive("合同约定是什么？")

        self.assertEqual(run.await_count, 1)
        self.assertEqual(run.await_args_list[0].args[0], "qa")
        self.assertIn("folder-a,folder-b", run.await_args_list[0].args)
        self.assertEqual(result["scope_folders"], 2)
        self.assertEqual(result["matched_files"], 0)

    async def test_scoped_answer_returns_provider_analysis_status(self):
        scopes = json.dumps([{"fid": "folder-a", "name": "A项目"}])
        with patch.dict(os.environ, {quark_drive_mcp.FOLDER_SCOPES_ENV: scopes}):
            with patch.object(
                quark_drive_mcp,
                "_run_cli",
                new=AsyncMock(side_effect=quark_drive_mcp.QuarkDriveMCPError("请在24小时后重试")),
            ) as run:
                with self.assertRaisesRegex(quark_drive_mcp.QuarkDriveMCPError, "24小时"):
                    await quark_drive_mcp.answer_from_drive("合同约定是什么？")

        self.assertEqual(run.await_count, 1)

    async def test_empty_search_does_not_retry_or_ask(self):
        rows = [{"code": 0, "type": "result", "data": {"total": 0}}]
        with patch.dict(os.environ, {quark_drive_mcp.FOLDER_SCOPES_ENV: ""}):
            with patch.object(quark_drive_mcp, "_run_cli", new=AsyncMock(return_value=rows)) as run:
                with self.assertRaisesRegex(quark_drive_mcp.QuarkDriveMCPError, "未在夸克网盘"):
                    await quark_drive_mcp.answer_from_drive("不存在的材料")
        self.assertEqual(run.await_count, 1)


if __name__ == "__main__":
    unittest.main()
