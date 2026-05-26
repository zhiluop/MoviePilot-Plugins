import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILE = ROOT / "plugins" / "speedlimiter" / "__init__.py"
PACKAGE_FILE = ROOT / "package.json"


def _install_app_stubs():
    app = types.ModuleType("app")
    core = types.ModuleType("app.core")
    event = types.ModuleType("app.core.event")
    helper = types.ModuleType("app.helper")
    downloader = types.ModuleType("app.helper.downloader")
    mediaserver = types.ModuleType("app.helper.mediaserver")
    schemas = types.ModuleType("app.schemas")
    schema_types = types.ModuleType("app.schemas.types")
    log = types.ModuleType("app.log")
    plugins = types.ModuleType("app.plugins")

    class Event:
        def __init__(self, event_type=None):
            self.event_type = event_type
            self.event_data = {}

    class EventManager:
        def register(self, _etype):
            def decorator(func):
                return func

            return decorator

    class DownloaderHelper:
        def get_configs(self, include_disabled=False):
            return {}

        def get_services(self, type_filter=None, name_filters=None):
            return {}

    class MediaServerHelper:
        def get_services(self, type_filter=None, name_filters=None):
            return {}

    class NotificationType:
        MediaServer = "媒体服务器通知"

    class WebhookEventInfo:
        pass

    class ServiceInfo:
        def __init__(self, name=None, instance=None, type=None, config=None):
            self.name = name
            self.instance = instance
            self.type = type
            self.config = config

    class EventType:
        WebhookMessage = "webhook.message"

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

    class PluginBase:
        def post_message(self, *args, **kwargs):
            self._posted_messages = getattr(self, "_posted_messages", [])
            self._posted_messages.append((args, kwargs))

    event.eventmanager = EventManager()
    event.Event = Event
    downloader.DownloaderHelper = DownloaderHelper
    mediaserver.MediaServerHelper = MediaServerHelper
    schemas.NotificationType = NotificationType
    schemas.WebhookEventInfo = WebhookEventInfo
    schemas.ServiceInfo = ServiceInfo
    schema_types.EventType = EventType
    log.logger = Logger()
    plugins._PluginBase = PluginBase

    modules = {
        "app": app,
        "app.core": core,
        "app.core.event": event,
        "app.helper": helper,
        "app.helper.downloader": downloader,
        "app.helper.mediaserver": mediaserver,
        "app.schemas": schemas,
        "app.schemas.types": schema_types,
        "app.log": log,
        "app.plugins": plugins,
    }
    sys.modules.update(modules)


def _load_plugin():
    _install_app_stubs()
    spec = importlib.util.spec_from_file_location("speedlimiter_plugin", PLUGIN_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["speedlimiter_plugin"] = module
    spec.loader.exec_module(module)
    return module


class SpeedLimiterBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_plugin()
        cls.plugin = cls.module.SpeedLimiter()

    def test_package_metadata_registers_speedlimiter(self):
        package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))
        metadata = package["SpeedLimiter"]

        self.assertEqual(metadata["name"], "播放限速")
        self.assertEqual(metadata["author"], "zhiluop")
        self.assertTrue(metadata["v2"])
        self.assertIn("公网", metadata["description"])

    def test_endpoint_parser_handles_ports_and_ipv4_mapped_ipv6(self):
        parse = self.plugin._SpeedLimiter__endpoint_to_ip

        self.assertEqual(str(parse("8.8.8.8:8096")), "8.8.8.8")
        self.assertEqual(str(parse("[2001:4860:4860::8888]:443")), "2001:4860:4860::8888")
        self.assertEqual(str(parse("::ffff:8.8.4.4")), "8.8.4.4")

    def test_default_unlimited_check_treats_lan_as_unlimited_only(self):
        is_unlimited = self.plugin._SpeedLimiter__is_unlimited_endpoint

        self.assertTrue(is_unlimited("192.168.31.20:8096"))
        self.assertTrue(is_unlimited("fd00::1"))
        self.assertFalse(is_unlimited("8.8.8.8:8096"))

    def test_configured_unlimited_cidrs_override_public_clients(self):
        plugin = self.module.SpeedLimiter()
        plugin.init_plugin({"ipv4": "8.8.8.0/24", "ipv6": "2001:4860:4860::/48"})
        is_unlimited = plugin._SpeedLimiter__is_unlimited_endpoint

        self.assertTrue(is_unlimited("8.8.8.8:8096"))
        self.assertTrue(is_unlimited("[2001:4860:4860::8888]:443"))
        self.assertFalse(is_unlimited("1.1.1.1"))

    def test_path_exclusion_ignores_empty_lines_and_missing_paths(self):
        plugin = self.module.SpeedLimiter()
        plugin.init_plugin({"exclude_path": "\n/儿童/\n  /纪录片/  \n"})
        excluded = plugin._SpeedLimiter__path_excluded

        self.assertTrue(excluded("/media/儿童/movie.mkv"))
        self.assertTrue(excluded("/media/纪录片/doc.mkv"))
        self.assertFalse(excluded("/media/movie.mkv"))
        self.assertFalse(excluded(None))

    def test_bitrate_helpers_pick_video_bitrate_without_audio_double_counting(self):
        video_stream_bitrate = self.plugin._SpeedLimiter__item_video_bitrate(
            {
                "Bitrate": 0,
                "MediaStreams": [
                    {"Type": "Audio", "BitRate": 192000},
                    {"Type": "Video", "BitRate": 12000000},
                ],
            }
        )
        fallback_bitrate = self.plugin._SpeedLimiter__item_video_bitrate({"Bitrate": 9000000})

        self.assertEqual(video_stream_bitrate, 12000000)
        self.assertEqual(fallback_bitrate, 9000000)

    def test_limit_calculation_never_returns_negative_speed(self):
        plugin = self.module.SpeedLimiter()
        plugin.init_plugin({"bandwidth": "10"})

        self.assertEqual(plugin._SpeedLimiter__calc_limit(12000000), 0)


if __name__ == "__main__":
    unittest.main()
