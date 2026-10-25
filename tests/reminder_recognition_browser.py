"""Anonymous real-browser coverage for selection handoff and reminder drawers."""
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'frontend/app.js').read_text()
INIT = APP[APP.index('function initOpenPagesOverview()'):APP.index('function getCaseManagerTabForMessageSource')]
HANDOFF = APP[APP.index('function openSelectionReminderRecognition('):APP.index('function openCaseManagerTab(')]
STUBS = '''
const TAB_TYPES = new Proxy({}, {get: (_, key) => key});
const tabState = {tabs: [], activeTabId: ''};
const openPagesOverviewKeyState = {};
const $ = id => document.getElementById(id);
function renderOpenPagesCommandSideSetting() {}
function handleCustomShortcutEvent() { return false; }
function resetOpenPagesCommandState() {}
function cancelPendingOpenPagesCommand() {}
function showToast(text) { window.lastToast = text; }
function openCaseManagerTab() {
  const id = 'case-' + (tabState.tabs.length + 1);
  tabState.tabs.push({id, type: TAB_TYPES.CASE_MANAGER}); tabState.activeTabId = id;
  document.querySelectorAll('.tab-page').forEach(page => page.style.display = 'none');
  const page = document.createElement('div'); page.id = id; page.className = 'tab-page active'; page.dataset.tabId = id;
  const frame = document.createElement('iframe'); frame.style = 'width:100%;height:850px;border:0';
  frame.src = '/case-manager?workspace_id=' + id; page.append(frame); document.body.append(page);
}
'''


