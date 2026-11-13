"""Run with python -m tests.article_ai_layout_browser on a machine with Playwright."""
import mimetypes
from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.test_article_ai_layout import ARTICLE, QUOTE, choice, layout_fixture


FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'
ORIGIN = 'http://127.0.0.1:17880'


def run(browser):
    with layout_fixture() as (client, connect, model, _):
        initial = [[1, 'h2'], [2, 'p'], [4, 'p'], [6, 'p']]
        retry = [[1, 'h2'], [2, 'p'], [4, 'item'], [5, 'item'], [6, 'p']]
        saved_layout = [[1, 'h2'], [2, 'p'], [3, 'item'], [4, 'item'], [5, 'p']]
        model.side_effect = [choice(initial), choice(retry), choice(saved_layout), choice(saved_layout)]
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, service_workers='block')
        page = context.new_page()

        def route_request(route):
            path = route.request.url[len(ORIGIN):].split('?')[0]
            if path == '/' or path.startswith('/static/'):
                target = FRONTEND / ('index.html' if path == '/' else path[len('/static/'):])
                if target.is_file():
                    return route.fulfill(path=target, content_type=mimetypes.guess_type(target)[0])
                return route.fulfill(status=404, body='')
            if path in {'/api/articles/1', '/api/notes/1', '/api/articles/1/layout/preview', '/api/articles/1/content'}:
                response = client.request(route.request.method, path, content=route.request.post_data,
                                          headers={'Content-Type': 'application/json'})
                return route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
            return route.fulfill(status=200, content_type='application/json', body='{}')

        page.route(ORIGIN + '/**', route_request)
        page.route('**/*', lambda route: route.fallback() if route.request.url.startswith(ORIGIN) else route.abort())
        page.goto(ORIGIN)
        verify_numbered_layout(page)
        page.evaluate("openArticleInTab(1, '匿名排版示例')")
        button = page.get_by_role('button', name='AI 排版', exact=True)
        body = page.locator('.tab-article-body-text').first
        dialog = page.get_by_role('dialog', name='AI 排版预览')
        confirm = dialog.get_by_role('button', name='确认替换正文格式')
        preview = dialog.get_by_label('排版后的正文')
        original_notes = client.get('/api/notes/1').json()
        body.locator('.note-anchor[data-note-id="1"]').wait_for()
        button.click()
        preview.locator('h2').wait_for()
        assert '本段被错误切开。' in preview.locator('p').first.inner_text()
        assert client.get('/api/articles/1').json()['content'] == ARTICLE
        assert preview.locator('table td').text_content().strip() == '原表格'
        dialog.get_by_role('button', name='重新排版').click()
        preview.locator('.body-list-item').nth(1).wait_for()
        assert preview.locator('.body-list-item').nth(1).locator('.note-anchor[data-note-id="1"]').inner_text().startswith(QUOTE)
        assert preview.locator('.body-list-item').first.locator('.note-anchor[data-note-id="1"]').count() == 0
        assert_highlights(preview)
        assert model.await_count == 2
        assert client.get('/api/articles/1').json()['content'] == ARTICLE

        # Check dialog geometry on a small dark reader before applying.
        page.set_viewport_size({'width': 420, 'height': 760})
        page.evaluate("document.body.classList.add('dark-mode')")
        assert dialog.evaluate('(el) => {const r=el.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && r.bottom<=innerHeight;}')
        confirm.click()
        dialog.wait_for(state='hidden')
        body.locator('.body-list-item').nth(1).locator('.note-anchor[data-note-id="1"]').wait_for()
        assert_highlights(body)
        assert client.get('/api/notes/1').json() == original_notes
        saved = client.get('/api/articles/1').json()['content']
        assert 'body-ai-layout' in saved and 'note-anchor' not in saved

        page.set_viewport_size({'width': 1440, 'height': 900})
        page.reload()
        page.evaluate("openArticleInTab(1, '匿名排版示例')")
        body.locator('.body-list-item').nth(1).locator('.note-anchor[data-note-id="1"]').wait_for()
        assert body.locator('h2').inner_text() == '第一部分'
        assert body.locator('.note-anchor[data-note-id="2"]').inner_text().startswith('本段被错误')
        assert_highlights(body)
        button.click()
        preview.wait_for()
        dialog.get_by_role('button', name='取消').click()
        dialog.wait_for(state='hidden')
        assert client.get('/api/articles/1').json()['content'] == saved

        button.click()
        preview.wait_for()
        concurrent = saved + '<p>其他窗口新增的文字。</p>'
        with connect() as conn:
            conn.execute('UPDATE articles SET content=? WHERE id=1', (concurrent,))
        confirm.click()
        dialog.get_by_text('正文已修改，请重新排版后再确认').wait_for()
        assert confirm.is_disabled()
        assert client.get('/api/articles/1').json()['content'] == concurrent
        assert client.get('/api/notes/1').json() == original_notes
        context.close()


