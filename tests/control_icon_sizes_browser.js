/* Anonymous production markup: popup dismissal glyphs and dynamic tag candidates. */
const fs = require('fs'), path = require('path'), assert = require('assert'), acorn = require('acorn');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
function markup(file) {
  return read(file).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<link\b[^>]*href=["']([^"']+)["'][^>]*>/gi, (_, url) => {
      let name = path.basename(url.split('?')[0]);
      if (name === 'style.min.css') name = 'style.css';
      const file = path.join(root, 'frontend', name);
      return name.endsWith('.css') && fs.existsSync(file) ? `<style>${fs.readFileSync(file, 'utf8')}</style>` : '';
    });
}
(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CASE_ENTRY_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.abort());
    const source = read('frontend/app.js');
    const declarations = acorn.parse(source, {ecmaVersion: 'latest'}).body.filter(node =>
      (node.type === 'VariableDeclaration' && node.declarations[0].id.name === 'SIDEBAR_ICONS') ||
      (node.type === 'FunctionDeclaration' && node.id.name === 'renderTagSuggestions'))
      .map(node => source.slice(node.start, node.end)).join('\n');
    for (const width of [1440, 1024, 390]) for (const dark of [false, true]) {
      await page.setViewportSize({width, height: 900});
      for (const [file, selector] of [
        ['index.html', '#edit-tags-modal .btn-icon, #domain-classification-modal .btn-icon, .relations-close'],
        ['knowledge-expand.html', '.modal-close, .drawer-close, .digest-fullscreen-close'],
        ['case-manager.html', '.mobile-record-action-close'],
      ]) {
        await page.goto('about:blank');
        await page.setContent(markup('frontend/' + file));
        await page.addStyleTag({content: '* { animation: none !important; transition: none !important; }'});
        await page.evaluate(dark => {
          document.body.classList.toggle('dark-mode', dark);
          document.documentElement.classList.toggle('dark-mode', dark);
        }, dark);
        const buttons = await page.locator(selector).evaluateAll(nodes => nodes.map(node => {
          for (let parent = node; parent && parent !== document.body; parent = parent.parentElement) {
            if (getComputedStyle(parent).display === 'none') parent.style.setProperty('display', 'block', 'important');
            parent.style.transform = 'none';
          }
          const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
          return {label: node.getAttribute('aria-label') || node.className,
            font: parseFloat(style.fontSize), width: rect.width, height: rect.height};
        }));
        assert(buttons.length, `${file}: missing fixture controls`);
        for (const button of buttons) {
          assert(button.font >= 20 && button.font <= 26, `${file}: small dismissal glyph ${JSON.stringify(button)}`);
          assert(button.width >= 30 && button.height >= 30, `${file}: small dismissal target ${JSON.stringify(button)}`);
        }
        if (file === 'index.html') {
          await page.addScriptTag({content: declarations + `
            const $=id=>document.getElementById(id), currentEditingTags=[];
            let _tagSuggestIndex=-1;
            function escapeHtml(text){const span=document.createElement('span');span.textContent=text;return span.innerHTML;}
            renderTagSuggestions(['匿名测试标签','另一个标签']);
          `});
          const sizes = await page.locator('.tag-suggest-item > svg').evaluateAll(nodes => nodes.map(svg => {
            for (let parent=svg.parentElement;parent && parent!==document.body;parent=parent.parentElement) {
              if(getComputedStyle(parent).display==='none')parent.style.setProperty('display','block','important');
              parent.style.transform='none';
            }
            const rect=svg.getBoundingClientRect();return {width:rect.width,height:rect.height};
          }));
          assert.equal(sizes.length, 2);
          for(const size of sizes) assert(size.width === 14 && size.height === 14, `Unbounded candidate icon: ${JSON.stringify(size)}`);
          if (width === 1440 && !dark) {
            await page.evaluate(() => {
              document.querySelectorAll('.modal-overlay').forEach(node => node.style.setProperty('display', 'none', 'important'));
              const modal = document.getElementById('edit-tags-modal');
              modal.style.setProperty('display', 'flex', 'important');
              modal.classList.add('open');
              document.getElementById('new-tag-input').value = '匿名';
            });
            fs.mkdirSync(path.join(root, '.tmp'), {recursive: true});
            await page.screenshot({path: path.join(root, '.tmp/frequent-workflows-tag-controls.png')});
          }
        }
      }
    }
    console.log('Control icon sizes: 3 pages × 3 widths × light/dark passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
