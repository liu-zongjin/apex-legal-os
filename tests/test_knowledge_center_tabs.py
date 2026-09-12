import re
import unittest
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "frontend" / "app.js"


class KnowledgeCenterTabNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_JS.read_text(encoding="utf-8")

    def _set_body(self, name):
        match = re.search(
            rf"const {name} = new Set\(\[\n(?P<body>.*?)\n\]\);",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, f"missing {name}")
        return match.group("body")

    def test_legal_knowledge_has_its_own_tab_group(self):
        knowledge = self._set_body("KNOWLEDGE_CENTER_TAB_TYPES")
        efficiency = self._set_body("TOOL_TAB_TYPES")
        self.assertEqual(knowledge.strip(), "TAB_TYPES.LEGAL_KNOWLEDGE,")
        self.assertNotIn("TAB_TYPES.LEGAL_KNOWLEDGE", efficiency)
        self.assertIn("TAB_TYPES.INTEREST_CALC", efficiency)
        self.assertIn("TAB_TYPES.QQ_MAIL", efficiency)
        self.assertIn("TAB_TYPES.SCANNER_INBOX", efficiency)
        self.assertIn("TAB_TYPES.PERSONAL_CENTER", efficiency)

    def test_both_navigation_surfaces_use_separate_groups(self):
        self.assertIn(
            "renderWorkspaceTabGroupMarkup('knowledge-center', knowledgeCenterTabs",
            self.source,
        )
        self.assertIn(
            "renderWorkspaceTabGroupMarkup('tools', toolTabs, {\n    label: '效率中心'",
            self.source,
        )
        self.assertIn(
            "{ id: 'knowledge-center', label: '知识中心'",
            self.source,
        )
        self.assertIn("{ id: 'tools', label: '效率中心'", self.source)
        self.assertIn(
            "if (KNOWLEDGE_CENTER_TAB_TYPES.has(tab.type)) return 'knowledge-center';",
            self.source,
        )

    def test_multiple_claim_pages_and_specific_titles_remain_supported(self):
        self.assertIn(
            "(type === TAB_TYPES.LEGAL_KNOWLEDGE && Number(t.data?.claimId || 0) === Number(data.claimId || 0))",
            self.source,
        )
        self.assertIn("function updateLegalKnowledgeTabTitle(tabId, claimId)", self.source)
        self.assertIn("detail?.issues?.[0]?.title", self.source)


if __name__ == "__main__":
    unittest.main()
