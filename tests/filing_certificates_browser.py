"""Anonymous browser checks for filing certificate selection and draft repair."""
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run():
    certificate = {"name": "执业证.pdf", "path": "/anonymous/certificate.pdf", "category": "lawyer_certificate", "label": "律师执业证", "destination": "代理材料", "persistent": True, "agent_name": "示例律师", "readable": True, "selected": False}
    task = {"id": 1, "status": "api_service_address_generated", "folder_path": "/anonymous/网上立案", "facts": {"api_draft_id": "anonymous-draft", "representation_mode": "unknown"}, "materials": [certificate], "events": [], "warnings": [], "ai": {}}
    calls = []
    def route(request):
        path = urlparse(request.request.url).path
        if path.startswith('/api/'):
            calls.append((request.request.method, path))
            if path.endswith('/reference-data'):
                value = {"agents": [{"name": "示例律师", "document_number": "990000199001010050", "practice_number": "14400000000000000", "law_firm": "示例律师事务所"}]}
            elif path.endswith('/confirm'):
                body = request.request.post_data_json
                task['facts'].update(body['facts'])
                task['materials'] = body['materials']
                value = task
            elif '/api-execute/' in path:
                value = task
            elif path.endswith('/execution-status'):
                value = {"phase": "complete", "is_running": False, "steps": []}
            elif path.endswith('/official-check'):
                value = {"party_count": 0, "expected_party_count": 0, "agent_count": 1, "expected_agent_count": 1, "material_count": 1, "expected_material_count": 1, "service_address_generated": True}
            elif path.endswith('/jobs/latest'):
                value = {"job": None}
            elif path.endswith('/jobs'):
                value = {"jobs": []}
            elif path.endswith('/jobs/1') or path.endswith('/reclassify-materials'):
                value = task
            elif path.endswith('/lawyer-certificates'):
                value = {"items": []}
            else:
                value = {}
            request.fulfill(content_type='application/json', body=json.dumps(value))
            return
        asset = ROOT / 'frontend' / ('automation-filing.html' if path == '/' else (path[len('/static/'):] if path.startswith('/static/') else path.lstrip('/')))
        if asset.is_file():
            request.fulfill(path=str(asset))
        else:
            request.fulfill(status=404, body='')
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('http://filing.test/**', route)
        page.goto('http://filing.test/')
        page.wait_for_function("typeof render === 'function'")
        page.evaluate('(task) => { job=task; apiExecutionSnapshot=null; render(); }', task)
        page.locator('[data-agent-profile]').first.select_option('示例律师')
        assert page.locator('#representationMode').input_value() == 'lawyer_agent'
        assert page.locator('[data-material="0"]').is_checked()
        page.locator('#caseName').fill('保留未保存修改')
        page.evaluate('refreshCertificateMaterials()')
        assert page.locator('#caseName').input_value() == '保留未保存修改'
        assert page.locator('[data-material="0"]').is_checked()
        assert page.locator('#syncAgentBtn').is_visible()
        for width, height in [(1440, 900), (1024, 768)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ['light', 'dark']:
                page.emulate_media(color_scheme=theme)
                page.locator('#syncAgentBtn').scroll_into_view_if_needed()
                assert page.locator('#syncAgentBtn').bounding_box()['width'] > 0
        assert not [path for method, path in calls if method == 'POST' and '/api-execute/' in path]
        page.evaluate('syncAgentMaterials()')
        writes = [path for method, path in calls if method == 'POST']
        assert writes[-3:] == ['/api/automated-filing/jobs/1/confirm', '/api/automated-filing/jobs/1/api-execute/materials', '/api/automated-filing/jobs/1/api-execute/agent'], writes
        assert task['facts']['representation_mode'] == 'lawyer_agent'
        assert task['materials'][0]['selected']
        assert page.locator('#syncAgentBtn').is_enabled()
        assert page.locator('#goSubmitBtn').is_visible()
        assert not errors, errors
        browser.close()
    print('PASS: profile mode, certificate selection, upload refresh, preserved edits, draft repair entry and four viewport/theme combinations')


if __name__ == '__main__':
    run()