def run(engine="chromium"):
    import sys
    sys.path.insert(0, str(ROOT))
    from tests.test_standalone_todos import TodoFixture
    todos = TodoFixture()
    requests, errors = [], []
    sample = '请于2026年10月29日09时30分提交会议签字页。'
    def route_handler(route):
        req = route.request
        path = unquote(urlsplit(req.url).path)
        if path.startswith('/static/'):
            file = ROOT / 'frontend' / path[len('/static/'):]
            if file.is_file():
                mime = 'text/javascript' if file.suffix == '.js' else 'text/css' if file.suffix == '.css' else 'application/octet-stream'
                route.fulfill(path=str(file), content_type=mime)
            else:
                route.fulfill(status=404, body='')
        elif path == '/case-manager':
            route.fulfill(path=str(ROOT / 'frontend/case-manager.html'), content_type='text/html; charset=utf-8')
        elif path == '/api/case-manager/todos':
            response = todos.client.request(req.method, req.url, content=req.post_data_buffer, headers={'Content-Type':'application/json'})
            route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
        elif path.startswith('/api/'):
            if path.endswith('/recognize'):
                requests.append((path, req.post_data_buffer.decode(errors='replace')))
                kind = path.split('/')[-2]
                item = {'title':'匿名案件', 'case_id':1, 'todo_title':'提交会议签字页', 'remind_at':'2026-10-29 09:30',
                        'recurrence':'weekly', 'appeal_type':'上诉', 'start_at':'2026-10-25', 'period_days':15,
                        'deadline_at':'', 'case_no':'（2026）测试1号', 'court':'匿名法院', 'notes':'待核对',
                        'hearing_at':'2026-10-29 09:30', 'reminder_type':'一审开庭', 'location':'第一法庭',
                        'preservation_type':'银行存款', 'asset_content':'匿名账户', 'period_years':1}
                if kind == 'todos':
                    item['case_id'] = None
                    item['title'] = ''
                data = {'ok':True,'item':item,'ai':{'used':True,'model':'fixture'},'matched_case':{'title':'匿名案件'},'files':[]}
            elif path == '/api/pwa/session-status':
                data = {'server_reachable':True,'authenticated':True,'shell_version':'283'}
            elif path.endswith('/offline-snapshot'):
                data = {'version':1, 'cases':[], 'todos':[], 'hearings':[], 'preservations':[], 'appeals':[]}
            else:
                data = {'items':[], 'counts':{}, 'ok':True}
            route.fulfill(json=data)
        else:
            route.fulfill(content_type='text/html; charset=utf-8', body='<meta charset="utf-8"><div id="open-pages-overview"></div><p id="source">'+sample+'</p><textarea id="input">'+sample+'</textarea><div class="tab-page" id="mail-host"><iframe id="mail"></iframe></div>')
    with sync_playwright() as p:
        if engine == 'webkit':
            browser = p.webkit.launch(headless=True)
        else:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True, channel='chrome')
        context = browser.new_context(viewport={'width':1440,'height':900}, user_agent='LegalKB-NativeShell Fixture', service_workers='block', reduced_motion='reduce')
        context.route('**/*', route_handler)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://stella.test/')
        assert page.locator('#source').inner_text() == sample
        page.add_script_tag(content=STUBS + INIT + HANDOFF + '\ninitOpenPagesOverview();')
        def context_menu(locator, position=None):
            if engine == 'webkit':
                bounds = locator.bounding_box()
                viewport = page.viewport_size
                point = {'x': (bounds['x'] + (position or {}).get('x', 5)) / viewport['width'],
                         'y': (bounds['y'] + (position or {}).get('y', 5)) / viewport['height']}
                assert page.evaluate('(p) => window.apexOpenSelectionMenuAtPoint(p.x, p.y)', point)
            else:
                locator.click(button='right', position=position)

        # Native handoff must fall back when there is no selection or the point
        # hits a password input, without touching the user's existing menus.
        assert page.evaluate('window.apexOpenSelectionMenuAtPoint(0.9, 0.9)') is False
        # Dynamically inserted nested sandboxed mail body uses the same bridge.
        page.evaluate('''() => {
          const mail = document.getElementById('mail');
          mail.srcdoc = '<div id="body"></div>';
        }''')
        mail = page.frame_locator('#mail')
        mail.locator('#body').wait_for(state='attached')
        mail.locator('#body').evaluate("el => { const child = document.createElement('iframe'); child.id='body-frame'; child.sandbox='allow-same-origin allow-popups'; child.srcdoc='<p id=selection>邮件中的待办通知</p>'; el.append(child); }")
        nested = mail.frame_locator('#body-frame')
        nested.locator('#selection').wait_for()
        assert not page.evaluate('window.mailInjected || 0')
        assert nested.locator('script,iframe,[onclick]').count() == 0
        nested.locator('#selection').evaluate("el => {const range=document.createRange();range.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(range);}")
        context_menu(nested.locator('#selection'))
        menu_scope = page if engine == 'webkit' else nested
        menu_scope.get_by_role('menuitem',name='AI 智能识别新增待办事项',exact=True).wait_for()
        menu_scope.get_by_role('menuitem',name='AI 智能识别新增待办事项',exact=True).click()
        frame = page.frame_locator('#case-1 > iframe')
        frame.locator('#reminderNoticeResult').filter(has_text='识别完成').wait_for()
        assert frame.locator('[name=todo_title]').input_value() == '提交会议签字页'
        assert '邮件中的待办通知' in requests[-1][1]
        assert frame.locator('[name=remind_at]').input_value() == '2026-10-29T09:30'
        assert frame.locator('[name=case_id]').input_value() == ''
        frame.get_by_role('button',name='保存',exact=True).click()
        frame.locator('#drawer.show').wait_for(state='hidden')
        frame.locator('tr',has_text='提交会议签字页').first.wait_for()
        saved = todos.client.get('/api/case-manager/todos').json()['items'][0]
        assert saved['todo_title'] == '提交会议签字页' and saved['case_id'] is None
        assert todos.scope['calendar_item']('todo',saved['id']) is not None
        with todos.get_db() as db:
            assert db.execute('SELECT COUNT(*) FROM case_manager_cases').fetchone()[0] == 1

        # Every selected-text destination opens a separate unsaved draft.
        for kind, label, text_id in [('hearings','开庭提醒','hearingNoticeText'),('preservations','财产保全','preservationNoticeText'),('appeals','上诉/异议期','reminderNoticeText')]:
            page.locator('#source').evaluate("el => {const range=document.createRange();range.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(range);}")
            context_menu(page.locator('#source'))
            page.get_by_role('menuitem',name='AI 智能识别新增'+label,exact=True).click()
            count = len(requests) + 1
            target = page.frame_locator(f'#case-{count} > iframe')
            target.locator('#'+text_id).wait_for()
            page.wait_for_function('(count) => document.querySelectorAll(".tab-page.active iframe").length >= count', arg=count)
            # Wait for actual network request / UI completion, not only the drawer.
            target.get_by_text('识别完成', exact=False).last.wait_for()
            assert requests[-1][0].endswith('/'+kind+'/recognize'), requests
            assert sample in requests[-1][1], requests[-1]
        # Input selection uses its selected substring rather than window Selection.
        page.locator('#input').evaluate('el => {el.focus();el.setSelectionRange(0,3)}')
        context_menu(page.locator('#input'), {'x':10,'y':10})
        page.get_by_role('menuitem',name='AI 智能识别新增待办事项',exact=True).wait_for()
        page.keyboard.press('Escape')
        assert page.locator('.stella-page-context-menu').count() == 0
        # An in-flight todo response cannot overwrite another drawer.
        last = page.frame_locator('#case-4 > iframe')
        last.locator('body').evaluate('''async () => {
          await openEditor('todos');
          window.originalRecognitionApi = api;
          api = (url, options) => url.endsWith('/recognize')
            ? new Promise(resolve => { window.finishRecognition = resolve; })
            : window.originalRecognitionApi(url, options);
          $('reminderNoticeText').value = '未完成的识别';
          window.pendingRecognition = recognizeReminderNotice('todos');
          closeEditor();
          await openEditor('appeals');
          setNamedValue('appeal_type', '人工核对');
          window.finishRecognition({item:{todo_title:'迟到的旧结果',appeal_type:'错误覆盖'},ai:{used:true}});
          await window.pendingRecognition;
          api = window.originalRecognitionApi;
        }''')
        assert last.locator('[name=appeal_type]').input_value() == '人工核对'
        # Opening another drawer of the same kind while court options load must
        # not receive the first handoff's source text or start its AI request.
        last.locator('body').evaluate('''async () => {
          const originalLoadCourts = loadCourts;
          let count = 0, release;
          loadCourts = () => ++count === 1 ? new Promise(resolve => { release = resolve; }) : Promise.resolve();
          const first = window.openSelectedTextRecognition('appeals', '原始选区通知');
          await openEditor('appeals');
          $('reminderNoticeText').value = '用户的新草稿';
          release();
          await first;
          loadCourts = originalLoadCourts;
        }''')
        assert last.locator('#reminderNoticeText').input_value() == '用户的新草稿'
        output = ROOT / '.tmp/reminder-recognition-review'
        output.mkdir(parents=True,exist_ok=True)
        for width,height in [(1440,900),(1024,768)]:
            page.set_viewport_size({'width':width,'height':height})
            for dark in (False,True):
                page.frame_locator('#case-4 > iframe').locator('body').evaluate('(el,dark) => applyCaseManagerTheme(dark)', dark)
                last.locator('#drawer').evaluate('el => { el.style.transition="none"; }')
                page.screenshot(path=str(output/f'appeals-{width}-{"dark" if dark else "light"}.png'))
        assert len(requests) == 4, requests
        assert not errors, errors
        print(f'PASS ({engine}): nested mail selection, four automatic recognition handoffs, input selection, Escape, late-result isolation, anonymous light/dark layouts')
        browser.close()
        todos.close()

if __name__ == '__main__':
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else "chromium")
