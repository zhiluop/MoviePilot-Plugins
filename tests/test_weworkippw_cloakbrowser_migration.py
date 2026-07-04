from pathlib import Path
import json
import unittest


PACKAGE_FILE = Path(__file__).resolve().parents[1] / "package.json"
PLUGIN_FILE = Path(__file__).resolve().parents[1] / "plugins" / "weworkippw" / "__init__.py"


class WeWorkIPPWCloakBrowserMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLUGIN_FILE.read_text(encoding="utf-8")
        cls.package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))

    def test_uses_cloakbrowser_instead_of_playwright_chromium(self):
        self.assertIn("from cloakbrowser import launch_context", self.source)
        self.assertNotIn("sync_playwright", self.source)
        self.assertNotIn(".chromium.launch", self.source)
        self.assertNotIn("frame_locator(", self.source)
        self.assertNotIn("framenavigated", self.source)

    def test_keeps_browser_launch_in_single_helper(self):
        self.assertIn("def _launch_browser_context", self.source)
        self.assertIn("launch_context(", self.source)
        self.assertIn("headless=headless", self.source)
        self.assertIn("humanize=settings.CLOAKBROWSER_HUMANIZE", self.source)
        self.assertIn("human_preset=settings.CLOAKBROWSER_HUMAN_PRESET", self.source)
        self.assertIn("Accept-Language", self.source)

    def test_package_metadata_identifies_the_cloakbrowser_fork(self):
        metadata = self.package["WeWorkIPPW"]

        self.assertEqual(metadata["name"], "企微配置IP Cloak版")
        self.assertEqual(metadata["author"], "zhiluop")
        self.assertEqual(metadata["version"], "2.5.4")
        self.assertIn("CloakBrowser", metadata["description"])
        self.assertIn('plugin_name = "企微配置IP Cloak版"', self.source)
        self.assertIn('plugin_author = "zhiluop"', self.source)

    def test_login_polls_success_state_and_reads_context_cookies(self):
        self.assertIn("def _wait_for_login_success", self.source)
        self.assertIn("def _is_login_success", self.source)
        self.assertIn("cookies = self._context_cookies(context)", self.source)
        self.assertIn("登录成功后未从浏览器上下文读取到cookie", self.source)

    def test_login_qr_detection_is_not_tied_to_one_css_class(self):
        self.assertIn("def _iter_login_frames", self.source)
        self.assertIn("def _safe_frame_url", self.source)
        self.assertIn("def _find_qr_url_in_frame", self.source)
        self.assertIn("img[src*='qrcode']", self.source)
        self.assertIn("img[src*='wwqrlogin']", self.source)
        self.assertIn("canvas.toDataURL", self.source)
        self.assertIn("未找到登录二维码图片，页面结构", self.source)

    def test_login_qr_image_save_supports_data_urls(self):
        self.assertIn("def _save_qr_image", self.source)
        self.assertIn('qr_url.startswith("data:image/")', self.source)
        self.assertIn("base64.b64decode", self.source)
        self.assertIn("unquote_to_bytes", self.source)

    def test_browser_sync_api_runs_on_dedicated_thread(self):
        self.assertIn("ThreadPoolExecutor", self.source)
        self.assertIn("thread_name_prefix=\"weworkippw-browser\"", self.source)
        self.assertIn("def _run_browser_task", self.source)
        self.assertIn("with ThreadPoolExecutor(max_workers=1", self.source)
        self.assertIn("threading.local()", self.source)
        self.assertIn("return self._run_browser_task(self._refresh_cookie_impl", self.source)
        self.assertIn("return self._run_browser_task(self._login_impl)", self.source)
        self.assertIn("return self._run_browser_task(self._change_ip_impl)", self.source)

    def test_browser_context_close_is_guarded_after_crashes(self):
        self.assertIn("def _close_browser_context", self.source)
        self.assertIn("关闭企业微信浏览器上下文失败", self.source)
        self.assertNotIn("_browser_executor:", self.source)

    def test_login_job_uses_stable_id_and_single_instance(self):
        self.assertIn('id="wwlogin"', self.source)
        self.assertIn("replace_existing=True", self.source)
        self.assertIn("max_instances=1", self.source)
        self.assertIn("coalesce=True", self.source)


if __name__ == "__main__":
    unittest.main()
