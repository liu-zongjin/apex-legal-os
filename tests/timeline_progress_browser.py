"""Exercise timeline progress against a disposable server and anonymous jobs."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stella-timeline-progress-') as temporary:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        server = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts/case_workflow_preview.py'), '--port', str(port), '--runtime', temporary],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        base = f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + '/case-workflows', timeout=1).close()
                    break
                except Exception:
                    time.sleep(.1)
            else:
                raise RuntimeError('fixture server did not start')

            long_path = '匿名材料/2025年诉讼材料/' + '超长文件名称用于验证完整路径显示' * 5 + '.pdf'
            job = {
                'id': 'anonymous-progress', 'kind': 'timeline', 'status': 'running', 'progress': 5,
                'message': f'读取材料 1/11：{long_path}', 'created_at': '2026-11-29T02:40:17+08:00',
                'sources': [{'path': f'匿名材料/{index}.pdf'} for index in range(11)],
                'revision': 1, 'timeline_events': [], 'timeline_issues': [], 'results': [],
                'steps': [{'at': '2026-11-29T02:40:17+08:00', 'message': '核对原件版本'},
                          {'at': '2026-11-29T02:40:18+08:00', 'message': f'读取材料 1/11：{long_path}'}],
                'artifacts': [], 'versions': [], 'export_options': {'style': 'axis', 'include_evidence': True},
            }
            requests = {'polls': 0, 'cancel': 0, 'resume': 0}

            def tasks(route):
                requests['polls'] += 1
                route.fulfill(json={'items': [copy.deepcopy(job)]})

            def auto(route):
                route.fulfill(json={'job': copy.deepcopy(job), 'scan': {}, 'created': False,
                                    'party_sides': {}, 'party_subjects': {}, 'word_locations': {}})

            def cancel(route):
                requests['cancel'] += 1
                job.update(status='cancelled', message='任务已停止；可继续办理。')
                route.fulfill(json=copy.deepcopy(job))

            def resume(route):
                requests['resume'] += 1
                job.update(status='running', message='核对原件版本', progress=2)
                route.fulfill(json=copy.deepcopy(job))

            with sync_playwright() as playwright:
                engine = playwright.webkit if os.environ.get('STELLA_TEST_WEBKIT') == '1' else playwright.chromium
                try:
                    browser = engine.launch(headless=True)
                except Exception:
                    if engine == playwright.webkit:
                        raise
                    browser = engine.launch(headless=True, channel='chrome')
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/api/case-workflows/cases/1/tasks', tasks)
                page.route('**/api/case-workflows/cases/1/timeline-auto', auto)
                page.route('**/api/case-workflows/cases/1/tasks/anonymous-progress/cancel', cancel)
                page.route('**/api/case-workflows/cases/1/tasks/anonymous-progress/resume', resume)
                page.goto(base + '/case-workflows?case_id=1')
                page.locator('.timeline-progress-card').wait_for()
                page.locator('.summary-generation-glow.is-visible').wait_for()
                assert page.locator('#timelineProgressMessage').inner_text() == '读取材料 1/11'
                assert page.locator('#timelineProgressFile').inner_text() == long_path
                assert page.locator('#timelineProgressPercent').inner_text() == '5%'
                assert page.locator('#timelineProgressSources').inner_text() == '11'
                assert page.locator('#timelineProgressEvents').inner_text() == '0'
                assert page.locator('#timelineProgressBar').get_attribute('value') == '5'

                # Polling updates actual status without restarting animation or collapsing steps.
                page.locator('.timeline-progress-steps > summary').click()
                page.evaluate('window.originalTimelineGlow = document.querySelector(".summary-generation-glow")')
                job.update(message='提取事件片段 2/8', progress=42, timeline_events=[{'id': 'checkpoint'}])
                job['steps'].append({'at': '2026-11-29T02:41:00+08:00', 'message': job['message']})
                page.wait_for_function("document.querySelector('#timelineProgressPercent').textContent === '42%'")
                assert page.evaluate('window.originalTimelineGlow === document.querySelector(".summary-generation-glow")')
                assert page.locator('.timeline-progress-steps').get_attribute('open') is not None
                assert page.locator('#timelineProgressEvents').inner_text() == '1'
                assert page.locator('#timelineProgressFile').is_hidden()
                assert '提取事件片段 2/8' in page.locator('#timelineProgressSteps').inner_text()

                # Review responsive light/dark layouts with a long, unbroken filename.
                job.update(message=f'读取材料 1/11：{long_path}', progress=5)
                page.locator('#refresh').click()
                page.wait_for_function("document.querySelector('#timelineProgressPercent').textContent === '5%'")
                page.locator('.timeline-progress-steps > summary').click()
                for width, height in [(1440, 900), (1024, 768), (390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    for dark in (False, True):
                        page.evaluate('dark => { document.documentElement.classList.toggle("dark-mode", dark); document.documentElement.dataset.theme = dark ? "dark" : "light"; }', dark)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        assert page.locator('#cancelJob').is_visible()
                        assert page.locator('#timelineProgressFile').inner_text() == long_path
                        progress_box = page.locator('.timeline-progress-card').bounding_box()
                        history_box = page.locator('.history-panel').bounding_box()
                        assert abs(progress_box['x'] - history_box['x']) < 1
                        assert abs(progress_box['width'] - history_box['width']) < 1
                        page.screenshot(path=str(output / f'progress-{width}-{"dark" if dark else "light"}.png'), full_page=True)

                # Hidden tabs release the canvas, stop polling and recreate only one glow on return.
                page.set_viewport_size({'width': 1440, 'height': 900})
                page.evaluate("window.postMessage({type:'apex:page-visibility',version:1,active:false}, location.origin)")
                page.locator('.summary-generation-glow').wait_for(state='detached')
                polls = requests['polls']
                page.wait_for_timeout(1800)
                assert requests['polls'] == polls
                page.evaluate("window.postMessage({type:'apex:page-visibility',version:1,active:true}, location.origin)")
                page.locator('.summary-generation-glow.is-visible').wait_for()
                assert page.locator('.summary-generation-glow').count() == 1

                page.locator('#cancelJob').click()
                page.locator('#resumeJob').wait_for(state='visible')
                assert page.locator('#resumeJob').is_enabled()
                assert page.locator('#timelineProgressStatus').inner_text() == '已停止'
                assert page.locator('#timelineProgressGlow').is_hidden()
                page.locator('#resumeJob').click()
                page.locator('#cancelJob').wait_for(state='visible')
                assert page.locator('#cancelJob').is_enabled()
                page.locator('.summary-generation-glow.is-visible').wait_for()
                assert requests['cancel'] == requests['resume'] == 1

                # Other workbench modes must not reveal the background timeline on a poll.
                page.locator('#factMode').click()
                page.locator('#detailPanel').wait_for(state='hidden')
                page.locator('.summary-generation-glow').wait_for(state='detached')
                page.wait_for_timeout(1800)
                assert page.locator('#detailPanel').is_hidden()
                page.locator('#timelineMode').click()
                page.locator('.summary-generation-glow.is-visible').wait_for()

                job.update(status='queued', message='等待办理', progress=0)
                page.locator('#refresh').click()
                page.wait_for_function("document.querySelector('#timelineProgressStatus').textContent === '排队中'")
                assert page.locator('#timelineProgressPercent').inner_text() == '0%'
                assert page.locator('.summary-glow-text').inner_text() == '等待任务开始…'
                job.update(status='failed', message='匿名测试：材料无法读取')
                page.locator('#refresh').click()
                page.locator('#resumeJob').wait_for(state='visible')
                assert page.locator('#timelineProgressMessage').inner_text() == '匿名测试：材料无法读取'
                assert page.locator('#timelineProgressGlow').is_hidden()
                page.locator('#resumeJob').click()
                page.locator('.summary-generation-glow.is-visible').wait_for()
                assert requests['resume'] == 2

                # Completion uses the existing exit transition before revealing the timeline.
                job.update(status='completed', message='时间轴已生成，请核对日期、事件及原文。',
                           progress=100, timeline_events=[])
                page.locator('#refresh').click()
                page.locator('.summary-generation-glow.is-finishing').wait_for()
                page.locator('.timeline-workbench').wait_for()
                assert page.locator('.timeline-progress-card').count() == 0
                assert page.locator('#timelineDelivery').count() == 1

                # Reduced motion uses the same state without spinning or canvas animation.
                job.update(status='running', message='核对原件版本', progress=2)
                page.emulate_media(reduced_motion='reduce')
                page.reload()
                page.locator('.summary-generation-glow.is-visible').wait_for()
                assert page.locator('.summary-glow-text').evaluate('(el) => getComputedStyle(el).animationName') == 'none'
                assert page.locator('#timelineProgressPercent').inner_text() == '2%'
                page.screenshot(path=str(output / 'progress-reduced-motion.png'), full_page=True)

                # Reduced-motion completion also reveals the existing timeline workbench.
                job.update(status='completed', message='时间轴已生成，请核对日期、事件及原文。',
                           progress=100, timeline_events=[])
                page.locator('#refresh').click()
                page.locator('.timeline-workbench').wait_for()
                assert page.locator('.timeline-progress-card').count() == 0
                assert page.locator('#timelineDelivery').count() == 1
                assert not errors, errors
                browser.close()
            print('Timeline progress browser checks passed:', output)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(tempfile.gettempdir()) / 'stella-timeline-progress-qa')
    run(parser.parse_args().output)
