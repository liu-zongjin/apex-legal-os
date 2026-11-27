"""Check the Windows workspace using a real WebView2 page or Chromium with a stubbed bridge."""
import argparse
import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'
ORIGIN = 'http://127.0.0.1:18865'
BRIDGE = """window.updateChecks = 0;
window.StellaWindows = {invoke: async (name) => {
  if (name === 'check_stella_update') { window.updateChecks++; throw Error('offline fixture'); }
  return {allowed: true};
}};"""


def fixture_page(browser):
    page = browser.new_page(service_workers='block', viewport={'width': 1280, 'height': 740})
    page.add_init_script(BRIDGE)

    def fulfill(route):
        url = urlparse(route.request.url)
        if f'{url.scheme}://{url.netloc}' != ORIGIN:
            return route.abort()
        path = url.path
        if path.startswith('/api/'):
            responses = {
                '/api/platform-capabilities': {'platform': 'windows'},
                '/api/stats': {'total': 0, 'url_count': 0, 'file_count': 0},
                '/api/articles': {'articles': [], 'total': 0, 'page': 1, 'page_size': 20},
            }
            return route.fulfill(json=responses.get(path, {}))
        path = 'index.html' if path == '/' else path.lstrip('/')
        if path.startswith('static/'):
            path = path[len('static/'):]
        target = FRONTEND / path
        if target.is_file():
            return route.fulfill(path=target, content_type=mimetypes.guess_type(target)[0])
        route.abort()

    page.route('**/*', fulfill)
    page.goto(ORIGIN)
    return page


def check_workspace(page, output=None):
    page.locator('html.stella-windows').wait_for(state='attached')
    page.locator('#stella-windows-update-btn').wait_for()
    page.locator('#stella-windows-statistics-settings').wait_for(state='attached')
    assert page.locator('.tab-bar-actions').get_by_role('button', name='使用统计').count() == 0
    page.add_style_tag(content='*,*::before,*::after{transition:none!important;animation:none!important}')
    page.evaluate("document.body.classList.remove('sidebar-collapsed')")
    session = page.context.new_cdp_session(page)
    for width, height, scale in ((1440, 850, 1), (1280, 760, 1.25), (1181, 680, 1.5),
                                 (900, 650, 1.5), (761, 600, 1.75), (700, 560, 2), (640, 500, 2)):
        session.send('Emulation.setDeviceMetricsOverride', {
            'width': width, 'height': height, 'deviceScaleFactor': scale, 'mobile': False,
        })
        page.wait_for_function('width => innerWidth === width', arg=width)
        for dark in (False, True):
            page.evaluate("dark => document.body.classList.toggle('dark-mode',dark)", dark)
            page.evaluate('goToMainView()')
            failures = page.evaluate("""() => {
              const grid = document.querySelector('.kb-home-grid').getBoundingClientRect();
              const overflow = el => el.right > document.documentElement.clientWidth + 2 || el.left < -2;
              const selectors = ['.tab-bar-actions', '#stella-windows-update-btn',
                '#tab-page-main > .topbar .search-bar', '#tab-page-main > .topbar .topbar-right',
                '.kb-home-hero', '.kb-home-side', '.kb-reminder-center'];
              const failures = selectors.filter(sel => overflow(document.querySelector(sel).getBoundingClientRect()));
              for (const card of document.querySelectorAll('.kb-home-grid > .kb-home-card')) {
                if (card.getBoundingClientRect().right > grid.right + 2) failures.push(card.className);
              }
              for (const button of document.querySelectorAll('.tab-bar-actions > button')) {
                if (button.scrollWidth > button.clientWidth + 2) failures.push(button.id);
              }
              return failures;
            }""")
            assert not failures, (width, height, scale, dark, failures)
            if output and (width, dark) in [(1280, False), (761, True)]:
                shot = session.send('Page.captureScreenshot', {'captureBeyondViewport': False})
                filename = f'windows-home-{width}-{"dark" if dark else "light"}.png'
                (output / filename).write_bytes(base64.b64decode(shot['data']))
            for mode, opening in (
                ('ai_ask', 'askContext = null; openAskPanel()'),
                ('case_ai', 'openCaseAiPanel()'),
            ):
                page.evaluate(opening)
                page.wait_for_function(
                    'mode => tabState.tabs.some(tab => tab.id === tabState.activeTabId && tab.type === mode)',
                    arg=mode,
                )
                page.locator('#ask-input').wait_for()
                failures = page.evaluate("""() => ['#ask-panel', '#ask-input', '#ask-send-btn'].filter(sel => {
                  const r = document.querySelector(sel).getBoundingClientRect();
                  return r.width <= 0 || r.left < -2 || r.right > document.documentElement.clientWidth + 2;
                })""")
                assert not failures, (opening, width, dark, failures)
                page.evaluate('closeAskPanel();goToMainView()')
    session.send('Emulation.clearDeviceMetricsOverride')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    parser.add_argument('--cdp')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        if args.cdp:
            browser = p.chromium.connect_over_cdp(args.cdp)
            page = next(page for context in browser.contexts for page in context.pages if page.url.startswith(ORIGIN))
        else:
            browser = p.chromium.launch(executable_path=args.browser)
            page = fixture_page(browser)
        check_workspace(page, args.output)
        if not args.cdp:
            update = page.get_by_role('button', name='重试检查更新')
            update.wait_for()
            assert page.evaluate('window.updateChecks') == 1
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            assert page.evaluate('window.updateChecks') == 1
            update.press('Enter')
            page.wait_for_function('window.updateChecks === 2')
            browser.close()
    print('Windows workspace: viewport, DPI, light/dark, AI and case AI passed')


if __name__ == '__main__':
    main()
