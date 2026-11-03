from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ContactTableContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "frontend" / "case-manager.js").read_text(encoding="utf-8")

    def test_contact_rows_use_pointer_reorder_instead_of_native_html_drag(self):
        self.assertIn(
            'class="btn contact-edit-drag-handle" type="button" draggable="false"',
            self.page,
        )
        self.assertIn('onpointerdown="contactRowPointerDown(event)"', self.page)
        self.assertIn("document.addEventListener('pointermove', move, true)", self.page)
        self.assertIn("document.addEventListener('pointerup', finish, true)", self.page)
        self.assertIn("document.addEventListener('pointercancel', finish, true)", self.page)

    def test_contact_rows_are_rendered_as_one_spreadsheet(self):
        self.assertIn("function contactTableHtml(groups, item = {}, options = {})", self.page)
        self.assertIn("function contactViewRowHtml(row)", self.page)
        self.assertIn("function contactEditorRowHtml(row)", self.page)
        self.assertIn('name="contact_department"', self.page)
        self.assertIn('name="contact_organization"', self.page)
        self.assertIn("data-contact-search", self.page)
        self.assertIn("function toggleContactPin(button)", self.page)
        self.assertIn("function addContactRow(trigger, prefill = null, categoryKey = 'litigation')", self.page)

    def test_reordered_contact_rows_are_saved_in_dom_order(self):
        self.assertIn(
            "root.querySelectorAll('[data-contact-row]').forEach((row, index) => {",
            self.page,
        )
        self.assertIn("order: index,", self.page)
        self.assertIn("const contacts = collectContactGroups();", self.page)
        self.assertIn("next.court_contact = serializeContactGroups(contacts, 'court');", self.page)
        self.assertIn("next.party_contact = serializeContactGroups(contacts, 'party');", self.page)
        self.assertIn("lines.push('置顶：是')", self.page)
        self.assertIn("lines.push(`排序：${Number(item.order)}`)", self.page)

    def test_contact_ai_split_and_organization_lookup_contracts(self):
        self.assertIn("'/api/case-manager/contacts/ai-split'", self.page)
        self.assertIn("function aiSplitContactRow(button)", self.page)
        self.assertIn("function aiAddContactRow(input)", self.page)
        self.assertIn("include_contacts=1", self.page)
        self.assertIn("'使用当前单位并新建'", self.page)


class ContactTextParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "frontend" / "case-manager.js").read_text(encoding="utf-8")

    def test_structured_contact_text_supports_department_organization_and_pins(self):
        for label in ("部门职务", "单位", "置顶", "排序"):
            self.assertIn(label, self.page)
        self.assertIn("fields.pinned = ['是', '1', 'true', 'yes'].includes(value.toLowerCase());", self.page)


if __name__ == "__main__":
    unittest.main()
