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

    def test_keeps_browser_launch_in_single_helper(self):
        self.assertIn("def _launch_browser_context", self.source)
        self.assertIn("launch_context(headless=headless", self.source)
        self.assertIn("Accept-Language", self.source)

    def test_package_metadata_identifies_the_cloakbrowser_fork(self):
        metadata = self.package["WeWorkIPPW"]

        self.assertEqual(metadata["name"], "企微配置IP Cloak版")
        self.assertEqual(metadata["author"], "zhiluop")
        self.assertEqual(metadata["version"], "2.5.0")
        self.assertIn("CloakBrowser", metadata["description"])
        self.assertIn('plugin_name = "企微配置IP Cloak版"', self.source)
        self.assertIn('plugin_author = "zhiluop"', self.source)


if __name__ == "__main__":
    unittest.main()
