import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ClientPickerContractTests(unittest.TestCase):
    def test_public_contract_is_present(self):
        source = (ROOT / "frontend" / "apex-client-picker.js").read_text(encoding="utf-8")
        for contract in ("mode === 'multiple'", "placeholder", "setDisabled", "setValue",
                         "apex:client-change", "apex:client-open", "apex:client-error"):
            self.assertIn(contract, source)

    def test_picker_uses_shared_client_adapter(self):
        source = (ROOT / "frontend" / "apex-client-picker.js").read_text(encoding="utf-8")
        self.assertIn("ApexAPI.searchClients", source)
        self.assertNotIn("/api/case-manager/clients?", source)

    def test_adapter_keeps_legacy_endpoints_behind_one_boundary(self):
        source = (ROOT / "frontend" / "apex-api.js").read_text(encoding="utf-8")
        self.assertIn("/api/case-manager/clients?", source)
        self.assertIn("/api/document-generators/client-profile?", source)


if __name__ == "__main__":
    unittest.main()
