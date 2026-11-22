import json
from pathlib import Path
import unittest

from backend.cause_catalog import document_cause_label
from scripts.build_cause_catalog import civil_parts, parse, validate


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


class CauseCatalogTests(unittest.TestCase):
    def test_source_counts_and_parent_order(self):
        catalog = json.loads((FRONTEND / "apex-cause-catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["source"]["status"], "compilation")
        self.assertEqual(len(catalog["source"]["sha256"]), 64)
        self.assertEqual(catalog["civilReview"], {"status": "compared", "differences": []})
        nodes = catalog["nodes"]
        validate(nodes)
        seen = {}
        for entry in nodes:
            self.assertGreater(entry["line"], 0)
            if entry["parent"]:
                parent = seen[entry["parent"]]
                self.assertEqual((parent["category"], parent["level"] + 1),
                                 (entry["category"], entry["level"]))
            seen[entry["id"]] = entry

    def test_civil_parentheses_preserve_name_punctuation(self):
        examples = {
            "企业名称（商号）合同纠纷（企业名称（商号）转让合同纠纷、企业名称（商号）使用合同纠纷）":
                ("企业名称（商号）合同纠纷", ["企业名称（商号）转让合同纠纷", "企业名称（商号）使用合同纠纷"]),
            "委托合同纠纷（诉讼、仲裁、人民调解代理合同纠纷、销售代理合同纠纷）":
                ("委托合同纠纷", ["诉讼、仲裁、人民调解代理合同纠纷", "销售代理合同纠纷"]),
            "申请海事请求保全（申请扣押船舶、申请拍卖扣押船舶）":
                ("申请海事请求保全", ["申请扣押船舶", "申请拍卖扣押船舶"]),
            "相邻关系纠纷（相邻用水、排水纠纷；相邻通行纠纷）":
                ("相邻关系纠纷", ["相邻用水、排水纠纷", "相邻通行纠纷"]),
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(civil_parts(raw), expected)

    def test_ids_stable_across_source_line_changes(self):
        text = "# 三、刑事案件罪名分类\n## 第五章 侵犯财产罪\n- 盗窃罪。\n"
        first = parse(text)[-1]
        moved = parse("\n\n" + text)[-1]
        self.assertNotEqual(first["line"], moved["line"])
        self.assertEqual(first["id"], moved["id"])

    def test_generated_document_wording(self):
        for name in ["盗窃罪", "行政处罚", "政府信息公开", "申请拍卖扣押船舶", "买卖合同纠纷", "劳动争议"]:
            self.assertEqual(document_cause_label(name, FRONTEND), name)
        self.assertEqual(document_cause_label("  自定义民事事由  ", FRONTEND), "自定义民事事由纠纷")
        self.assertEqual(document_cause_label("", FRONTEND), "")
