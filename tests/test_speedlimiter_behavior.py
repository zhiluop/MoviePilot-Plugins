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
        def get_configs(self, include_disabled=False):
            return {}

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
        records = []

        @classmethod
        def clear(cls):
            cls.records = []

        def info(self, *args, **kwargs):
            self.records.append(("info", args, kwargs))

        def warning(self, *args, **kwargs):
            self.records.append(("warning", args, kwargs))

        def error(self, *args, **kwargs):
            self.records.append(("error", args, kwargs))

        def debug(self, *args, **kwargs):
            self.records.append(("debug", args, kwargs))

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
    return Logger


def _load_plugin():
    logger_class = _install_app_stubs()
    spec = importlib.util.spec_from_file_location("speedlimiter_plugin", PLUGIN_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["speedlimiter_plugin"] = module
    spec.loader.exec_module(module)
    module._test_logger_class = logger_class
    return module


class FakeDownloader:
    def __init__(self, download_limit=2048, upload_limit=0):
        self.download_limit = download_limit
        self.upload_limit = upload_limit
        self.calls = []

    def get_speed_limit(self):
        return self.download_limit, self.upload_limit

    def set_speed_limit(self, download_limit=None, upload_limit=None):
        self.calls.append({"download_limit": download_limit, "upload_limit": upload_limit})
        self.download_limit = download_limit
        self.upload_limit = upload_limit
        return True


class FakeTransmissionDownloader(FakeDownloader):
    def __init__(self, download_limit=2048, upload_limit=0, download_enabled=False):
        super().__init__(download_limit=download_limit, upload_limit=upload_limit)
        self.trc = self
        self.download_enabled = download_enabled

    def get_session(self):
        return {
            "speed_limit_down": self.download_limit,
            "speed_limit_down_enabled": self.download_enabled,
        }


def _plugin_with_services(module, services):
    class TestSpeedLimiter(module.SpeedLimiter):
        @property
        def service_infos(self):
            return services

    plugin = TestSpeedLimiter()
    plugin._downloader = list(services)
    return plugin


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

    def test_no_play_state_text_uses_internal_or_no_playback_language(self):
        plugin = self.module.SpeedLimiter()

        form, defaults = plugin.get_form()
        form_text = json.dumps(form, ensure_ascii=False)

        self.assertIn("公网播放上传限速", form_text)
        self.assertIn("内网或未观看上传限速", form_text)
        self.assertNotIn("无公网播放", form_text)
        self.assertNotIn("play_down_speed", defaults)
        self.assertNotIn("noplay_down_speed", defaults)

    def test_download_limit_is_preserved_when_setting_upload_limits(self):
        first = FakeDownloader(download_limit=2048)
        second = FakeDownloader(download_limit=4096)
        services = {
            "qb": self.module.ServiceInfo(name="qb", instance=first, type="qbittorrent"),
            "tr": self.module.ServiceInfo(name="tr", instance=second, type="transmission"),
        }
        plugin = _plugin_with_services(self.module, services)
        plugin._notify = False

        plugin._SpeedLimiter__set_limiter("公网播放", 500)

        self.assertEqual(first.calls, [{"download_limit": 2048, "upload_limit": 500}])
        self.assertEqual(second.calls, [{"download_limit": 4096, "upload_limit": 500}])

    def test_disabled_transmission_download_limit_stays_disabled(self):
        plugin = self.module.SpeedLimiter()
        downloader = FakeTransmissionDownloader(download_limit=4096, download_enabled=False)

        limit = plugin._SpeedLimiter__current_download_limit(downloader, "transmission")

        self.assertEqual(limit, 0)

    def test_limiter_notification_is_aggregated_for_multiple_downloaders(self):
        first = FakeDownloader(download_limit=2048)
        second = FakeDownloader(download_limit=4096)
        services = {
            "qb": self.module.ServiceInfo(name="qb", instance=first, type="qbittorrent"),
            "tr": self.module.ServiceInfo(name="tr", instance=second, type="transmission"),
        }
        plugin = _plugin_with_services(self.module, services)
        plugin._notify = True

        plugin._SpeedLimiter__set_limiter("公网播放", 500)

        messages = getattr(plugin, "_posted_messages", [])
        self.assertEqual(len(messages), 1)
        text = messages[0][1]["text"]
        self.assertIn("qb(qbittorrent)：上传 500 KB/s，下载保持 2048 KB/s", text)
        self.assertIn("tr(transmission)：上传 500 KB/s，下载保持 4096 KB/s", text)

    def test_limiter_writes_logs_for_state_changes(self):
        downloader = FakeDownloader(download_limit=2048)
        plugin = _plugin_with_services(self.module, {
            "qb": self.module.ServiceInfo(name="qb", instance=downloader, type="qbittorrent")
        })
        plugin._notify = False
        self.module._test_logger_class.clear()

        plugin._SpeedLimiter__set_limiter("公网播放", 500)

        messages = [record[1][0] for record in self.module._test_logger_class.records if record[0] == "info"]
        self.assertTrue(any("播放限速状态切换：公网播放" in message for message in messages))

    def test_init_warns_when_enabled_without_any_upload_limit(self):
        plugin = self.module.SpeedLimiter()
        self.module._test_logger_class.clear()

        plugin.init_plugin({"enabled": True})

        messages = [record[1][0] for record in self.module._test_logger_class.records if record[0] == "warning"]
        self.assertTrue(any("已启用但未配置任何上传限速" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
