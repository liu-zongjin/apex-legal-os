/* Anonymous regression checks; no live server or business database is used. */
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict'), acorn = require('acorn');
const { chromium, webkit } = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/case-manager.js'), 'utf8');
const declarations = acorn.parse(source, { ecmaVersion: 'latest' }).body
  .filter(node => node.type === 'FunctionDeclaration' && !['esc', 'toast', 'api'].includes(node.id.name)
    || node.type === 'VariableDeclaration' && node.declarations.some(d => d.id.name === 'CONTACT_CATEGORIES'))
  .map(node => source.slice(node.start, node.end)).join('\n');
(async () => {
  const useWebkit = process.env.STELLA_BROWSER_ENGINE === 'webkit';
  const executablePath = process.env.STELLA_BROWSER_EXECUTABLE
    || (useWebkit ? undefined : '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
  const browser = await (useWebkit ? webkit : chromium).launch({ headless: true, executablePath });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<main><div id="mount" data-case-inline-section="contacts"></div></main>');
    await page.addScriptTag({ content: `const state={};
      function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
      ${declarations}` });
    await page.evaluate(() => {
      window.series = { id: 700, profile: {
        table_columns: [{ key: 'custom_secretary', label: '秘书' }, { key: 'custom_handler', label: '秘书' }],
        detail_field_mappings: [{ source_key: 'custom_secretary', target_key: 'contacts' }, { source_key: 'custom_handler', target_key: 'contacts' }],
      }};
      window.rawChild = { id: 701, title: '示例子案', display_name: '示例子案', series_code: '001',
        court_contact: '', party_contact: '', memo: '保留备忘', custom_values: {
          custom_secretary: '示例秘书甲\n电话：020-12345678\n邮箱：a@example.com\n仅为测试',
          custom_handler: '示例秘书乙\n电话：020-87654321',
        }};
      state.seriesWorkspace = series;
      state.editing = { tab: 'cases', seriesDetailMappingSeriesId: 700, item: applySeriesDetailMappings(rawChild, series) };
      window.initialItem = JSON.stringify(state.editing.item);
      document.querySelector('#mount').innerHTML = caseContactHub(state.editing.item);
    });
    assert.deepEqual(await page.locator('.contact-name-text').allTextContents(), ['示例秘书甲', '示例秘书乙']);
    await page.evaluate(() => { document.querySelector('#mount').innerHTML = caseSectionEditorHtml('contacts', state.editing.item); });
    assert.deepEqual(await page.locator('[name=contact_name]').evaluateAll(inputs => inputs.map(input => input.value)), ['示例秘书甲', '示例秘书乙']);
    assert.deepEqual(await page.locator('[name=contact_phone]').evaluateAll(inputs => inputs.map(input => input.value)), ['020-12345678', '020-87654321']);
    assert.equal(await page.locator('[name=contact_email]').first().inputValue(), 'a@example.com');
    const ids = await page.locator('[data-contact-row]').evaluateAll(rows => rows.map(row => row.dataset.contactGroupId));
    assert.equal(new Set(ids).size, 2, 'same-label source columns need independent contact identities');
    const selection = await page.evaluate(() => readContactDisplaySelections());
    assert.deepEqual(selection, { custom_secretary: [ids[0]], custom_handler: [ids[1]] });
    // Opening and cancelling an editor must never import contacts into stored state.
    await page.locator('[name=contact_name]').first().fill('取消的修改');
    assert(await page.evaluate(() => JSON.stringify(state.editing.item) === initialItem));
    await page.evaluate(() => { document.querySelector('#mount').innerHTML = caseSectionEditorHtml('contacts', state.editing.item); });
    assert.equal(await page.locator('[name=contact_name]').first().inputValue(), '示例秘书甲');
    await page.locator('[name=contact_name]').first().fill('修改后的秘书甲');
    await page.locator('[name=contact_phone]').first().fill('020-11112222');
    await page.locator('[name=contact_notes]').first().fill('修改后的备注');
    const saved = await page.evaluate(() => {
      window.savedPayload = caseSavePayload(updatedCaseFromSection('contacts'));
      state.editing.item = applySeriesDetailMappings({ ...rawChild, ...savedPayload }, series);
      document.querySelector('#mount').innerHTML = caseContactHub(state.editing.item);
      return { payload: savedPayload, values: state.editing.item._seriesDetailDisplayValues };
    });
    assert.equal(saved.payload.memo, '保留备忘');
    assert(saved.values.custom_secretary.includes('修改后的秘书甲'));
    assert(saved.values.custom_secretary.includes('020-11112222'));
    assert(!saved.values.custom_handler.includes('修改后的秘书甲'));
    assert.deepEqual(await page.locator('.contact-name-text').allTextContents(), ['修改后的秘书甲', '示例秘书乙']);
    // A persisted/reopened child has exactly one copy of each contact.
    await page.evaluate(() => {
      state.editing.item = applySeriesDetailMappings(state.editing.item, series);
      document.querySelector('#mount').innerHTML = caseSectionEditorHtml('contacts', state.editing.item);
    });
    assert.deepEqual(await page.locator('[data-contact-row]').evaluateAll(rows => rows.map(row => row.dataset.contactGroupId)), ids);
    assert.deepEqual(await page.evaluate(() => readContactDisplaySelections()), selection);
    // Explicit deletion must suppress the legacy-cell fallback after a save/reopen.
    await page.evaluate(() => {
      document.querySelectorAll('[data-contact-row]').forEach(row => row.remove());
      const payload = caseSavePayload(updatedCaseFromSection('contacts'));
      state.editing.item = applySeriesDetailMappings({ ...rawChild, ...payload }, series);
      document.querySelector('#mount').innerHTML = caseContactHub(state.editing.item);
    });
    assert.equal(await page.locator('[data-contact-row]').count(), 0);
    // Ordinary/structured cases and explicit empty selections keep their behavior.
    await page.evaluate(() => {
      state.editing.seriesDetailMappingSeriesId = 0;
      document.querySelector('#mount').innerHTML = contactEditorHtml(savedPayload);
    });
    assert.equal(await page.locator('[data-contact-row]').count(), 2);
    assert.equal(await page.locator('[data-contact-display-column]').count(), 0);
    await page.evaluate(() => {
      state.editing.seriesDetailMappingSeriesId = 700;
      const child = applySeriesDetailMappings({ ...rawChild, detail_contact_selection: { custom_secretary: [], custom_handler: [] } }, series);
      document.querySelector('#mount').innerHTML = contactEditorHtml(child);
    });
    assert.equal(await page.locator('[name=contact_name]').first().inputValue(), '');
    // The single mapped-contact path uses the same selection as the main table.
    await page.evaluate(() => {
      const single = { ...series, profile: { ...series.profile, detail_field_mappings: series.profile.detail_field_mappings.slice(0, 1) } };
      state.seriesWorkspace = single;
      state.editing.item = applySeriesDetailMappings(rawChild, single);
      document.querySelector('#mount').innerHTML = contactEditorHtml(state.editing.item);
    });
    assert.equal(await page.locator('[name=contact_name]').first().inputValue(), '示例秘书甲');
    assert.equal(await page.locator('[data-contact-display-column]:checked').count(), 1);
    assert.deepEqual(errors, []);
    console.log('Series contact editor: mapped names/phones/email/notes, distinct source selections, cancel, edit/save/reopen, no duplicates, delete and ordinary-case compatibility passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
