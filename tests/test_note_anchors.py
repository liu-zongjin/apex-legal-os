import json
import unittest
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

from backend import main


class NoteAnchorTests(unittest.TestCase):
    def test_selection_anchor_round_trip(self):
        anchor = {
            "version": 1,
            "start": 12,
            "end": 15,
            "quote": "关键字",
            "block_index": 1,
        }
        encoded = main._encode_note_selection_anchor(json.dumps(anchor, ensure_ascii=False))
        self.assertEqual(main._decode_note_selection_anchor(encoded), anchor)

    def test_word_comment_uses_selected_duplicate_paragraph(self):
        anchor = {
            "version": 1,
            "start": 10,
            "end": 13,
            "quote": "关键字",
            "block_index": 1,
        }
        raw = main._article_editor_docx_bytes(
            "测试",
            "<p>第一段关键字结束</p><p>第二段关键字结束</p>",
            [{
                "content": "属于第二段",
                "selected_text": "关键字",
                "selection_anchor": json.dumps(anchor, ensure_ascii=False),
                "created_at": "2026-08-15T12:00:00",
            }],
        )

        with zipfile.ZipFile(BytesIO(raw)) as docx:
            root = ET.fromstring(docx.read("word/document.xml"))
        word_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        anchored_text = ""
        for paragraph in root.findall(f".//{{{word_ns}}}p"):
            if paragraph.find(f"{{{word_ns}}}commentRangeStart") is not None:
                anchored_text = "".join(
                    node.text or "" for node in paragraph.findall(f".//{{{word_ns}}}t")
                )
                break

        self.assertIn("第二段关键字", anchored_text)


if __name__ == "__main__":
    unittest.main()
