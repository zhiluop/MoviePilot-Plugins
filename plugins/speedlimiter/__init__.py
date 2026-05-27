import ipaddress
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import Event, eventmanager
from app.helper.downloader import DownloaderHelper
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType, ServiceInfo
from app.schemas.types import EventType


class SpeedLimiter(_PluginBase):
    # 插件名称
    plugin_name = "播放限速"
    # 插件描述
    plugin_desc = "公网播放媒体库视频时，自动对下载器进行上传限速。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/zhiluop/MoviePilot-Plugins/main/icons/micon.png"
    # 插件版本
    plugin_version = "3.0.1"
    # 插件作者
    plugin_author = "zhiluop"
    # 作者主页
    author_url = "https://github.com/zhiluop/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "speedlimit_"
    # 加载顺序
    plugin_order = 11
    # 可使用的用户级别
    auth_level = 1

    _playback_events = {
        "playback.start",
        "PlaybackStart",
        "media.play",
        "playback.stop",
        "PlaybackStop",
        "media.stop",
        "playback.pause",
        "PlaybackPause",
        "playback.resume",
        "PlaybackResume",
    }

    def __init__(self):
        super().__init__()
        self._enabled: bool = False
        self._notify: bool = True
        self._interval: int = 60
        self._downloader: List[str] = []
        self._mediaserver: List[str] = []
        self._play_up_speed: float = 0
        self._noplay_up_speed: float = 0
        self._bandwidth: float = 0
        self._allocation_ratio: str = ""
        self._auto_limit: bool = False
        self._limit_enabled: bool = False
        self._unlimited_ips: Dict[str, str] = {"ipv4": "", "ipv6": ""}
        self._current_state: str = ""
        self._exclude_path: str = ""

    def init_plugin(self, config: dict = None):
        config = config or {}

        self._enabled = bool(config.get("enabled"))
        self._notify = bool(config.get("notify", True))
        self._interval = max(self.__to_int(config.get("interval"), 60), 10)
        self._downloader = config.get("downloader") or []
        self._mediaserver = config.get("mediaserver") or []
        self._play_up_speed = self.__to_float(config.get("play_up_speed"))
        self._noplay_up_speed = self.__to_float(config.get("noplay_up_speed"))
        self._allocation_ratio = config.get("allocation_ratio") or ""
        self._exclude_path = config.get("exclude_path") or ""
        self._unlimited_ips = {
            "ipv4": config.get("ipv4") or "",
            "ipv6": config.get("ipv6") or "",
        }

        bandwidth_mbps = self.__to_float(config.get("bandwidth"))
        self._bandwidth = bandwidth_mbps * 1000000
        self._auto_limit = self._bandwidth > 0
        self._limit_enabled = bool(
            self._auto_limit
            or self._play_up_speed
            or self._noplay_up_speed
        )
        self._current_state = ""
        logger.info(
            "播放限速配置已加载："
            f"启用={self._enabled}，公网播放上传限速={self._play_up_speed} KB/s，"
            f"内网或未观看上传限速={self._noplay_up_speed} KB/s，"
            f"智能上行带宽={self._bandwidth / 1000000:g} Mbps，"
            f"下载器={','.join(self._downloader) or '未选择'}，"
            f"媒体服务器={','.join(self._mediaserver) or '全部'}"
        )
        if self._enabled and not self._limit_enabled:
            logger.warning("播放限速已启用但未配置任何上传限速或智能上行带宽，检查服务不会启动")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._limit_enabled:
            return []
        return [
            {
                "id": "SpeedLimiter",
                "name": "播放限速检查服务",
                "trigger": "interval",
                "func": self.check_playing_sessions,
                "kwargs": {"seconds": self._interval},
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        downloader_items = [
            {"title": config.name, "value": config.name}
            for config in DownloaderHelper().get_configs().values()
        ]
        mediaserver_items = [
            {"title": config.name, "value": config.name}
            for config in MediaServerHelper().get_configs().values()
        ]

        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "notify", "label": "发送通知"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "interval",
                                            "label": "检查间隔",
                                            "placeholder": "秒，最低 10",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "multiple": True,
                                            "chips": True,
                                            "clearable": True,
                                            "model": "downloader",
                                            "label": "下载器",
                                            "items": downloader_items,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "multiple": True,
                                            "chips": True,
                                            "clearable": True,
                                            "model": "mediaserver",
                                            "label": "媒体服务器",
                                            "items": mediaserver_items,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "play_up_speed",
                                            "label": "公网播放上传限速",
                                            "placeholder": "KB/s，0 为不限",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "noplay_up_speed",
                                            "label": "内网或未观看上传限速",
                                            "placeholder": "KB/s，0 为解除上传限速",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "bandwidth",
                                            "label": "智能限速上行带宽",
                                            "placeholder": "Mbps，留空使用固定限速",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "allocation_ratio",
                                            "label": "多下载器分配比例",
                                            "items": [
                                                {"title": "平均", "value": ""},
                                                {"title": "1:9", "value": "1:9"},
                                                {"title": "2:8", "value": "2:8"},
                                                {"title": "3:7", "value": "3:7"},
                                                {"title": "4:6", "value": "4:6"},
                                                {"title": "6:4", "value": "6:4"},
                                                {"title": "7:3", "value": "7:3"},
                                                {"title": "8:2", "value": "8:2"},
                                                {"title": "9:1", "value": "9:1"},
                                            ],
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "ipv4",
                                            "label": "不限速 IPv4/CIDR",
                                            "placeholder": "留空默认内网不限速；多个用逗号或换行",
                                            "rows": 2,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "ipv6",
                                            "label": "不限速 IPv6/CIDR",
                                            "placeholder": "留空默认内网不限速；多个用逗号或换行",
                                            "rows": 2,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_path",
                                            "label": "不限速路径",
                                            "placeholder": "包含这些路径片段的媒体不触发限速；多个换行",
                                            "rows": 3,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "interval": 60,
            "downloader": [],
            "mediaserver": [],
            "play_up_speed": None,
            "noplay_up_speed": None,
            "bandwidth": None,
            "allocation_ratio": "",
            "ipv4": "",
            "ipv6": "",
            "exclude_path": "",
        }

    def get_page(self) -> List[dict]:
        return []

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        if not self._downloader:
            logger.warning("尚未配置下载器，请检查播放限速插件配置")
            return None

        services = DownloaderHelper().get_services(name_filters=self._downloader)
        active_services = {}
        for service_name, service_info in services.items():
            if self.__service_inactive(service_info):
                logger.warning(f"下载器 {service_name} 未连接，跳过限速")
                continue
            active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查播放限速插件配置")
            return None
        return active_services

    @property
    def media_server_infos(self) -> Dict[str, ServiceInfo]:
        return MediaServerHelper().get_services(name_filters=self._mediaserver or None)

    @eventmanager.register(EventType.WebhookMessage)
    def check_playing_sessions(self, event: Event = None):
        if not self._enabled or not self._limit_enabled:
            return
        if event and self.__event_name(event.event_data) not in self._playback_events:
            return
        if not self.service_infos:
            return

        total_bit_rate = self.__collect_public_video_bitrate()
        if total_bit_rate:
            upload_limit = self.__calc_limit(total_bit_rate) if self._auto_limit else self._play_up_speed
            logger.info(f"播放限速检查：检测到公网播放，总视频码率 {total_bit_rate} bps，准备设置上传限速 {upload_limit} KB/s")
            self.__set_limiter("公网播放", upload_limit)
        else:
            logger.info(f"播放限速检查：当前为内网播放或未观看，准备恢复上传限速 {self._noplay_up_speed} KB/s")
            self.__set_limiter("内网或未观看", self._noplay_up_speed)

    def __collect_public_video_bitrate(self) -> int:
        total_bit_rate = 0
        for service_name, service in self.media_server_infos.items():
            service_type = (service.type or "").lower()
            try:
                if service_type == "emby":
                    total_bit_rate += self.__collect_emby_or_jellyfin_bitrate(
                        service.instance,
                        "[HOST]emby/Sessions?api_key=[APIKEY]",
                    )
                elif service_type == "jellyfin":
                    total_bit_rate += self.__collect_emby_or_jellyfin_bitrate(
                        service.instance,
                        "[HOST]Sessions?api_key=[APIKEY]",
                    )
                elif service_type == "plex":
                    total_bit_rate += self.__collect_plex_bitrate(service.instance)
            except Exception as err:
                logger.error(f"获取 {service_name} 播放会话失败：{err}")
        return total_bit_rate

    def __collect_emby_or_jellyfin_bitrate(self, instance: Any, req_url: str) -> int:
        response = instance.get_data(req_url)
        if not response or response.status_code != 200:
            return 0

        total_bit_rate = 0
        for session in response.json() or []:
            item = session.get("NowPlayingItem") or {}
            if not self.__active_video_item(session, item):
                continue
            if self.__path_excluded(item.get("Path")):
                continue
            if self.__is_unlimited_endpoint(session.get("RemoteEndPoint")):
                continue
            total_bit_rate += self.__item_video_bitrate(item)
        return total_bit_rate

    def __collect_plex_bitrate(self, instance: Any) -> int:
        plex = instance.get_plex()
        if not plex:
            return 0

        total_bit_rate = 0
        for session in plex.sessions() or []:
            if getattr(session, "TAG", None) != "Video":
                continue
            if self.__is_unlimited_endpoint(getattr(session.player, "address", None)):
                continue
            total_bit_rate += sum(int(media.bitrate or 0) * 1000 for media in session.media or [])
        return total_bit_rate

    def __active_video_item(self, session: Dict[str, Any], item: Dict[str, Any]) -> bool:
        if not item or item.get("MediaType") != "Video":
            return False
        if (session.get("PlayState") or {}).get("IsPaused"):
            return False
        return True

    def __item_video_bitrate(self, item: Dict[str, Any]) -> int:
        if item.get("Bitrate"):
            return int(item.get("Bitrate") or 0)

        total = 0
        for stream in item.get("MediaStreams") or []:
            stream_type = str(stream.get("Type") or stream.get("type") or "").lower()
            if stream_type and stream_type != "video":
                continue
            total += int(stream.get("BitRate") or stream.get("Bitrate") or stream.get("bitrate") or 0)
        return total

    def __path_excluded(self, path: Optional[str]) -> bool:
        if not path or not self._exclude_path:
            return False
        for exclude_path in self.__split_config_values(self._exclude_path):
            if exclude_path and exclude_path in path:
                logger.info(f"{path} 命中不限速路径 {exclude_path}，跳过限速")
                return True
        return False

    def __calc_limit(self, total_bit_rate: float) -> float:
        if not self._bandwidth:
            return self._play_up_speed
        limit = (self._bandwidth - total_bit_rate) / 8 / 1024
        return round(max(limit, 0), 2)

    def __set_limiter(self, limit_type: str, upload_limit: float):
        services = self.service_infos
        if not services:
            return

        upload_limits = self.__allocated_upload_limits(upload_limit, len(services))
        download_limits = [
            self.__current_download_limit(service.instance, service.type)
            for service in services.values()
        ]
        state = f"{limit_type}|U:{upload_limits}|D:{download_limits}|S:{','.join(services)}"
        if self._current_state == state:
            logger.info(f"播放限速状态未变化：{limit_type}，{self.__format_limit_lines(services, upload_limits, download_limits)}")
            return
        self._current_state = state

        results = []
        for index, (service_name, service) in enumerate(services.items()):
            service_upload_limit = upload_limits[index]
            service_download_limit = download_limits[index]
            try:
                success = service.instance.set_speed_limit(
                    download_limit=service_download_limit,
                    upload_limit=service_upload_limit,
                )
                results.append({
                    "name": service_name,
                    "type": service.type,
                    "upload_limit": service_upload_limit,
                    "download_limit": service_download_limit,
                    "success": bool(success),
                })
            except Exception as err:
                logger.error(f"设置下载器 {service_name} 限速失败：{err}")
                results.append({
                    "name": service_name,
                    "type": service.type,
                    "upload_limit": service_upload_limit,
                    "download_limit": service_download_limit,
                    "success": False,
                })

        logger.info(f"播放限速状态切换：{limit_type}；{self.__format_result_lines(results)}")
        self.__notify_limiter(limit_type, results)

    @staticmethod
    def __current_download_limit(instance: Any, service_type: str = None) -> int:
        if str(service_type or "").lower() == "transmission":
            try:
                session = instance.trc.get_session()
                if session and not session.get("speed_limit_down_enabled"):
                    return 0
            except Exception:
                pass

        getter = getattr(instance, "get_speed_limit", None)
        if not callable(getter):
            return 0
        try:
            limits = getter()
        except Exception as err:
            logger.warning(f"读取下载器当前限速失败，将下载限速按不限速处理：{err}")
            return 0
        if not limits:
            return 0
        try:
            return int(float(limits[0] or 0))
        except (TypeError, ValueError, IndexError):
            return 0

    def __allocated_upload_limits(self, upload_limit: float, count: int) -> List[int]:
        if count <= 0:
            return []
        upload_limit = int(upload_limit)
        if not self._auto_limit or count == 1:
            return [upload_limit] * count

        ratios = self.__allocation_ratios(count)
        if not ratios:
            per_service = int(upload_limit / count)
            return [per_service] * count

        ratio_sum = sum(ratios)
        return [int(upload_limit * ratio / ratio_sum) for ratio in ratios]

    def __allocation_ratios(self, count: int) -> List[int]:
        if not self._allocation_ratio:
            return []
        try:
            ratios = [int(item) for item in self._allocation_ratio.split(":")]
        except ValueError:
            logger.warning(f"播放限速分配比例配置错误：{self._allocation_ratio}")
            return []
        return ratios if len(ratios) == count and all(ratio > 0 for ratio in ratios) else []

    def __notify_limiter(self, limit_type: str, results: List[Dict[str, Any]]):
        if not self._notify:
            return
        text = self.__format_result_lines(results)
        self.post_message(
            mtype=NotificationType.MediaServer,
            title="【播放限速】",
            text=f"{limit_type}\n{text}",
        )

    @staticmethod
    def __format_result_lines(results: List[Dict[str, Any]]) -> str:
        lines = []
        for result in results:
            status = "成功" if result.get("success") else "失败"
            lines.append(
                f"{result.get('name')}({result.get('type')})："
                f"上传 {result.get('upload_limit')} KB/s，"
                f"下载保持 {result.get('download_limit')} KB/s，{status}"
            )
        return "\n".join(lines)

    @staticmethod
    def __format_limit_lines(
            services: Dict[str, ServiceInfo],
            upload_limits: List[int],
            download_limits: List[int],
    ) -> str:
        results = []
        for index, (service_name, service) in enumerate(services.items()):
            results.append({
                "name": service_name,
                "type": service.type,
                "upload_limit": upload_limits[index],
                "download_limit": download_limits[index],
                "success": True,
            })
        return SpeedLimiter.__format_result_lines(results)

    def __is_unlimited_endpoint(self, endpoint: Optional[str]) -> bool:
        ipaddr = self.__endpoint_to_ip(endpoint)
        if not ipaddr:
            return True

        has_custom_ranges = bool(self._unlimited_ips.get("ipv4") or self._unlimited_ips.get("ipv6"))
        if not has_custom_ranges:
            return self.__is_lan_ip(ipaddr)

        key = "ipv4" if ipaddr.version == 4 else "ipv6"
        ranges = self.__split_config_values(self._unlimited_ips.get(key))
        if not ranges:
            return True

        for network in ranges:
            try:
                if ipaddr in ipaddress.ip_network(network, strict=False):
                    return True
            except ValueError:
                logger.warning(f"播放限速不限速地址范围无效：{network}")
        return False

    @staticmethod
    def __endpoint_to_ip(endpoint: Optional[str]) -> Optional[ipaddress._BaseAddress]:
        if not endpoint:
            return None

        text = str(endpoint).strip()
        if not text:
            return None
        text = text.split(",", 1)[0].strip()

        if text.startswith("[") and "]" in text:
            text = text[1:text.index("]")]

        candidates = [text]
        if text.count(":") == 1 and "." in text:
            candidates.append(text.rsplit(":", 1)[0])
        elif text.count(":") > 1 and text.rsplit(":", 1)[-1].isdigit():
            candidates.append(text.rsplit(":", 1)[0])

        for candidate in candidates:
            try:
                ipaddr = ipaddress.ip_address(candidate)
                return getattr(ipaddr, "ipv4_mapped", None) or ipaddr
            except ValueError:
                continue
        logger.warning(f"无法识别播放客户端地址：{endpoint}")
        return None

    @staticmethod
    def __is_lan_ip(ipaddr: ipaddress._BaseAddress) -> bool:
        return any([
            ipaddr.is_private,
            ipaddr.is_loopback,
            ipaddr.is_link_local,
            ipaddr.is_multicast,
            ipaddr.is_unspecified,
        ])

    @staticmethod
    def __split_config_values(value: Optional[str]) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in re.split(r"[,\n]+", value) if item.strip()]

    @staticmethod
    def __service_inactive(service_info: ServiceInfo) -> bool:
        instance = service_info.instance if service_info else None
        inactive = getattr(instance, "is_inactive", None)
        if not callable(inactive):
            return False
        try:
            return bool(inactive())
        except Exception as err:
            logger.warning(f"检查服务连接状态失败：{err}")
            return True

    @staticmethod
    def __event_name(event_data: Any) -> Optional[str]:
        if isinstance(event_data, dict):
            return event_data.get("event")
        return getattr(event_data, "event", None)

    @staticmethod
    def __to_float(value: Any, default: float = 0) -> float:
        try:
            return float(value or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def __to_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(value or default))
        except (TypeError, ValueError):
            return default

    def stop_service(self):
        pass
