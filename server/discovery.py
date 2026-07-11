"""
mDNS 设备发现

通过 Zeroconf/Bonjour 在局域网中广播和发现 MusicSync 服务。
其他设备可以发现本机并获取同步服务的地址。

依赖: pip install zeroconf
"""

import socket
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

try:
    from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceListener
    _HAS_ZEROCONF = True
except ImportError:
    _HAS_ZEROCONF = False
    Zeroconf = None
    ServiceInfo = None
    ServiceBrowser = None
    ServiceListener = None


SERVICE_TYPE = "_musicsync._tcp.local."
SERVICE_NAME = "MusicSync"


def get_local_ip() -> str:
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class DiscoveryService:
    """mDNS 服务注册 + 发现"""
    
    def __init__(self, port: int = 8899):
        self.port = port
        self._zeroconf: Optional[Zeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._browser: Optional[ServiceBrowser] = None
        self._discovered_devices: dict[str, dict] = {}
        self._on_device_found: Optional[Callable] = None
    
    @property
    def is_available(self) -> bool:
        return _HAS_ZEROCONF
    
    def start_advertising(self, display_name: str = ""):
        """
        开始广播本机服务
        
        其他设备可以发现本机并连接到 HTTP 文件服务
        """
        if not _HAS_ZEROCONF:
            logger.warning("zeroconf 未安装，跳过服务广播。安装: pip install zeroconf")
            return
        
        self._zeroconf = Zeroconf()
        
        ip = get_local_ip()
        hostname = socket.gethostname()
        name = f"{SERVICE_NAME} ({display_name or hostname})"
        
        self._service_info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=name,
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={
                "version": "0.1.0",
                "hostname": hostname,
            },
        )
        
        self._zeroconf.register_service(self._service_info)
        logger.info(f"mDNS 广播已启动: {name} @ {ip}:{self.port}")
    
    def start_discovery(self, on_device_found: Callable[[dict], None]):
        """
        开始发现局域网中的其他 MusicSync 设备
        
        Args:
            on_device_found: 发现设备时的回调，参数为设备信息 dict
        """
        if not _HAS_ZEROCONF:
            logger.warning("zeroconf 未安装，跳过设备发现。")
            return
        
        self._on_device_found = on_device_found
        self._zeroconf = Zeroconf()
        
        class Listener(ServiceListener):
            def add_service(self_zc, type_, name):
                info = self_zc.get_service_info(type_, name)
                if info:
                    device = self._parse_service_info(info)
                    self._discovered_devices[name] = device
                    if self._on_device_found:
                        self._on_device_found(device)
                    logger.info(f"发现设备: {device['name']} @ {device['ip']}:{device['port']}")
            
            def remove_service(self_zc, type_, name):
                if name in self._discovered_devices:
                    del self._discovered_devices[name]
                    logger.info(f"设备离线: {name}")
            
            def update_service(self_zc, type_, name):
                pass
        
        self._browser = ServiceBrowser(self._zeroconf, SERVICE_TYPE, Listener())
        logger.info("开始扫描局域网中的 MusicSync 设备...")
    
    def _parse_service_info(self, info: ServiceInfo) -> dict:
        """解析服务信息"""
        ip = ".".join(str(b) for b in info.addresses[0]) if info.addresses else "unknown"
        props = {}
        for key, value in info.properties.items():
            props[key.decode()] = value.decode() if isinstance(value, bytes) else value
        
        return {
            "name": info.name,
            "ip": ip,
            "port": info.port,
            "version": props.get("version", "unknown"),
            "hostname": props.get("hostname", ""),
        }
    
    def get_discovered_devices(self) -> list[dict]:
        """获取已发现的设备列表"""
        return list(self._discovered_devices.values())
    
    def stop(self):
        """停止所有服务"""
        if self._zeroconf:
            if self._service_info:
                self._zeroconf.unregister_service(self._service_info)
            self._zeroconf.close()
            logger.info("mDNS 服务已停止")
