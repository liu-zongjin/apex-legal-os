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

    def test_picker_exposes_paging_sort_and_recents(self):
        source = (ROOT / "frontend" / "apex-client-picker.js").read_text(encoding="utf-8")
        for contract in ("apex-client-picker-foot", "data-sort", "apex:client-sort",
                         "apex-client-picker-group-label", "insertAdjacentHTML",
                         "aria-activedescendant", "Intl.Collator"):
            self.assertIn(contract, source)

    def test_picker_highlights_matches(self):
        source = (ROOT / "frontend" / "apex-client-picker.js").read_text(encoding="utf-8")
        self.assertIn("apex-client-picker-mark", source)

    def test_picker_avoids_native_checkboxes(self):
        source = (ROOT / "frontend" / "apex-client-picker.js").read_text(encoding="utf-8")
        self.assertNotIn('type="checkbox"', source)

    def test_picker_anchors_menu_to_viewport(self):
        source = (ROOT / "frontend" / "apex-client-picker.js").read_text(encoding="utf-8")
        for contract in ("document.body.appendChild(this.menu)", "getBoundingClientRect",
                         "innerHeight", "scroll", "this.menu.remove()"):
            self.assertIn(contract, source)

    def test_menu_css_is_fixed_and_layered_above_edit_modals(self):
        source = (ROOT / "frontend" / "apex-components.css").read_text(encoding="utf-8")
        self.assertIn("position: fixed", source)
        self.assertIn("z-index: 10040", source)
        self.assertNotIn("overscroll-behavior", source)


if __name__ == "__main__":
    unittest.main()
