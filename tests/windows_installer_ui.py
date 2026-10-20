"""Browser-only UI regression with a fake native bridge; not Windows installation proof."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
MOCK = '''window.__TAURI__={event:{listen:async(name,handler)=>{window.onInstallEvent=handler}},core:{invoke:async(name)=>{
 if(name==='inspect_installation')return {supported:true,installed:false};
 if(name==='installation_plan')return {version:'0.1.0',download_bytes:360000000,required_free_bytes:1500000000,components:[{id:'server',bytes:140000000,reuse:false},{id:'browser',bytes:100000000,reuse:false},{id:'ocr',bytes:40000000,reuse:false},{id:'converter',bytes:80000000,reuse:false}]};
 if(name==='install_components'){window.onInstallEvent({payload:{event:'progress',component:'browser',received:50000000,total:100000000}});return {event:'installed'};}
 if(name==='start_stella'){window.testLaunched=true;return;}
}}};'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser', default=None)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({'executable_path':args.browser} if args.browser else {}))
        page = browser.new_page(viewport={'width':840,'height':660})
        page.add_init_script(MOCK)
        page.goto((ROOT/'windows-installer/ui/index.html').as_uri())
        page.get_by_role('button', name='安装并准备组件').wait_for()
        assert page.locator('#components li').count() == 4
        assert '360.0 MB' in page.locator('#size').inner_text()
        page.screenshot(path=str(args.output/'installer-light.png'), full_page=True)
        page.emulate_media(color_scheme='dark')
        page.screenshot(path=str(args.output/'installer-dark.png'), full_page=True)
        page.get_by_role('button', name='安装并准备组件').click()
        page.get_by_role('button', name='打开 Stella').wait_for()
        page.get_by_role('button', name='打开 Stella').click()
        assert page.evaluate('window.testLaunched')
        browser.close()
    print('Installer UI passed: plan, component list, size, light/dark, install and launch (mock native bridge)')


if __name__ == '__main__': main()
