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
                page.locator('#agentModelLabel').filter(has_text='匿名演示模型').wait_for()
                page.locator('#submit').click()
                assert '请先添加材料' in page.locator('#toast').inner_text()
                frame = page.frame_locator('#filePicker')
                frame.locator('.file-row').filter(has_text='01_合同.pdf').click()
                frame.locator('#archiveAssignBtn').click()
                page.locator('#sources .source-row').wait_for()
                page.locator('#agentAdvanced > summary').click()
                page.locator('#agentProjectMenu summary').click()
                page.locator('[data-agent-project="1"]').click()
                page.locator('#agentGoal').fill('匿名任务：核对合同与付款情况')
                page.locator('#submit').click()
                page.locator('#agentDetail h2').filter(has_text='已交付').wait_for(timeout=20000)
                assert '关键事项与缺口' in page.locator('#agentDetail').inner_text()
                assert not page.locator('#inputStage').get_attribute('open')
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
