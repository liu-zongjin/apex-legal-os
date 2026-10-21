"""Browser geometry regression for the article editor (anonymous HTML only).

python3 tests/article_editor_pagination_browser.py --browser chromium --executable /path/to/chrome
python3 tests/article_editor_pagination_browser.py --browser webkit --executable /path/to/pw_run.sh
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'frontend/app.js').read_text()
CSS = (ROOT / 'frontend/style.css').read_text()
PAGINATOR = SOURCE[SOURCE.index('function _updateBodyEditorPagination()'):SOURCE.index('async function exportBodyAsWord()')]
SERIALIZERS = SOURCE[SOURCE.index('function _bodyEditorContentHtml()'):SOURCE.index('function _readStoredBodyEditorPageSettings()')]

CHECK = """() => {
 const editor=$('body-editor'), origin=editor.getBoundingClientRect().top;
 const cycle=1137, topMargin=_bodyEditorMargins.top*96/2.54, bottomMargin=_bodyEditorMargins.bottom*96/2.54;
 const bad=[]; const check=(rect,label)=>{
   if(!rect.height||!rect.width)return;
   const top=rect.top-origin,bottom=rect.bottom-origin,index=Math.floor(top/cycle);
   if(top<index*cycle+topMargin-1||bottom>index*cycle+1123-bottomMargin+1)bad.push({label,top,bottom});
 };
 const walker=document.createTreeWalker(editor,NodeFilter.SHOW_TEXT);let node;
 while(node=walker.nextNode()){
   if(!node.textContent.trim())continue;
   const range=document.createRange();range.selectNodeContents(node);
   for(const rect of range.getClientRects())check(rect,node.textContent.slice(0,20));
 }
 editor.querySelectorAll('img').forEach(el=>check(el.getBoundingClientRect(),el.tagName));
 return {mode:_bodyEditorPageMode,bad,pages:$('body-editor-page-numbers').querySelectorAll('span').length,
   html:_bodyEditorContentHtml(),text:editor.textContent,
   spacers:editor.querySelectorAll('.body-editor-page-break-spacer').length};
}"""


def paginate(page):
    return page.evaluate("""async () => {
      const started=performance.now();
      _updateBodyEditorPagination();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      return performance.now()-started;
    }""")


def run(browser):
    page=browser.new_page(viewport={'width':1440,'height':900})
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content('<style>'+CSS+'</style><div class="body-editor-modal"><div id="content-editor-wrapper" style="height:800px;overflow:auto"><div class="body-editor-page"><div id="body-editor" class="body-editor tab-article-body-text" contenteditable="true"></div><div id="body-editor-page-numbers" class="body-editor-page-numbers"></div></div></div></div>')
    page.add_script_tag(content="""
      const $=id=>document.getElementById(id);
      let _bodyEditorPaginationFrame=0,_bodyEditorComposing=false,_bodyEditorSavedRange=null,_bodyEditorRecordSession=null;
      function _syncBodyEditorPageSettingsUi(){}
      const BODY_EDITOR_PAGE_GEOMETRY={height:1123,gap:14,pxPerCm:96/2.54};
      let _bodyEditorMargins={top:2.54,bottom:2.54,left:2.6,right:2.6},_bodyEditorPageMode='paged';
    """+SERIALIZERS+PAGINATOR)
    phrase='这是匿名测试正文，检查页边距及文字完整性。'
    cases={
        'short': '<p>短文章</p>',
        'record_four_pages': '<p>匿名案件记录</p><ol class="legal-outline-list"><li data-list-level="1" data-list-label="一、">争议与证据</li></ol>'+''.join('<p%s>%s</p>' % (' class="body-document-meta"' if i==1 else '', (phrase*(size//len(phrase)+1))[:size]) for i,size in enumerate([66,224,52,403,65,10,457,14,113,30,26,28,12,64,10,84,10,129,70,195])),
        'case_collection': ''.join('<h2>案例%d</h2><p>%s</p>' % (i, phrase*30) for i in range(10)),
        'long_paragraph_followed_by_short': '<p>'+phrase*220+'</p>'+('<p>'+phrase*3+'</p>')*30,
        'inline_formats': '<p>'+('<strong>'+phrase*12+'</strong><em>'+phrase*9+'</em>')*20+'</p>',
        'nested_list': '<ol><li>'+phrase*150+'<ol><li>'+phrase*100+'</li></ol></li><li>'+phrase*100+'</li></ol>',
        'nested_blocks': '<div><blockquote><div>'+phrase*150+'</div><p>'+phrase*90+'</p></blockquote></div>',
        'table': '<p>'+phrase*28+'</p><table>'+''.join('<tr><td>%s</td><td>%s</td></tr>' % (phrase*2,phrase*3) for _ in range(80))+'</table>',
        'oversized_table_row': '<table><tr><td>'+phrase*150+'</td><td>'+phrase*180+'</td></tr><tr><td>末行</td><td>末行</td></tr></table>',
        'image': '<p>'+phrase*35+'<img width="550" height="850" src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22550%22 height=%22850%22/%3E">'+phrase*50+'</p>',
        'mixed_sizes': ''.join('<p style="font-size:%dpx;line-height:1.7">%s</p>' % (size,phrase*15) for size in [12,24,15,32]*10),
    }
    for name,html in cases.items():
        page.evaluate("html=>{$('body-editor').innerHTML=html;_bodyEditorPageMode='paged';}",html)
        original=page.evaluate('_bodyEditorContentHtml()')
        elapsed=paginate(page)
        result=page.evaluate(CHECK)
        assert elapsed<1200,(name,'pagination blocked UI',elapsed)
        if result['mode']=='continuous':
            assert result['spacers']==0 and result['html']==original,(name,'fallback must preserve content')
            print(name+': responsive continuous fallback (%d ms)' % elapsed)
            continue
        assert not result['bad'], (name,result['bad'][:5])
        assert result['html']==original, (name,'pagination changed saved HTML')
        pages=result['pages']
        assert pages>=1
        paginate(page)
        repeated=page.evaluate(CHECK)
        assert repeated['pages']==pages and not repeated['bad'], (name,'unstable second pass',repeated['bad'][:5])
        assert repeated['html']==original
        if name=='record_four_pages':
            # Simulate WebKit's viewport anchoring during a spacer insertion.
            page.evaluate("""() => {
              const host=$('content-editor-wrapper');host.scrollTop=800;
              const original=Node.prototype.insertBefore;
              window.restoreInsertion=()=>{Node.prototype.insertBefore=original;};
              let shifted=false;
              Node.prototype.insertBefore=function(child,before){const result=original.call(this,child,before);if(!shifted&&child.classList?.contains('body-editor-page-break-spacer')){shifted=true;host.scrollTop+=120;}return result;};
            }""")
            elapsed=paginate(page)
            page.evaluate('restoreInsertion()')
            shifted=page.evaluate(CHECK)
            assert elapsed<1200 and not shifted['bad'] and shifted['html']==original, ('viewport origin changed during layout',shifted['bad'][:3])
        print(name+': OK (%d pages)' % pages)
    page.evaluate("html=>{$('body-editor').innerHTML=html;_bodyEditorPageMode='paged';}",cases['case_collection'])
    page.evaluate("window.realNow=performance.now.bind(performance);let tick=0;performance.now=()=>{tick+=200;return tick;}")
    paginate(page)
    page.evaluate('performance.now=realNow')
    bounded=page.evaluate(CHECK)
    assert bounded['mode']=='continuous' and bounded['spacers']==0
    # Preserve a backward selection across text-node splitting and mode changes.
    page.evaluate("html=>{$('body-editor').innerHTML=html;_bodyEditorPageMode='paged';}",cases['short']+'<p>末段测试文字与定位以及双向选区</p>')
    paginate(page)
    before=page.evaluate("""() => {const e=$('body-editor');e.focus();const w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),a=w.nextNode(),b=w.nextNode();getSelection().setBaseAndExtent(b,10,a,3);return getSelection().toString();}""")
    paginate(page)
    assert page.evaluate('getSelection().toString()')==before
    page.evaluate("_bodyEditorPageMode='continuous'")
    paginate(page)
    result=page.evaluate(CHECK)
    assert result['pages']==0 and result['spacers']==0
    assert page.evaluate('getSelection().toString()')==before
    page.evaluate("_bodyEditorPageMode='paged';_bodyEditorComposing=true")
    paginate(page)
    assert page.evaluate(CHECK)['spacers']==0
    page.evaluate('_bodyEditorComposing=false')
    paginate(page)
    assert not page.evaluate(CHECK)['bad']
    # Empty paragraphs and paragraph starts must remain distinct caret positions.
    page.evaluate("""() => {$('body-editor').innerHTML='<p>前段</p><p><br></p><p>后段</p>';$('body-editor').focus();getSelection().setBaseAndExtent($('body-editor').children[1],0,$('body-editor').children[1],0);}""")
    paginate(page)
    assert page.evaluate("getSelection().anchorNode===$('body-editor').children[1]")
    page.evaluate("""() => {const text=$('body-editor').lastElementChild.firstChild;getSelection().setBaseAndExtent(text,0,text,0);}""")
    paginate(page)
    assert page.evaluate("getSelection().anchorNode.parentElement===$('body-editor').lastElementChild")
    page.evaluate("html=>{$('body-editor').innerHTML=html;}",cases['mixed_sizes'])
    # Narrow paper, changed margins and dark appearance use the same geometry.
    page.evaluate("""() => {document.body.classList.add('dark-mode');document.querySelector('.body-editor-page').style.width='620px';_bodyEditorMargins={top:4,bottom:3,left:3,right:3};for(const side of ['top','bottom','left','right'])document.querySelector('.body-editor-page').style.setProperty('--editor-margin-'+side,(_bodyEditorMargins[side]*96/2.54)+'px');}""")
    paginate(page)
    assert not page.evaluate(CHECK)['bad']
    assert not errors,errors
    print('selection, composition, mode switching, width, margins, dark appearance: OK')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--executable')
    args=parser.parse_args()
    with sync_playwright() as playwright:
        options={'headless':True}
        if args.executable: options['executable_path']=args.executable
        browser=getattr(playwright,args.browser).launch(**options)
        try: run(browser)
        finally: browser.close()
