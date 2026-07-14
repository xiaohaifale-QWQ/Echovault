"""
配置管理模块
管理 API Key、模型选择、路径等全局配置。
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


CONFIG_SCHEMA_VERSION = 1
SUPPORTED_PROVIDERS = {"groq", "local"}
SUPPORTED_LOCAL_MODELS = {"tiny", "base", "small", "medium", "large"}
SUPPORTED_LANGUAGES = {"zh", "en", "ja", "ko"}


@dataclass
class ASRConfig:
    """ASR 识别配置"""
    provider: str = "groq"           # groq | local | aliyun | xunfei
    local_model: str = "base"        # tiny | base | small | medium（仅 local provider）
    language: Optional[str] = None   # None=自动检测, "zh"=中文, "en"=英语, "ja"=日语, "ko"=韩语
    use_vocal_separation: bool = False  # 是否启用 Demucs 人声分离
    use_gpu: bool = False               # 是否启用 GPU 加速（默认 CPU）


@dataclass
class SyncConfig:
    """文件同步配置"""
    direction: str = "bidirectional"
    conflict_resolution: str = "manual"
    auto_sync_interval_minutes: int = 0
    remote_dir: str = ""  # 手机端同步路径


@dataclass
class AppConfig:
    """应用全局配置"""
    music_dirs: list[str] = field(default_factory=list)
    video_dirs: list[str] = field(default_factory=list)
    video_time_offsets: dict[str, int] = field(default_factory=dict)
    output_lrc_dir: Optional[str] = None   # None=与音频同目录
    asr: ASRConfig = field(default_factory=ASRConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    
    # API Keys（建议通过环境变量设置，这里提供默认值）
    groq_api_key: str = ""
    xunfei_api_key: str = ""
    
    def __post_init__(self):
        # 从环境变量读取 API Key
        if not self.groq_api_key:
            self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        if not self.xunfei_api_key:
            self.xunfei_api_key = os.environ.get("XUNFEI_API_KEY", "")


class ConfigManager:
    """配置管理器：加载/保存 JSON 配置文件"""
    
    DEFAULT_CONFIG_PATH = Path.home() / ".music-lyrics-sync" / "config.json"
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = AppConfig()
        self._loaded = False
    
    def load(self) -> AppConfig:
        """加载配置，如果文件不存在则使用默认值"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._deserialize(data)
            except (json.JSONDecodeError, KeyError):
                pass  # 配置损坏，使用默认值
        self._loaded = True
        return self.config
    
    def save(self):
        """保存配置到文件"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._serialize()
        temp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(self.config_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    
    def _serialize(self) -> dict:
        c = self.config
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "music_dirs": c.music_dirs,
            "video_dirs": c.video_dirs,
            "video_time_offsets": c.video_time_offsets,
            "output_lrc_dir": c.output_lrc_dir,
            "groq_api_key": c.groq_api_key,
            "xunfei_api_key": c.xunfei_api_key,
            "asr": {
                "provider": c.asr.provider,
                "local_model": c.asr.local_model,
                "language": c.asr.language,
                "use_vocal_separation": c.asr.use_vocal_separation,
                "use_gpu": c.asr.use_gpu,
            },
            "sync": {
                "direction": c.sync.direction,
                "conflict_resolution": c.sync.conflict_resolution,
                "auto_sync_interval_minutes": c.sync.auto_sync_interval_minutes,
                "remote_dir": c.sync.remote_dir,
            },
        }
    
    def _deserialize(self, data: dict):
        c = self.config
        c.music_dirs = data.get("music_dirs", [])
        c.video_dirs = [value for value in data.get("video_dirs", []) if isinstance(value, str)]
        offsets = data.get("video_time_offsets", {})
        c.video_time_offsets = {
            key: value
            for key, value in offsets.items()
            if isinstance(key, str) and isinstance(value, int)
        } if isinstance(offsets, dict) else {}
        c.output_lrc_dir = data.get("output_lrc_dir")
        c.groq_api_key = os.environ.get("GROQ_API_KEY") or data.get("groq_api_key", "")
        c.xunfei_api_key = os.environ.get("XUNFEI_API_KEY") or data.get("xunfei_api_key", "")
        asr_data = data.get("asr", {})
        c.asr.provider = asr_data.get("provider", "groq")
        c.asr.local_model = asr_data.get("local_model", "base")
        c.asr.language = asr_data.get("language")
        c.asr.use_vocal_separation = asr_data.get("use_vocal_separation", False)
        c.asr.use_gpu = asr_data.get("use_gpu", False)
        sync_data = data.get("sync", {})
        c.sync.direction = sync_data.get("direction", "bidirectional")
        c.sync.conflict_resolution = sync_data.get("conflict_resolution", "manual")
        c.sync.auto_sync_interval_minutes = sync_data.get("auto_sync_interval_minutes", 0)
        c.sync.remote_dir = sync_data.get("remote_dir", "")


def update_config_value(config: AppConfig, key: str, value: str) -> None:
    """Validate and update one CLI-addressable configuration value."""
    if key == "asr.provider":
        if value not in SUPPORTED_PROVIDERS:
            raise ValueError(f"不支持的 Provider: {value}")
        config.asr.provider = value
    elif key == "asr.local_model":
        if value not in SUPPORTED_LOCAL_MODELS:
            raise ValueError(f"不支持的本地模型: {value}")
        config.asr.local_model = value
    elif key == "asr.language":
        normalized = value.lower()
        if normalized in {"none", "null", "auto"}:
            config.asr.language = None
        elif normalized in SUPPORTED_LANGUAGES:
            config.asr.language = normalized
        else:
            raise ValueError(f"不支持的语言: {value}")
    elif key in {"asr.use_vocal_separation", "asr.use_gpu"}:
        normalized = value.lower()
        if normalized not in {"true", "1", "yes", "false", "0", "no"}:
            raise ValueError(f"无效的布尔值: {value}")
        setattr(config.asr, key.split(".", 1)[1], normalized in {"true", "1", "yes"})
    elif key == "output_lrc_dir":
        config.output_lrc_dir = None if value.lower() in {"none", "null"} else value
    elif key == "music_dirs":
        config.music_dirs = [value]
    elif key == "video_dirs":
        config.video_dirs = [value]
    elif key == "groq_api_key":
        config.groq_api_key = value
    elif key == "xunfei_api_key":
        config.xunfei_api_key = value
    else:
        raise ValueError(f"未知配置项: {key}")


# 全局单例
config_manager = ConfigManager()
