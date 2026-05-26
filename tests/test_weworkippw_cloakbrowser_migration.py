from pathlib import Path
import unittest


PLUGIN_FILE = Path(__file__).resolve().parents[1] / "plugins" / "weworkippw" / "__init__.py"


class WeWorkIPPWCloakBrowserMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLUGIN_FILE.read_text(encoding="utf-8")

    def test_uses_cloakbrowser_instead_of_playwright_chromium(self):
        self.assertIn("from cloakbrowser import launch_context", self.source)
        self.assertNotIn("sync_playwright", self.source)
        self.assertNotIn(".chromium.launch", self.source)
        self.assertNotIn("frame_locator(", self.source)

    def test_keeps_browser_launch_in_single_helper(self):
        self.assertIn("def _launch_browser_context", self.source)
        self.assertIn("launch_context(headless=headless", self.source)
        self.assertIn("Accept-Language", self.source)


if __name__ == "__main__":
    unittest.main()
