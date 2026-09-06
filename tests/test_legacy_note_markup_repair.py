import importlib.util
from pathlib import Path
import unittest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_legacy_note_markup.py"
_SPEC = importlib.util.spec_from_file_location("repair_legacy_note_markup", _SCRIPT)
repair_legacy_note_markup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(repair_legacy_note_markup)


class LegacyNoteMarkupRepairTests(unittest.TestCase):
    def test_removes_saved_runtime_badges_and_old_numeric_suffixes(self):
        html = (
            '<p>前文<span class="note-highlight note-anchor">关键词'
            '<sup class="note-anchor-badge">7</sup></span>后文</p>'
            '<p><span class="note-anchor"><span class="note-anchor">第二条8</span>7</span></p>'
        )

        cleaned = repair_legacy_note_markup.strip_legacy_markup(html)

        self.assertNotIn("note-anchor", cleaned)
        self.assertNotIn("note-highlight", cleaned)
        self.assertEqual(cleaned, "<p>前文关键词后文</p><p>第二条</p>")


if __name__ == "__main__":
    unittest.main()
