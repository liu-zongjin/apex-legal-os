import unittest

from backend.case_issue import (
    build_fact_fingerprint,
    build_search_constraints,
    constraint_hit,
    detect_court_level,
    evaluate_case_fit,
    infer_claim_direction,
)


QUERY = (
    "债权人在依据担保合同起诉连带责任保证人请求其承担连带担保责任，"
    "可以另行起诉主债务人请求其履行主合同项下债务，两者责任主体及请求权基础不同，"
    "不构成重复起诉。"
)

REVOCATION_FEE_QUERY = (
    "案例检索：广东省内或其他省的中级人民法院法院的以下案件是如何收费的："
    "债务人无偿放弃到期债权，债权人就此提起撤销权诉讼的诉讼费如何收取？"
)


DIRECT_5989 = (
    "本院认为，主债务人与连带保证人责任各自独立。债务人依主债法律关系承担清偿责任，"
    "保证人依保证法律关系承担连带保证责任，两者为不同法律关系。债权人对债务人和保证人的"
    "起诉为可分之诉，可以分别起诉。黄某另案向保证人主张连带保证责任后，仍可在本案中就同一笔"
    "债务向主债务人主张清偿责任。双重受益属于判项表述或执行问题，不应作为裁定驳回的依据。"
)


REVERSE_CASE = (
    "债权人在前案中起诉主债务人还本付息，此后又另行起诉连带责任保证人，"
    "请求保证人对未清偿部分承担保证责任。法院认为不构成重复起诉。"
)


class CaseIssueFingerprintTests(unittest.TestCase):
    def test_extracts_guarantor_to_debtor_direction_and_judicial_routes(self):
        fingerprint = build_fact_fingerprint(QUERY)
        self.assertEqual(fingerprint["kind"], "sequential_guarantee_claims")
        self.assertEqual(fingerprint["direction"], "guarantor_to_debtor")
        self.assertTrue(fingerprint["strict_direction"])
        self.assertIn("保证责任 后 仍可 主债务人", fingerprint["query_routes"])
        self.assertIn("主债务人 连带保证人 责任各自独立", fingerprint["query_routes"])

    def test_direction_classifier_distinguishes_direct_and_reverse_cases(self):
        self.assertEqual(infer_claim_direction(DIRECT_5989), "guarantor_to_debtor")
        self.assertEqual(infer_claim_direction(REVERSE_CASE), "debtor_to_guarantor")

    def test_direct_case_outranks_reverse_direction_case(self):
        fingerprint = build_fact_fingerprint(QUERY)
        direct = evaluate_case_fit([DIRECT_5989], fingerprint)
        reverse = evaluate_case_fit([REVERSE_CASE], fingerprint)
        self.assertEqual(direct["match_tier"], "highly_similar")
        self.assertEqual(direct["direction_match"], "aligned")
        self.assertEqual(reverse["match_tier"], "reverse_direction")
        self.assertGreater(direct["fit_score"], reverse["fit_score"])

    def test_same_direction代位权_case_is_analogical_not_fully_identical(self):
        fingerprint = build_fact_fingerprint(QUERY)
        fit = evaluate_case_fit([
            "本院认为，债权人根据保证合同向保证人主张权利后，仍可另行向主债务人主张权利，"
            "不构成重复诉讼。本案系债权人代位权纠纷。"
        ], fingerprint)
        self.assertEqual(fit["direction_match"], "aligned")
        self.assertEqual(fit["match_tier"], "analogical")


class SearchConstraintTests(unittest.TestCase):
    def test_parses_intermediate_court_with_open_region(self):
        constraints = build_search_constraints(REVOCATION_FEE_QUERY)
        self.assertEqual(constraints["court_levels"], ["intermediate"])
        self.assertEqual(constraints["strict_regions"], [])
        self.assertTrue(constraints["present"])
        self.assertIn("中级人民法院", constraints["description"])
        self.assertIn("地域不限", constraints["description"])

    def test_strict_region_when_no_open_marker(self):
        constraints = build_search_constraints("广东省内的中级人民法院如何认定违约金过高？")
        self.assertIn("intermediate", constraints["court_levels"])
        self.assertEqual(constraints["strict_regions"], ["广东"])

    def test_constraint_words_exclude_issue_terms(self):
        constraints = build_search_constraints(REVOCATION_FEE_QUERY)
        for word in constraints["constraint_words"]:
            self.assertNotIn(word, ("撤销权", "诉讼费", "放弃债权", "受理费"))

    def test_court_level_detection(self):
        self.assertEqual(detect_court_level("四川省成都市中级人民法院"), "intermediate")
        self.assertEqual(detect_court_level("最高人民法院"), "supreme")
        self.assertEqual(detect_court_level("浙江省义乌市人民法院"), "basic")
        self.assertEqual(detect_court_level("北海市铁山港区人民法院"), "basic")
        self.assertEqual(detect_court_level("广东省高级人民法院"), "high")

    def test_constraint_hit_flags_violating_courts(self):
        constraints = build_search_constraints(REVOCATION_FEE_QUERY)
        self.assertTrue(constraint_hit("广东省深圳市中级人民法院", constraints)["constraint_hit"])
        self.assertTrue(constraint_hit("四川省成都市中级人民法院", constraints)["constraint_hit"])
        self.assertFalse(constraint_hit("最高人民法院", constraints)["constraint_hit"])
        self.assertFalse(constraint_hit("浙江省义乌市人民法院", constraints)["constraint_hit"])
        notes = constraint_hit("浙江省义乌市人民法院", constraints)["notes"]
        self.assertTrue(any("基层" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