def assert_highlights(root):
    highlights = root.locator('.body-list-item span[style*="background-color"]')
    assert highlights.evaluate_all('''elements => elements.map(element => {
        const clone = element.cloneNode(true);
        clone.querySelectorAll('.note-anchor-badge').forEach(node => node.remove());
        return [clone.textContent.trim(), getComputedStyle(element).backgroundColor];
    })''') == [[QUOTE, 'rgb(255, 242, 168)'], [QUOTE, 'rgb(255, 242, 168)']]


def verify_numbered_layout(page):
    html = ('<p><span><br></span></p><p>示例说明。</p>'
            '<span style="background-color:#fff2a8"><p>一、承办人员应完整记录材料。</p></span><p></p>'
            '<h2>二、下列材料应归档：</h2><p>（一）纸面记录；（二）电子记录。</p>'
            '<p>三、先核对原件；已核验的可以归档。</p><p>四、归档后及时通知。</p>'
            '<p>友情链接开始示例链接</p><p>示例网站 版权所有</p><p>End Code</p>'
            '<span>另一份文件的文字</span>')
    result = page.evaluate('''raw => {
        const source = document.createElement('div');
        source.innerHTML = articleBodyBaseHtml(raw, true);
        const originalText = normalizeNoteLocatorText(source.textContent);
        const extras = prepareArticleLayoutSource(source, true);
        const units = collectArticleLayoutRuns(source).flat();
        // Simulate a model that calls every fragment a heading and splits at
        // each semicolon. The structural corrections must still hold.
        const plan = units.map((_, index) => [index + 1, 'h2']);
        const rendered = renderBodyContentWithToc(applyArticleLayout(source, plan));
        const root = document.createElement('div');
        root.innerHTML = rendered.html;
        const texts = selector => [...root.querySelectorAll(selector)].map(node => node.textContent.trim());
        return {
            extras, intact: originalText === normalizeNoteLocatorText(root.textContent),
            clauses: texts('p.body-ai-clause'), items: texts('p.body-list-item'),
            headings: texts('h2'), toc: rendered.toc.length,
            highlighted: texts('.body-ai-clause span[style*="background-color"]'),
            footer: texts('.body-ai-extra'), tail: texts('.body-ai-extra-tail'),
            sentToModel: units.map(unit => unit.text).join(''),
        };
    }''', html)
    assert result['extras'] and result['intact']
    assert result['clauses'] == ['一、承办人员应完整记录材料。', '二、下列材料应归档：',
                                 '三、先核对原件；已核验的可以归档。', '四、归档后及时通知。']
    assert result['items'] == ['（一）纸面记录；', '（二）电子记录。']
    assert not result['headings'] and result['toc'] == 4
    assert result['highlighted'] == ['一、承办人员应完整记录材料。']
    assert result['footer'] == ['友情链接开始示例链接', '示例网站 版权所有', 'End Code', '另一份文件的文字']
    assert result['tail'] == ['另一份文件的文字'] and '友情链接' not in result['sentToModel']


if __name__ == '__main__':
    with sync_playwright() as playwright:
        with playwright.webkit.launch() as browser:
            run(browser)
    print('AI layout: preview, regenerate, confirm, reload, notes, highlight, cancel and conflict passed')
