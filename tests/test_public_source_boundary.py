import unittest
from scripts.apex_guard import private_research_check, GuardFailure

class PublicSourceBoundaryTests(unittest.TestCase):
    def test_internal_reports_are_rejected_even_if_force_added(self):
        for path in ['docs/verification/session.md','docs/reviews/internal.md','docs/validation/run.md','CASE_REFERENCE_STUDY.md','.private/audit/notes.md']:
            with self.subTest(path=path),self.assertRaises(GuardFailure):
                private_research_check(['backend/main.py',path])

    def test_runtime_integrations_and_public_docs_remain_allowed(self):
        private_research_check(['backend/ai_config.py','frontend/ai-api-manager.html','docs/architecture/SYSTEM_MAP.md','README.md'])

    def test_empty_snapshot_is_allowed(self):
        private_research_check([])
