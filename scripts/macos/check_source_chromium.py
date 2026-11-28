"""Check both Playwright Chromium executables before tolerating an install error."""
import subprocess
import sys


def main():
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            # Headful features and headless features may use different binaries.
            subprocess.run([playwright.chromium.executable_path, '--version'],
                           check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
            browser = playwright.chromium.launch(headless=True, timeout=15000)
            try:
                page = browser.new_page()
                page.set_content('<title>Stella browser check</title>')
                if page.title() != 'Stella browser check':
                    raise RuntimeError('Chromium page check failed')
            finally:
                browser.close()
    except Exception as exc:
        print(f'无法确认当前 Playwright Chromium 可用：{exc}', file=sys.stderr)
        return 1
    print('当前 Playwright 的 Chromium 完整版可执行文件可运行，无头模式已通过启动检查。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
