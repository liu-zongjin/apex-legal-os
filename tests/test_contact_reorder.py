from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ContactReorderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "frontend" / "case-manager.js").read_text(encoding="utf-8")

    def test_contact_handle_uses_pointer_reorder_instead_of_native_html_drag(self):
        self.assertIn(
            'class="btn contact-edit-drag-handle" type="button" draggable="false"',
            self.page,
        )
        self.assertIn('onpointerdown="contactGroupPointerDown(event)"', self.page)
        self.assertIn("document.addEventListener('pointermove', move, true)", self.page)
        self.assertIn("document.addEventListener('pointerup', finish, true)", self.page)

    def test_reordered_contact_groups_are_saved_in_dom_order(self):
        self.assertIn(
            "[...category.querySelectorAll('.contact-group')].map(group => ({",
            self.page,
        )
        self.assertIn(
            "const contacts = collectContactGroups();",
            self.page,
        )
        self.assertIn(
            "next.court_contact = serializeContactGroups(contacts, 'court');",
            self.page,
        )
        self.assertIn(
            "next.party_contact = serializeContactGroups(contacts, 'party');",
            self.page,
        )


if __name__ == "__main__":
    unittest.main()
