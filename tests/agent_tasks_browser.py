"""End-to-end workbench checks against an anonymous disposable server."""
import argparse
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]



def recovery_scenarios(page, base):
    """Hold real anonymous responses to exercise out-of-order reads and controls."""
    from copy import deepcopy
    first, second = [next(item for item in page.request.get(base + '/api/agent-tasks/cases/1/tasks').json()['items']
                          if item['goal'].startswith(prefix))
                     for prefix in ('匿名任务：', '匿名校验纠正：')]
    detail_url = lambda item: base + '/api/agent-tasks/cases/1/tasks/' + item['id']
    originals = {item['id']: page.request.get(detail_url(item)).json() for item in (first, second)}

    def open_records():
        if page.locator('#agentRecords').get_attribute('open') is None:
            page.locator('#agentRecords > summary').click()

    def choose(item):
        open_records()
        page.locator(f'[data-agent-task="{item["id"]}"]').click()

    def goal(value):
        page.wait_for_function('value=>document.querySelector(".agent-goal")?.textContent===value', arg=value)

    choose(second)
    goal(second['goal'])
    held = []
    hold = lambda route: held.append(route)
    page.route(detail_url(first), hold)
    choose(first)
    page.wait_for_function('document.querySelector("[data-agent-copy]").disabled')
    assert page.locator('.agent-goal').inner_text() == second['goal']
    # A faster second selection must win, even when the first response arrives later.
    choose(second)
    page.wait_for_function('!document.querySelector("[data-agent-copy]").disabled')
    assert held
    held.pop().fulfill(json=originals[first['id']])
    page.wait_for_timeout(100)
    assert page.locator('.agent-goal').inner_text() == second['goal']
    # Starting a new analysis cancels an outstanding history selection.
    choose(first)
    page.wait_for_function('document.querySelector("[data-agent-copy]").disabled')
    page.locator('#agentNew').click()
    assert held
    held.pop().fulfill(json=originals[first['id']])
    page.wait_for_timeout(100)
    assert page.locator('#inputStage').get_attribute('open') is not None
    assert page.locator('.agent-goal').inner_text() == second['goal']
    page.unroute(detail_url(first), hold)

    fail = lambda route: route.fulfill(status=503, json={'detail': '匿名临时读取失败'})
    page.route(detail_url(first), fail)
    choose(first)
    page.wait_for_function('document.getElementById("agentMessage").textContent.includes("匿名临时读取失败")')
    assert page.locator('[data-agent-copy]').is_enabled()
    assert page.locator('.agent-goal').inner_text() == second['goal']
    page.unroute(detail_url(first), fail)

    # Reading history remains possible when model configuration is temporarily unavailable.
    page.route(base + '/api/agent-tasks/models', fail)
    page.reload()
    page.locator('#agentDetail h2').filter(has_text='已交付').wait_for()
    assert page.locator('.agent-goal').inner_text() == second['goal']
    page.unroute(base + '/api/agent-tasks/models', fail)
    page.locator('#refresh').click()
    page.locator('#agentModelLabel').filter(has_text='匿名演示模型').wait_for(state='attached')

    reads = []
    running = deepcopy(originals[second['id']])
    running.update(status='running', message='匿名办理进度')
    def polling(route):
        reads.append(route)
        if len(reads) == 2:
            route.fulfill(status=503, json={'detail': '匿名临时轮询失败'})
        else:
            route.fulfill(json=running)
    page.route(detail_url(second), polling)
    choose(second)
    page.locator('[data-agent-action="pause"]').wait_for()
    for selector in ('.agent-audit', '.agent-evidence'):
        detail = page.locator(selector).first
        if detail.get_attribute('open') is None:
            detail.locator(':scope > summary').click()
    # Wait across a failed poll and the next successful poll, without a manual refresh.
    page.wait_for_function('document.getElementById("agentMessage").textContent.includes("匿名临时轮询失败")', timeout=10000)
    page.wait_for_timeout(3400)
    assert len(reads) >= 3
    assert "匿名临时轮询失败" not in page.locator("#agentMessage").inner_text()
    assert page.locator('.agent-audit').get_attribute('open') is not None
    assert page.locator('.agent-evidence').first.get_attribute('open') is not None

    page.locator('#agentNew').click()
    page.locator('#agentGoal').fill('未提交的匿名分析目标')
    page.locator('#draftOptions > summary').click()
    page.locator('#draft').fill('补充说明：乙方否认已经收取价款。')
    assert '补充文字' in page.locator('#sourceCount').inner_text()
    page.wait_for_timeout(3400)
    assert page.locator('#inputStage').is_visible()
    assert not page.locator('#agentPanel').is_visible()
    assert page.locator('#agentGoal').input_value() == '未提交的匿名分析目标'
    page.locator('#agentBack').click()
    assert page.locator('#agentPanel').is_visible()
    assert not page.locator('#inputStage').is_visible()
    created = page.request.post(base + '/api/agent-tasks/cases/2/tasks', data={
        'request_key': 'anonymous-other-case-20261025', 'paths': [], 'draft': '2026年1月1日，乙方否认已经收取价款10000元。',
        'goal': '另案独立分析', 'model': 'fixture-model'}).json()
    for _ in range(100):
        other = page.request.get(base + '/api/agent-tasks/cases/2/tasks/' + created['id']).json()
        if other['status'] == 'succeeded':
            break
        time.sleep(.03)
    else:
        raise AssertionError(other)
    controls = []
    control_hold = lambda route: controls.append(route)
    page.route(detail_url(second) + '/pause', control_hold)
    page.locator('[data-agent-action="pause"]').click()
    page.wait_for_function('document.querySelector("[data-agent-action=pause]").disabled')
    page.locator('#caseSearch').fill('另案演示')
    page.locator('#caseResults [role="option"]').filter(has_text='另案演示').click()
    assert controls
    paused = {**running, 'status': 'paused', 'generation': running['generation'] + 1}
    controls.pop().fulfill(json=paused)
    goal('另案独立分析')
    assert page.locator('[data-agent-copy]').is_enabled()
    assert page.locator('#caseSearch').input_value() == '另案演示（匿名）'
    page.unroute(detail_url(second) + '/pause', control_hold)
    page.unroute(detail_url(second), polling)
    page.locator('#caseSearch').fill('匿名合同')
    page.locator('#caseResults [role="option"]').filter(has_text='匿名合同纠纷').click()
    goal(second['goal'])
    choose(first)
    goal(first['goal'])
    # A control response from material mode must not change the next workflow's form.
    paused_first = {**originals[first['id']], 'status': 'paused'}
    show_paused = lambda route: route.fulfill(json=paused_first)
    page.route(detail_url(first), show_paused)
    choose(first)
    page.locator('[data-agent-action="resume"]').wait_for()
    resume_responses = []
    hold_resume = lambda route: resume_responses.append(route)
    page.route(detail_url(first) + '/resume', hold_resume)
    page.locator('[data-agent-action="resume"]').click()
    page.locator('#timelineMode').click()
    assert resume_responses
    resume_responses.pop().fulfill(json=originals[first['id']])
    page.wait_for_timeout(100)
    assert not page.locator('body').evaluate('el=>el.classList.contains("reviewing-result")')
    assert page.locator('#inputStage').is_visible()
    assert page.locator('#inputStage').get_attribute('open') is not None
    page.unroute(detail_url(first), show_paused)
    page.unroute(detail_url(first) + '/resume', hold_resume)
    page.locator('#agentMode').click()
    goal(first['goal'])
    page.locator('#agentDetail h2').filter(has_text='已交付').wait_for()


