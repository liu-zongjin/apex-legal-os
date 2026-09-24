import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
CASE_MANAGER = (ROOT / "frontend" / "case-manager.js").read_text(encoding="utf-8")


class CaseManagerPageStateTests(unittest.TestCase):
    def test_each_outer_workspace_passes_its_own_storage_scope(self):
        self.assertIn("new URLSearchParams({ v: '2026090402', workspace_id: String(tab?.id || 'case-manager') })", APP)
        self.assertIn("workspace_id=${encodeURIComponent(tab.id)}&court_record=", APP)

    def test_restored_case_state_and_subtabs_are_scoped_to_workspace(self):
        self.assertIn("initialPageParams.get('workspace_id') || 'standalone'", CASE_MANAGER)
        self.assertIn("const workspaceSessionKey = name => `case-manager:${PAGE_WORKSPACE_ID}:${name}`", CASE_MANAGER)
        self.assertIn("workspaceSessionKey('open-case-detail')", CASE_MANAGER)
        self.assertIn("workspaceSessionKey('open-case-detail-state-v2')", CASE_MANAGER)
        self.assertIn("workspaceSessionKey('open-manager')", CASE_MANAGER)
        self.assertIn("'active-tab-manager-v2'", CASE_MANAGER)
        self.assertIn("'active-tab-court-online-v2'", CASE_MANAGER)

    def test_creating_a_new_case_clears_a_stale_detail_snapshot(self):
        start = CASE_MANAGER.index("function openNewCaseDetail()")
        end = CASE_MANAGER.index("function resetCaseResearchWorkspace()", start)
        self.assertIn("forgetOpenCaseDetail();", CASE_MANAGER[start:end])

    def test_only_the_latest_court_online_list_request_can_render(self):
        start = CASE_MANAGER.index("async function loadCourtOnline()")
        end = CASE_MANAGER.index("// 一张网子标签页配置", start)
        loader = CASE_MANAGER[start:end]
        self.assertIn("const requestSequence = ++courtOnlineLoadSequence", loader)
        self.assertIn("if (requestSequence !== courtOnlineLoadSequence) return", loader)
        self.assertIn("requestSequence === courtOnlineLoadSequence && activeTab === 'courtOnline'", loader)


if __name__ == "__main__":
    unittest.main()
