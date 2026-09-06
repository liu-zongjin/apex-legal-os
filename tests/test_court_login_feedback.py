"""隔离浏览器验证登录反馈，不访问法院或使用真实账号。"""
import time
import unittest
from playwright.async_api import async_playwright
from backend.court_online_service import (
    _arm_login_feedback,
    _browser_executable,
    _refresh_captcha_image,
    _wait_login_result,
)


class CourtLoginFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = await async_playwright().start()
        self.browser = await self.driver.chromium.launch(executable_path=_browser_executable() or None, headless=True)
        self.page = await self.browser.new_page()
        await self.page.route('http://login.test/**', lambda route: route.fulfill(body='<html><body></body></html>', content_type='text/html'))
        await self.page.goto('http://login.test/#/pagesGrxx/pc/login/index')

    async def asyncTearDown(self):
        await self.browser.close()
        await self.driver.stop()

    async def test_captcha_error_within_one_second(self):
        await _arm_login_feedback(self.page)
        await self.page.evaluate("() => setTimeout(() => document.body.innerHTML = '<uni-toast>验证码识别错误</uni-toast>', 30)")
        started = time.monotonic()
        self.assertEqual(await _wait_login_result(self.page), 'captcha_error')
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1)
        print(f'captcha error response: {elapsed:.3f}s')

    async def test_stale_error_ignored(self):
        await self.page.evaluate("() => document.body.innerHTML = '<uni-toast>验证码错误</uni-toast>'")
        await _arm_login_feedback(self.page)
        await self.page.evaluate("""() => setTimeout(() => {
            localStorage.setItem('zxfwtoken', 'test'); location.hash = '/pagesGrxx';
        }, 200)""")
        self.assertEqual(await _wait_login_result(self.page), 'success')

    async def test_hidden_and_password_errors_ignored(self):
        await _arm_login_feedback(self.page)
        await self.page.evaluate("""() => {
            document.body.innerHTML = '<uni-toast style="display:none">验证码错误</uni-toast><div role="alert">密码错误</div>';
            setTimeout(() => {localStorage.setItem('zxfwtoken', 'test'); location.hash = '/pagesGrxx';}, 200);
        }""")
        self.assertEqual(await _wait_login_result(self.page), 'success')

    async def test_reused_toast_detected(self):
        await self.page.evaluate("() => document.body.innerHTML = '<uni-toast>验证码错误</uni-toast>'")
        await _arm_login_feedback(self.page)
        await self.page.evaluate("""() => {
            const toast = document.querySelector('uni-toast'); toast.style.display = 'none';
            setTimeout(() => toast.style.display = 'block', 50);
        }""")
        self.assertEqual(await _wait_login_result(self.page), 'captcha_error')

    async def test_inline_captcha_error_detected_within_one_second(self):
        await _arm_login_feedback(self.page)
        await self.page.evaluate("""() => setTimeout(() => {
            const tip = document.createElement('div');
            tip.className = 'fd-input-code-error';
            tip.textContent = '验证码输入错误';
            document.body.appendChild(tip);
        }, 30)""")
        started = time.monotonic()
        self.assertEqual(await _wait_login_result(self.page), 'captcha_error')
        self.assertLess(time.monotonic() - started, 1)

    async def test_captcha_refresh_returns_new_image_within_one_second(self):
        await self.page.set_content("""
            <div class="fd-images-code"><img src="old-captcha"></div>
            <script>
                document.querySelector('img').addEventListener('click', () => {
                    setTimeout(() => document.querySelector('img').src = 'new-captcha', 40);
                });
            </script>
        """)
        captcha = self.page.locator('.fd-images-code').first

        async def read_image():
            return await self.page.locator('.fd-images-code img').get_attribute('src')

        started = time.monotonic()
        refreshed = await _refresh_captcha_image(
            self.page, captcha, 'http://login.test/old-captcha', read_image
        )
        self.assertEqual(refreshed, 'http://login.test/new-captcha')
        self.assertLess(time.monotonic() - started, 1)
