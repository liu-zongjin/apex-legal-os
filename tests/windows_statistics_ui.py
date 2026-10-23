"""Native bridge consent UI regression; never sends real metrics."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'frontend/apex-windows-statistics.js').read_text()
MOCK = '''window.calls=[];window.preference=null;window.fail=false;window.StellaWindows={invoke:async(name,args)=>{
window.calls.push([name,args.allowed]);if(window.fail)throw new Error('fake');
if(args.allowed!==null)window.preference=args.allowed;return {allowed:window.preference,interval_seconds:21600};}};'''
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--browser');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
        page=browser.new_page(viewport={'width':1024,'height':768})
        page.set_content('<div class="tab-bar-actions"></div>');page.add_script_tag(content=MOCK);page.add_script_tag(content=SCRIPT)
        dialog=page.get_by_role('dialog');dialog.wait_for();assert '每六小时最多一次' in dialog.inner_text()
        assert page.evaluate('window.calls')==[['windows_statistics',None]]
        page.get_by_role('button',name='不允许',exact=True).click();dialog.wait_for(state='detached');assert page.evaluate('window.preference') is False
        page.get_by_role('button',name='匿名统计',exact=True).click();dialog.wait_for();assert '当前：已关闭' in dialog.inner_text()
        page.keyboard.press('Tab');assert page.get_by_role('button',name='允许匿名统计').evaluate('(el)=>el===document.activeElement')
        page.get_by_role('button',name='允许匿名统计').click();dialog.wait_for(state='detached');assert page.evaluate('window.preference') is True
        page.get_by_role('button',name='匿名统计',exact=True).click();dialog.wait_for();assert '当前：已开启' in dialog.inner_text()
        page.evaluate('window.fail=true');page.get_by_role('button',name='不允许',exact=True).click();page.get_by_text('设置未能保存，请重试。').wait_for()
        page.evaluate('window.fail=false');page.get_by_role('button',name='不允许',exact=True).click();dialog.wait_for(state='detached')
        page.evaluate("window.dispatchEvent(new Event('stella:windows-ready'))");assert page.get_by_role('button',name='匿名统计',exact=True).count()==1
        # Load actual shared styles and review both themes without real server or data.

        for css in ('style.css', 'apex-design-tokens.css', 'apex-system-messages.css', 'apex-appearance.css'):
            page.add_style_tag(path=str(ROOT/'frontend'/css))
        page.get_by_role('button',name='匿名统计',exact=True).click();dialog.wait_for()
        for theme in ('light','dark'):
            page.emulate_media(color_scheme=theme);page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            page.screenshot(path=str(args.output/f'windows-statistics-{theme}.png'))
        other=browser.new_page();other.set_content('<div class="tab-bar-actions"></div>');other.add_script_tag(content=SCRIPT)
        assert other.locator('button').count()==0
        browser.close()
    print('Windows consent UI: passed')
if __name__=='__main__':main()
