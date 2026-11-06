import unittest
from backend.series_table_editing import remap_text_format, remap_format_edits


class TextFormatMappingTests(unittest.TestCase):
    def test_insert_keeps_spanning_style_and_cell_alignment(self):
        original = {'runs': [{'start': 0, 'end': 4, 'bold': True}], 'align': 'right'}
        result = remap_text_format('匿名案件', '匿名新案件', original)
        self.assertEqual(result, {'runs': [{'start': 0, 'end': 5, 'bold': True}], 'align': 'right'})
        self.assertEqual(original['runs'][0]['end'], 4)

    def test_offsets_use_utf16_with_non_bmp_characters(self):
        result = remap_text_format('😀甲乙', '😀新甲乙', {'runs': [{'start': 2, 'end': 4, 'color': 'red'}]})
        self.assertEqual(result['runs'], [{'start': 3, 'end': 5, 'color': 'red'}])

    def test_replacement_does_not_extend_partial_styles_into_unrelated_text(self):
        result = remap_text_format('甲乙丙丁', '甲新丁', {'runs': [{'start': 1, 'end': 2, 'bold': True}]})
        self.assertNotIn('runs', result)

    def test_empty_value_keeps_cell_format_only(self):
        result = remap_text_format('甲乙', '', {'runs': [{'start': 0, 'end': 2, 'bold': True}], 'cell_background': 'yellow'})
        self.assertEqual(result, {'cell_background': 'yellow'})

    def test_multiple_edits_preserve_unchanged_middle_style(self):
        result = remap_format_edits('甲重点甲', '乙重点乙', {'runs': [{'start': 1, 'end': 3, 'color': 'red'}]}, [{'start': 0, 'end': 1, 'text': '乙'}, {'start': 3, 'end': 4, 'text': '乙'}])
        self.assertEqual(result['runs'], [{'start': 1, 'end': 3, 'color': 'red'}])

    def test_known_edit_ranges_reject_wrong_result(self):
        with self.assertRaises(ValueError):
            remap_format_edits('原文', '错误结果', {}, [{'start': 0, 'end': 1, 'text': '改'}])
