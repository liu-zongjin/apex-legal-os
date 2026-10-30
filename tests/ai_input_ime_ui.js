const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const src = fs.readFileSync('frontend/app.js', 'utf8');
function extract(name) {
  const m = new RegExp('^function '+name+'\\(', 'm').exec(src); assert(m, name);
  const rest = src.slice(m.index), next = /\n(?:async )?function [\w]+\(/g; next.lastIndex = 1;
  const end = next.exec(rest), decl = /\n(?:const|let|var|class) \w/.exec(rest);
  return rest.slice(0, Math.min(end ? end.index : rest.length, decl ? decl.index : rest.length));
}
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.STELLA_UI_BROWSER || 'chrome'});
  const page = await browser.newPage();
  await page.setContent('<textarea id="ask-input"></textarea>');
  await page.addScriptTag({content: `let askInputComposing=false, askInputCompositionEndedAt=-Infinity;let sends=0;function sendAskQuestion(){sends++}\n` + ['onAskInputCompositionStart','onAskInputCompositionEnd','onAskInputKeydown'].map(extract).join('\n')});
  await page.evaluate(() => {const input=document.querySelector('#ask-input');input.addEventListener('compositionstart',onAskInputCompositionStart);input.addEventListener('compositionend',onAskInputCompositionEnd);input.addEventListener('keydown',onAskInputKeydown)});
  const run = await page.evaluate(async () => {
    const input=document.querySelector('#ask-input');
    const key=(options={})=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...options}));
    input.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
    const during=key({isComposing:true});
    input.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));
    const commit=key();
    await new Promise(r=>setTimeout(r,100));
    const legacy = new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true});Object.defineProperty(legacy,'keyCode',{value:229});const legacyAllowed=input.dispatchEvent(legacy);
    const shift=key({shiftKey:true});const enter=key();
    return {during,commit,legacyAllowed,shift,enter,sends};
  });
  assert.deepStrictEqual(run,{during:true,commit:true,legacyAllowed:true,shift:true,enter:false,sends:1});
  await browser.close(); console.log('IME composition and normal Enter handling passed.');
})().catch(e=>{console.error(e);process.exit(1)});
