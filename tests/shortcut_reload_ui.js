const fs = require('fs'), path = require('path'), assert = require('assert'), acorn = require('acorn');
const {chromium,webkit} = require(process.env.STELLA_PLAYWRIGHT_MODULE || 'playwright');
const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'),'utf8');
const ast = acorn.parse(source, {ecmaVersion:'latest'});
const get = name => {const node=ast.body.find(n=>n.type==='FunctionDeclaration' && n.id.name===name);assert(node,name);return source.slice(node.start,node.end)};
const nativeStart=source.indexOf('window.stellaHandleNativeReloadShortcut = function () {');
const nativeEnd=source.indexOf('\n};',nativeStart)+3;
assert(nativeStart>=0 && nativeEnd>nativeStart);
(async()=>{
 for(const [name,engine,options] of [['chromium',chromium,{executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true}],['webkit',webkit,{headless:true}]]) {
  const browser=await engine.launch(options);
  try {
   const page=await browser.newPage(); await page.route('http://shortcuts.test/',route=>route.fulfill({status:200,body:'<html></html>'})); await page.goto('http://shortcuts.test/');
   await page.setContent(`<button id="outside">outside</button><input id="editing"><script>
   let bindings={r:{actionId:'all',modifiers:['alt']}}; let triggered=0; let shortcutBulkFrom='alt',shortcutBulkTo='meta'; const SHORTCUT_BINDINGS_KEY='bindings';
   function loadShortcutBindings(){return bindings} function renderShortcutKeyboard(){} function renderShortcutEditor(){} function getShortcutActions(){return [{id:'all',run(){triggered++}}]} function closeSettingsModal(){}
   ${['isShortcutEditableTarget','isInsideAskPanelEditableTarget','shortcutKeyFromEvent','handleCustomShortcutEvent','isReservedShortcut','replaceShortcutModifiers'].map(get).join('\n')}
   ${source.slice(nativeStart,nativeEnd)}
   </script><span id="shortcut-bulk-status"></span>`);
   await page.evaluate(()=>replaceShortcutModifiers());
   assert.deepEqual(await page.evaluate(()=>bindings.r.modifiers),['meta']);
   assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('bindings')).r.actionId),'all');
   await page.locator('#outside').focus();
   assert.equal(await page.evaluate(()=>window.stellaHandleNativeReloadShortcut()),true);
   await page.waitForFunction(()=>triggered===1);
   assert.equal(await page.evaluate(()=>{const event=new KeyboardEvent('keydown',{key:'r',code:'KeyR',metaKey:true,cancelable:true,bubbles:true}); document.addEventListener('keydown',handleCustomShortcutEvent,{once:true}); document.getElementById('outside').dispatchEvent(event); return event.defaultPrevented}),true);
   await page.waitForFunction(()=>triggered===2);
   await page.locator('#editing').focus(); assert.equal(await page.evaluate(()=>window.stellaHandleNativeReloadShortcut()),false);
   await page.evaluate(()=>{bindings={}}); await page.locator('#outside').focus(); assert.equal(await page.evaluate(()=>window.stellaHandleNativeReloadShortcut()),false);
   assert.equal(await page.evaluate(()=>isReservedShortcut('r',['meta','alt'])),true);
   assert.equal(await page.evaluate(()=>isReservedShortcut('r',['meta'])),false);
   console.log(`${name}: replacement, dispatch, editing and reload fallback passed`);
  } finally {await browser.close()}
 }
})().catch(error=>{console.error(error);process.exitCode=1});
