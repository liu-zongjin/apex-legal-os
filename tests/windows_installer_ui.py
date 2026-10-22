"""Browser-only UI regression with a fake native bridge; not Windows installation proof."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
MOCK = '''window.testCalls=[];window.testListeners=0;window.__TAURI__={event:{listen:async(name,handler)=>{window.testListeners++;window.onInstallEvent=handler}},core:{invoke:async(name)=>{
 window.testCalls.push(name);
 if(name==='inspect_installation'){
   if(window.testProbeFailures>0){window.testProbeFailures--;throw new Error('temporary probe failure');}
   return {supported:window.testSupported!==false,installed:!!window.testInstalled};
 }
 if(name==='installation_plan')return {version:'0.1.0',download_bytes:360000000,required_free_bytes:1500000000,components:[{id:'server',bytes:140000000,reuse:false},{id:'browser',bytes:100000000,reuse:false},{id:'ocr',bytes:40000000,reuse:false},{id:'converter',bytes:80000000,reuse:false}]};
 if(name==='install_components'){if(window.testHoldInstallation)await new Promise(resolve=>window.testFinishInstall=resolve);window.onInstallEvent({payload:{event:'progress',component:'browser',received:50000000,total:100000000,speed_bytes_per_second:2000000,elapsed_seconds:10}});return {event:'installed'};}
 if(name==='start_stella'){window.onInstallEvent({payload:{event:'phase',phase:'launch_service'}});if(window.testLaunchFailure)throw new Error('启动未完成，请重试');window.testLaunched=true;return;}
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
        # Real progress is byte/file based; waiting never creates a looping progress bar.
        flow = browser.new_page(viewport={'width':1024,'height':768})
        flow.add_init_script('window.testHoldInstallation=true;' + MOCK)
        flow.goto((ROOT/'windows-installer/ui/index.html').as_uri())
        flow.get_by_role('button', name='安装并准备组件').click()
        assert flow.locator('#progress').is_hidden()
        def event(payload): flow.evaluate('(payload)=>window.onInstallEvent({payload})', payload)
        event({'event':'progress','component':'browser','received':50000000,'total':100000000,
               'speed_bytes_per_second':2000000,'elapsed_seconds':10,'source':'download.example.test'})
        assert flow.locator('#progress').get_attribute('value') == '50'
        assert abs(float(flow.locator('#overall-progress').get_attribute('value')) - 50/360*100) < 0.01
        assert '2.0 MB/s' in flow.locator('#transfer').inner_text()
        assert '全部下载预计剩余 3 分钟' in flow.locator('#transfer').inner_text()
        assert flow.locator('#stage-download').get_attribute('aria-current') == 'step'
        flow.screenshot(path=str(args.output/'installer-download.png'), full_page=True)
        event({'event':'download_complete','component':'browser','total':100000000})
        event({'event':'verification','component':'browser','phase':'verify_extract','checked':20,'total':100,
               'received':200000000,'expanded_bytes':400000000,'elapsed_seconds':10,'eta_seconds':10})
        assert flow.locator('#progress').get_attribute('value') == '50'
        assert '当前检查预计剩余 10 秒' in flow.locator('#transfer').inner_text()
        assert flow.locator('#stage-verify').get_attribute('aria-current') == 'step'
        assert '20 / 100' in flow.locator('#detail').inner_text()
        flow.emulate_media(color_scheme='dark')
        flow.screenshot(path=str(args.output/'installer-verify-dark.png'), full_page=True)
        event({'event':'phase','phase':'self_test'})
        event({'event':'self_test_progress','checked':2,'total':4})
        assert flow.locator('#progress').get_attribute('value') == '50'
        event({'event':'retry','reason':'slow','attempt':2,'switching_source':True})
        assert '正在切换下载通道' in flow.locator('#status').inner_text()
        assert flow.locator('#progress').is_hidden()
        event({'event':'phase','phase':'launch_service'})
        assert flow.locator('#progress').is_hidden()
        assert flow.locator('#stage-launch').get_attribute('aria-current') == 'step'
        assert flow.locator('progress:not([value])').count() == 0
        event({'event':'ready'})
        assert flow.locator('#progress').get_attribute('value') == '100'
        flow.evaluate('window.testFinishInstall()')
        flow.get_by_role('button', name='打开 Stella').wait_for()
        assert '需下载' not in flow.locator('#size').inner_text()
        assert flow.locator('#components li').all_text_contents() == [
            'Stella 工作空间已准备','法院与网页组件已准备','文字识别组件已准备','文档转换组件已准备']
        flow.evaluate('window.testLaunchFailure=true')
        flow.get_by_role('button', name='打开 Stella').click()
        flow.get_by_role('button', name='重试启动').wait_for()
        assert flow.locator('#transfer').is_hidden()
        assert flow.locator('#overall').is_hidden()
        # Detection retry must not also run installation commands or add listeners.
        retry = browser.new_page()
        retry.add_init_script('window.testProbeFailures=2;' + MOCK)
        retry.goto((ROOT/'windows-installer/ui/index.html').as_uri())
        retry.get_by_role('button', name='重新检测').wait_for()
        retry.get_by_role('button', name='重新检测').click()
        retry.wait_for_function('window.testCalls.length===2')
        assert retry.evaluate('window.testCalls') == ['inspect_installation'] * 2
        retry.get_by_role('button', name='重新检测').click()
        retry.get_by_role('button', name='安装并准备组件').wait_for()
        assert retry.evaluate('window.testCalls') == ['inspect_installation'] * 3 + ['installation_plan']
        assert retry.evaluate('window.testListeners') == 1
        unsupported = browser.new_page()
        unsupported.add_init_script('window.testSupported=false;' + MOCK)
        unsupported.goto((ROOT/'windows-installer/ui/index.html').as_uri())
        button = unsupported.get_by_role('button', name='暂不支持此设备')
        button.wait_for()
        assert button.is_disabled()
        assert unsupported.locator('#progress').get_attribute('value') == '0'
        assert unsupported.evaluate('window.testCalls') == ['inspect_installation']
        assert 'Windows 10' in unsupported.locator('#status').inner_text()
        installed = browser.new_page()
        installed.add_init_script('window.testInstalled=true;' + MOCK)
        installed.goto((ROOT/'windows-installer/ui/index.html').as_uri())
        installed.get_by_role('button', name='打开 Stella').wait_for()
        assert installed.get_by_role('button', name='检查更新与修复').is_enabled()
        assert installed.evaluate('window.testCalls') == ['inspect_installation']
        browser.close()
    print('Installer UI passed: plan, component list, size, light/dark, install and launch (mock native bridge)')


if __name__ == '__main__': main()
