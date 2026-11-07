from __future__ import annotations

import unittest

from backend.case_manager import split_contact_text_fallback


class ContactSmartSplitFallbackTests(unittest.TestCase):
    def test_splits_court_contact_sentence(self):
        contact = split_contact_text_fallback("示例法院立案庭拍卖组 王法官 81234567")
        self.assertEqual(contact["name"], "王法官")
        self.assertIn("立案庭拍卖组", contact["department"])
        self.assertEqual(contact["organization"], "示例法院")
        self.assertEqual(contact["phone"], "81234567")

    def test_splits_company_contact_with_mobile_and_email(self):
        contact = split_contact_text_fallback("示例科技有限公司 法务部 李经理 13800138000 li@example.com")
        self.assertEqual(contact["name"], "李经理")
        self.assertIn("法务部", contact["department"])
        self.assertIn("示例科技有限公司", contact["organization"])
        self.assertEqual(contact["phone"], "13800138000")
        self.assertEqual(contact["email"], "li@example.com")

    def test_empty_input_returns_empty_fields(self):
        contact = split_contact_text_fallback("")
        self.assertTrue(all(value == "" for value in contact.values()))

class ContactSplitSafetyTests(unittest.TestCase):
    def test_names_and_area_codes_never_become_departments(self):
        for text, phone in [('张三 020-81234567', '020-81234567'),
                            ('张三（0757）8123 4567', '（0757）81234567'),
                            ('张三 0757 81234567', '075781234567')]:
            with self.subTest(text=text):
                value = split_contact_text_fallback(text)
                self.assertEqual(value['name'], '张三')
                self.assertEqual(value['phone'], phone)
                self.assertEqual(value['department'], '')

    def test_unknown_text_is_not_a_person_or_department(self):
        value = split_contact_text_fallback('020-81234567 待核实 明天下午联系')
        self.assertEqual(value['name'], '')
        self.assertEqual(value['department'], '')
        self.assertIn('待核实', value['notes'])

    def test_all_numbers_extensions_and_residue_survive(self):
        value = split_contact_text_fallback('王法官 138 0000 0001 0757-81234567 81234568转8128 明天下午联系')
        self.assertEqual(value['phone'], '13800000001、0757-81234567、81234568转8128')
        self.assertEqual(value['department'], '')
        self.assertIn('明天下午联系', value['notes'])

    def test_structured_row_reparses_misfiled_name_and_preserves_notes(self):
        text = '姓名：\n部门：张三 0757\n单位：\n电话：81234567\n邮箱：\n备注：仅周一联系'
        value = split_contact_text_fallback(text)
        self.assertEqual(value['name'], '张三')
        self.assertEqual(value['department'], '')
        self.assertEqual(value['phone'], '075781234567')
        self.assertIn('仅周一联系', value['notes'])

    def test_row_with_only_pasted_notes_can_be_split(self):
        value = split_contact_text_fallback('姓名：\n部门：\n单位：\n电话：\n邮箱：\n备注：张三 020-81234567 明天下午联系')
        self.assertEqual(value['name'], '张三')
        self.assertEqual(value['phone'], '020-81234567')
        self.assertIn('明天下午联系', value['notes'])

    def test_ai_cannot_invent_expand_or_misplace_phone(self):
        from backend.case_manager import validate_contact_split
        text = '示例法院 张三 020-81234567、81234568 待核实'
        local = split_contact_text_fallback(text)
        for data in [{'name': ['张三'], 'department':'张三 020', 'organization':'广州市天河区人民法院', 'phone':'99999999'},
                     {'name':'李四', 'department':{}, 'organization':None, 'notes':'AI编造'}]:
            value = validate_contact_split(text, data, local)
            self.assertEqual(value, local)