def run(output, engine="chromium"):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stella-agent-browser-') as temporary:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/case_workflow_preview.py'),
                                    '--port', str(port), '--runtime', temporary], cwd=ROOT,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            base = f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + '/case-workflows', timeout=1).close()
                    break
                except Exception:
                    time.sleep(.1)
            else:
                raise RuntimeError('anonymous fixture server did not start')
            with sync_playwright() as playwright:
                try:
                    browser = getattr(playwright, engine).launch(headless=True)
                except Exception:
                    if engine != 'chromium':
                        raise
                    browser = playwright.chromium.launch(headless=True, channel='chrome')
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/case-workflows?case_id=1&mode=tasks')
                page.locator('#agentModelLabel').filter(has_text='匿名演示模型').wait_for(state='attached')
                page.locator('#submit').click()
                assert '请先添加材料' in page.locator('#toast').inner_text()
                page.locator('#toast').wait_for(state='hidden')
                assert page.locator('#inputStage').is_visible()
                assert not page.locator('#agentPanel').is_visible()
                assert page.locator('#sourceSection #draftOptions').count() == 1
                assert page.locator('.case-bar .segmented button').evaluate_all('(items)=>items.map(item=>item.id)') == ['agentMode','timelineMode','knowledgeMode','factMode','bookMode']
                assert page.locator('.analysis-empty').is_visible()
                assert page.locator('#sourceCount').inner_text() == '0 份文件'
                for dark in (False, True):
                    page.evaluate('(dark)=>{document.documentElement.classList.toggle("dark-mode",dark);document.documentElement.dataset.theme=dark?"dark":"light"}', dark)
                    page.evaluate('window.scrollTo(0,0)')
                    page.wait_for_timeout(250)
                    page.screenshot(path=str(output / f'agent-compose-{engine}-{"dark" if dark else "light"}.png'), full_page=True)
                page.evaluate('document.documentElement.classList.remove("dark-mode");document.documentElement.dataset.theme="light"')
                frame = page.frame_locator('#filePicker')
                frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                frame.locator('#archiveAssignBtn').click()
                page.locator('#sources .source-row').wait_for()
                page.locator('#agentAdvanced > summary').click()
                page.locator('#agentProjectMenu summary').click()
                page.locator('[data-agent-project="1"]').click()
                page.locator('#agentGoal').fill('匿名任务：核对合同与付款情况')
                # Submission errors must be visible while the result panel is hidden.
                failed_submissions = []
                task_url = base + '/api/agent-tasks/cases/1/tasks'
                def reject_submission(route):
                    if route.request.method == 'POST':
                        failed_submissions.append(route)
                        route.fulfill(status=503, json={'detail': '匿名交办暂不可用，请重试'})
                    else:
                        route.continue_()
                page.route(task_url, reject_submission)
                page.locator('#submit').click()
                page.locator('#agentMessage').filter(has_text='匿名交办暂不可用').wait_for(state='visible')
                page.wait_for_function('!document.getElementById("submit").disabled')
                assert page.locator('#analysisActions #agentMessage').count() == 1
                assert page.locator('#agentMessage').evaluate('el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}')
                page.screenshot(path=str(output / f'agent-submit-error-{engine}.png'))
                assert len(failed_submissions) == 1
                assert page.locator('#inputStage').is_visible()
                assert not page.locator('#agentPanel').is_visible()
                assert page.locator('#agentGoal').input_value() == '匿名任务：核对合同与付款情况'
                assert page.locator('#sources .source-row').count() == 1
                page.unroute(task_url, reject_submission)
                page.locator('#submit').click()
                page.locator('#agentDetail h2').filter(has_text='已交付').wait_for(timeout=20000)
                assert '关键事项与缺口' in page.locator('#agentDetail').inner_text()
                assert not page.locator('#inputStage').get_attribute('open')
                assert not page.locator('#inputStage').is_visible()
                assert page.locator('#agentPanel').is_visible()
                assert not page.locator('.history-panel').is_visible()
                assert not page.locator('.agent-evidence .quote').first.is_visible()
                assert not page.locator('.agent-audit').get_attribute('open')
                page.locator('.agent-audit > summary').click()
                assert '2/40' in page.locator('#agentDetail').inner_text()
                page.locator('.agent-audit > summary').click()
                page.locator('.agent-evidence > summary').first.click()
                assert page.locator('.agent-evidence .quote').first.is_visible()
                page.locator('.agent-evidence > summary').first.click()
                page.locator('[data-agent-view="statement"]').click()
                assert '材料要点' in page.locator('.agent-findings h3').inner_text()
                page.locator('[data-agent-view="timeline"]').click()
                assert '时间线' in page.locator('.agent-findings h3').inner_text()
                page.locator('[data-agent-view="focus"]').click()
                if page.locator('[data-agent-more]').count():
                    before = page.locator('.agent-findings .agent-item').count()
                    page.locator('[data-agent-more]').click()
                    assert page.locator('.agent-findings .agent-item').count() > before
                assert page.locator('#agentDetail .downloads a').count() >= 3
                assert page.locator('#agentDetail .agent-reference a').first.get_attribute('href').startswith('/api/case-workflows/cases/1/tasks/')
                with page.expect_download() as event:
                    page.locator('#agentDetail .downloads a').filter(has_text='材料分析草稿.docx').click()
                download = event.value
                assert download.suggested_filename == '材料分析草稿.docx'
                download.save_as(str(output / download.suggested_filename))
                page.evaluate("localStorage.setItem('stella-agent-selected-1','missing-task')")
                page.reload()
                page.wait_for_function("document.getElementById('agentMode').getAttribute('aria-pressed')==='true'")
                page.locator('#agentDetail h2').filter(has_text='已交付').wait_for()
                assert page.locator('#agentHistory [data-agent-task]').count() == 1
                page.locator('[data-agent-copy]').click()
                assert page.locator('#agentGoal').input_value() == '匿名任务：核对合同与付款情况'
                page.locator('#agentGoal').fill('匿名校验纠正：核对付款情况')
                page.locator('#submit').click()
                page.locator('#agentDetail h2').filter(has_text='已交付').wait_for(timeout=20000)
                page.wait_for_function("document.getElementById('agentDetail').textContent.includes('3/40')")
                page.locator('.agent-audit > summary').click()
                assert '纠正记录已保留' in page.locator('#agentDetail').inner_text()
                page.locator('.agent-audit > summary').click()
                assert page.locator('#agentHistory [data-agent-task]').count() == 2
                page.locator('#agentRecords > summary').click()
                page.locator('#agentHistory [data-agent-task]').last.click()
                page.wait_for_function("document.getElementById('agentDetail').textContent.includes('2/40')")
                assert not page.locator('#agentRecords').get_attribute('open')
                recovery_scenarios(page, base)
                for width, height in [(1440, 900), (1024, 768), (390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    for dark in (False, True):
                        page.evaluate('(dark)=>{document.documentElement.classList.toggle("dark-mode",dark);document.documentElement.dataset.theme=dark?"dark":"light"}', dark)
                        page.evaluate('window.scrollTo(0,0)')
                        page.wait_for_timeout(250)  # Let the 180ms theme/button transition settle.
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        page.screenshot(path=str(output / f'agent-task-{engine}-{width}-{"dark" if dark else "light"}.png'), full_page=True)
                page.set_viewport_size({'width':1440,'height':900})
                page.locator('#agentNew').click()
                assert page.locator('#inputStage').get_attribute('open') is not None
                assert page.locator('#agentGoal').is_visible()
                page.evaluate('window.scrollTo(0,0)')
                page.wait_for_timeout(250)  # Let the 180ms theme/button transition settle.
                page.screenshot(path=str(output / f'agent-input-{engine}.png'), full_page=True)
                page.evaluate("window.postMessage({type:'apex:page-visibility',version:1,active:false},location.origin)")
                assert not errors, errors
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.returncode not in (0, -15):
                raise RuntimeError(process.stderr.read().decode()[-4000:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--engine', choices=['chromium', 'webkit'], default='chromium')
    args = parser.parse_args()
    run(args.output, args.engine)
    print('Anonymous material-task browser checks passed')