class ContactSplitRouteTests(unittest.TestCase):
    """Exercise the real request handler with a stub model, without a database."""
    def client(self, response=None, fail=False):
        import ast
        import json
        from pathlib import Path
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import case_manager as module
        async def fake_model(*args, **kwargs):
            if fail:
                raise RuntimeError('offline')
            return {'choices':[{'message':{'content':json.dumps(response)}}]}, 'stub'
        app = FastAPI()
        tree = ast.parse(Path(module.__file__).read_text())
        register = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'register_case_manager_routes')
        functions = [n for n in register.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in ('norm', 'ai_split_contact')]
        scope = {**vars(module), 'app':app, 'ai_call':fake_model}
        exec(compile(ast.Module(body=functions,type_ignores=[]), '<contact-route>', 'exec'),scope)
        return TestClient(app)

    def test_bad_model_output_and_outage_preserve_extraction(self):
        for client in (self.client({'department':'张三 020','name':[], 'phone':'123'}), self.client(fail=True)):
            response=client.post('/api/case-manager/contacts/ai-split',json={'text':'张三 020-81234567'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['contact']['name'],'张三')
            self.assertEqual(response.json()['contact']['department'],'')
            self.assertEqual(response.json()['contact']['phone'],'020-81234567')

    def test_long_input_rejected_instead_of_silently_truncated(self):
        client=self.client({})
        self.assertEqual(client.post('/api/case-manager/contacts/ai-split',json={'text':'注'*12001}).status_code,400)
        response=client.post('/api/case-manager/contacts/ai-split',json={'text':'张三 020-81234567 '+'待核对'*900})
        self.assertEqual(response.status_code,200)
        self.assertGreater(len(response.json()['contact']['notes']),2000)

class ContactMultiRowTests(unittest.TestCase):
    def rows(self, text):
        from backend.case_manager import split_contact_rows, validate_contact_rows
        rows, uncertain = split_contact_rows(text)
        return validate_contact_rows(text, {}, rows), uncertain

    def test_same_person_gets_one_phone_per_row(self):
        rows, uncertain = self.rows('一审 王法官 020-81234567、020-87654321、13800000001')
        self.assertFalse(uncertain)
        self.assertEqual([(r['name'], r['phone'], r['department']) for r in rows], [
            ('王法官','020-81234567','一审'),('王法官','020-87654321','一审'),('王法官','13800000001','一审')])

    def test_multiple_people_multiple_numbers_keep_relationship(self):
        rows, uncertain = self.rows('张三 13800000001、13800000002；李四 13900000003、13900000004')
        self.assertFalse(uncertain)
        self.assertEqual([(r['name'],r['phone']) for r in rows],[('张三','13800000001'),('张三','13800000002'),('李四','13900000003'),('李四','13900000004')])

    def test_procedure_and_department_both_survive(self):
        rows, _ = self.rows('一审 示例法院立案庭 王法官 020-81234567、81234568；二审 李法官 020-87654321；执行 王法官 13900000000')
        self.assertEqual([r['name'] for r in rows],['王法官','王法官','李法官','王法官'])
        self.assertIn('一审',rows[0]['department'])
        self.assertIn('立案庭',rows[0]['department'])
        self.assertIn('二审',rows[2]['department'])
        self.assertEqual('执行',rows[3]['department'])

    def test_repeated_person_and_number_remain_separate_across_procedures(self):
        rows, _ = self.rows('一审 张三 13800000001；二审 张三 13800000001')
        self.assertEqual(len(rows),2)
        self.assertEqual([r['department'] for r in rows],['一审','二审'])

    def test_unordered_lists_are_not_zipped_or_guessed(self):
        rows, uncertain = self.rows('张三、李四：13800000001、13900000002')
        self.assertTrue(uncertain)
        self.assertEqual([r['name'] for r in rows],['',''])
        self.assertEqual([r['phone'] for r in rows],['13800000001','13900000002'])
        self.assertTrue(all('归属待核对' in r['notes'] for r in rows))

    def test_postfix_names_do_not_leak_to_next_number(self):
        rows, uncertain = self.rows('020-81234567 张三；020-87654321 李四')
        self.assertFalse(uncertain)
        self.assertEqual([(r['name'],r['phone']) for r in rows],[('张三','020-81234567'),('李四','020-87654321')])

    def test_structured_row_keeps_procedure_and_notes(self):
        rows, _ = self.rows('姓名：张三\n部门：二审\n单位：示例法院\n电话：020-81234567、020-87654321\n邮箱：\n备注：仅周一联系')
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['name']=='张三' and r['department']=='二审' and '仅周一联系' in r['notes'] for r in rows))

    def test_extensions_are_one_phone_and_judicial_title_survives(self):
        rows, _ = self.rows('罗调解员 81234568转8128、81234568转8129')
        self.assertEqual([r['phone'] for r in rows],['81234568转8128','81234568转8129'])
        self.assertTrue(all(r['name']=='罗调解员' for r in rows))

    def test_new_program_without_named_owner_does_not_inherit_old_person(self):
        rows, uncertain = self.rows('一审 张三 13800000001；执行：13900000002')
        self.assertTrue(uncertain)
        self.assertEqual([r['name'] for r in rows],['张三',''])
        self.assertIn('执行',rows[1]['department'])

    def test_shared_number_uses_department_or_purpose_as_name(self):
        for label in ('缴费咨询', '立案庭'):
            rows, _ = self.rows(f'示例法院 {label} 020-81234567')
            self.assertEqual(rows[0]['name'], label)
            self.assertEqual(rows[0]['phone'], '020-81234567')

    def test_unknown_new_person_does_not_inherit_previous_name(self):
        rows, uncertain = self.rows('张三 13800000001；未具名人员 13900000002')
        self.assertTrue(uncertain)
        self.assertEqual(rows[1]['name'],'')

    def test_explicit_undelimited_judicial_name_is_supported(self):
        rows, uncertain = self.rows('一审承办人张三020-81234567；执行案经办人李四13900000000')
        self.assertFalse(uncertain)
        self.assertEqual([r['name'] for r in rows],['张三','李四'])

    def test_model_cannot_swap_owners_or_drop_numbers(self):
        from backend.case_manager import split_contact_rows, validate_contact_rows
        text='一审 张三 13800000001；二审 李四 13900000002'
        local,_=split_contact_rows(text)
        rows=validate_contact_rows(text,{'contacts':[{'name':'李四','phone':'13800000001','department':'二审'},{'name':'张三','phone':'13900000002','department':'一审'}]},local)
        self.assertEqual([(r['name'],r['phone']) for r in rows],[('张三','13800000001'),('李四','13900000002')])

    def test_explicit_respective_mapping_is_supported(self):
        rows, uncertain = self.rows('一审张三、二审李四的电话分别为13800000001、13900000002')
        self.assertFalse(uncertain)
        self.assertEqual([(r['name'],r['phone'],r['department']) for r in rows],[('张三','13800000001','一审'),('李四','13900000002','二审')])

    def test_stage_lists_without_mapping_are_marked_for_review(self):
        rows, uncertain = self.rows('一审、二审 张三 13800000001、13800000002')
        self.assertTrue(uncertain)
        self.assertTrue(all('一审' in r['department'] and '二审' in r['department'] and '审级对应关系待核对' in r['notes'] for r in rows))

    def test_model_partial_result_still_preserves_all_source_phones(self):
        from backend.case_manager import split_contact_rows, validate_contact_rows
        text='张三 13800000001、13800000002'
        local,_=split_contact_rows(text)
        rows=validate_contact_rows(text,{'contacts':[{'name':'张三','phone':'13800000001'}]},local)
        self.assertEqual([r['phone'] for r in rows],['13800000001','13800000002'])

    def test_dates_and_case_identifiers_are_not_extra_phone_rows(self):
        rows, _ = self.rows('一审 张三 13800000001 20261102核对 12345678号案件')
        self.assertEqual([r['phone'] for r in rows],['13800000001'])
        self.assertIn('20261102',rows[0]['notes'])
        self.assertIn('12345678号',rows[0]['notes'])

    def test_multiline_postfix_people_keep_their_own_numbers(self):
        rows, uncertain = self.rows('020-81234567 张三\n020-87654321 李四')
        self.assertFalse(uncertain)
        self.assertEqual([(r['name'],r['phone']) for r in rows],[('张三','020-81234567'),('李四','020-87654321')])

    def test_person_mentioned_without_a_number_stays_in_notes(self):
        rows, _ = self.rows('张三 13800000001（李四 提供，需核对）')
        self.assertEqual(rows[0]['name'],'张三')
        self.assertIn('李四',rows[0]['notes'])
        self.assertIn('需核对',rows[0]['notes'])

    def test_api_additive_array_and_legacy_first_row(self):
        client = ContactSplitRouteTests().client(fail=True)
        data=client.post('/api/case-manager/contacts/ai-split',json={'text':'一审 张三 13800000001、13800000002；二审 李四 13900000003'}).json()
        self.assertEqual(len(data['contacts']),3)
        self.assertEqual(data['contact'],data['contacts'][0])
        self.assertEqual([r['department'] for r in data['contacts']],['一审','一审','二审'])


if __name__ == "__main__":
    unittest.main()
