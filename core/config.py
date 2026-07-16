"""
配置管理模块
管理 API Key、模型选择、路径等全局配置。
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CONFIG_SCHEMA_VERSION = 8
SUPPORTED_AI_PROVIDERS = {"online", "local"}
SUPPORTED_TRANSLATION_ENGINES = {"ai", "local"}
SUPPORTED_PROVIDERS = {"groq", "local", "xunfei"}
SUPPORTED_LOCAL_MODELS = {"tiny", "base", "small", "medium", "large"}
SUPPORTED_SEPARATION_MODELS = {"htdemucs", "htdemucs_ft", "mdx_extra_q"}
SUPPORTED_LANGUAGES = {"zh", "en", "ja", "ko"}
SUPPORTED_TRANSLATION_SOURCE_LANGUAGES = SUPPORTED_LANGUAGES | {"auto"}


@dataclass
class ASRConfig:
    """ASR 识别配置"""
    provider: str = "groq"           # groq | local | aliyun | xunfei
    local_model: str = "base"        # tiny | base | small | medium（仅 local provider）
    language: Optional[str] = None   # None=自动检测, "zh"=中文, "en"=英语, "ja"=日语, "ko"=韩语
    use_vocal_separation: bool = False  # 是否启用 Demucs 人声分离
    use_gpu: bool = False               # 是否启用 GPU 加速（默认 CPU）
    vocal_separation_model: str = "htdemucs"
    vocal_separation_use_gpu: bool = False


@dataclass
class SyncConfig:
    """文件同步配置"""
    direction: str = "bidirectional"
    conflict_resolution: str = "manual"
    auto_sync_interval_minutes: int = 0
    remote_dir: str = ""  # 手机端同步路径


@dataclass
class TransferConfig:
    """手机 LocalSend 接收、任务和回传配置。"""

    receive_dir: str = ""
    outbox_dir: str = ""
    auto_start_receiver: bool = False
    device_alias: str = "Echovault"
    concurrent_uploads: int = 2
    strict_hash: bool = True
    keep_session_days: int = 30


@dataclass
class AppConfig:
    """应用全局配置"""
    music_dirs: list[str] = field(default_factory=list)
    video_dirs: list[str] = field(default_factory=list)
    music_select_all: bool = False
    video_select_all: bool = False
    video_time_offsets: dict[str, int] = field(default_factory=dict)
    output_lrc_dir: Optional[str] = None   # None=与音频同目录
    asr: ASRConfig = field(default_factory=ASRConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    transfer: TransferConfig = field(default_factory=TransferConfig)

    # API Keys（建议通过环境变量设置，这里提供默认值）
    groq_api_key: str = ""
    groq_proxy_url: str = ""
    xunfei_app_id: str = ""
    xunfei_api_key: str = ""
    xunfei_api_secret: str = ""
    ai_model_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com"
    ai_model_name: str = "deepseek-chat"
    ai_provider: str = "online"
    local_ai_base_url: str = "http://127.0.0.1:11434/v1"
    local_ai_model_name: str = ""
    local_ai_api_key: str = ""
    translation_engine: str = "ai"
    translation_source_language: str = "auto"
    translation_target_language: str = "zh"
    voice_input_shortcut: str = "Ctrl+Shift+Space"

    def __post_init__(self):
        # 从环境变量读取 API Key
        if not self.groq_api_key:
            self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        if not self.xunfei_api_key:
            self.xunfei_api_key = os.environ.get("XUNFEI_API_KEY", "")
        if not self.xunfei_app_id:
            self.xunfei_app_id = os.environ.get("XUNFEI_APP_ID", "")
        if not self.xunfei_api_secret:
            self.xunfei_api_secret = os.environ.get("XUNFEI_API_SECRET", "")
        if not self.ai_model_api_key:
            self.ai_model_api_key = os.environ.get("ECHOVAULT_AI_API_KEY", "")
        if not self.local_ai_api_key:
            self.local_ai_api_key = os.environ.get("ECHOVAULT_LOCAL_AI_API_KEY", "")
        self.local_ai_base_url = os.environ.get(
            "ECHOVAULT_LOCAL_AI_BASE_URL", self.local_ai_base_url
        )
        self.local_ai_model_name = os.environ.get(
            "ECHOVAULT_LOCAL_AI_MODEL", self.local_ai_model_name
        )

    @property
    def has_xunfei_credentials(self) -> bool:
        """讯飞 WebAPI 需要同时具备 AppID、API Key 与 API Secret。"""
        return bool(self.xunfei_app_id and self.xunfei_api_key and self.xunfei_api_secret)


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
            "music_select_all": c.music_select_all,
            "video_select_all": c.video_select_all,
            "video_time_offsets": c.video_time_offsets,
            "output_lrc_dir": c.output_lrc_dir,
            "groq_api_key": c.groq_api_key,
            "groq_proxy_url": c.groq_proxy_url,
            "xunfei_app_id": c.xunfei_app_id,
            "xunfei_api_key": c.xunfei_api_key,
            "xunfei_api_secret": c.xunfei_api_secret,
            "ai_model_api_key": c.ai_model_api_key,
            "ai_base_url": c.ai_base_url,
            "ai_model_name": c.ai_model_name,
            "ai_provider": c.ai_provider,
            "local_ai_base_url": c.local_ai_base_url,
            "local_ai_model_name": c.local_ai_model_name,
            "local_ai_api_key": c.local_ai_api_key,
            "translation_engine": c.translation_engine,
            "translation_source_language": c.translation_source_language,
            "translation_target_language": c.translation_target_language,
            "voice_input_shortcut": c.voice_input_shortcut,
            "asr": {
                "provider": c.asr.provider,
                "local_model": c.asr.local_model,
                "language": c.asr.language,
                "use_vocal_separation": c.asr.use_vocal_separation,
                "use_gpu": c.asr.use_gpu,
                "vocal_separation_model": c.asr.vocal_separation_model,
                "vocal_separation_use_gpu": c.asr.vocal_separation_use_gpu,
            },
            "sync": {
                "direction": c.sync.direction,
                "conflict_resolution": c.sync.conflict_resolution,
                "auto_sync_interval_minutes": c.sync.auto_sync_interval_minutes,
                "remote_dir": c.sync.remote_dir,
            },
            "transfer": {
                "receive_dir": c.transfer.receive_dir,
                "outbox_dir": c.transfer.outbox_dir,
                "auto_start_receiver": c.transfer.auto_start_receiver,
                "device_alias": c.transfer.device_alias,
                "concurrent_uploads": c.transfer.concurrent_uploads,
                "strict_hash": c.transfer.strict_hash,
                "keep_session_days": c.transfer.keep_session_days,
            },
        }

    def _deserialize(self, data: dict):
        c = self.config
        c.music_dirs = data.get("music_dirs", [])
        c.video_dirs = [value for value in data.get("video_dirs", []) if isinstance(value, str)]
        c.music_select_all = bool(data.get("music_select_all", False))
        c.video_select_all = bool(data.get("video_select_all", False))
        offsets = data.get("video_time_offsets", {})
        c.video_time_offsets = {
            key: value
            for key, value in offsets.items()
            if isinstance(key, str) and isinstance(value, int)
        } if isinstance(offsets, dict) else {}
        c.output_lrc_dir = data.get("output_lrc_dir")
        c.groq_api_key = os.environ.get("GROQ_API_KEY") or data.get("groq_api_key", "")
        c.groq_proxy_url = data.get("groq_proxy_url", "")
        c.xunfei_app_id = os.environ.get("XUNFEI_APP_ID") or data.get("xunfei_app_id", "")
        c.xunfei_api_key = os.environ.get("XUNFEI_API_KEY") or data.get("xunfei_api_key", "")
        c.xunfei_api_secret = os.environ.get("XUNFEI_API_SECRET") or data.get(
            "xunfei_api_secret", ""
        )
        c.ai_model_api_key = os.environ.get("ECHOVAULT_AI_API_KEY") or data.get(
            "ai_model_api_key", ""
        )
        c.ai_base_url = data.get("ai_base_url", "https://api.deepseek.com")
        c.ai_model_name = data.get("ai_model_name", "deepseek-chat")
        ai_provider = data.get("ai_provider", "online")
        c.ai_provider = ai_provider if ai_provider in SUPPORTED_AI_PROVIDERS else "online"
        c.local_ai_base_url = os.environ.get("ECHOVAULT_LOCAL_AI_BASE_URL") or data.get(
            "local_ai_base_url", "http://127.0.0.1:11434/v1"
        )
        c.local_ai_model_name = os.environ.get("ECHOVAULT_LOCAL_AI_MODEL") or data.get(
            "local_ai_model_name", ""
        )
        c.local_ai_api_key = os.environ.get("ECHOVAULT_LOCAL_AI_API_KEY") or data.get(
            "local_ai_api_key", ""
        )
        translation_engine = data.get("translation_engine", "ai")
        c.translation_engine = (
            translation_engine if translation_engine in SUPPORTED_TRANSLATION_ENGINES else "ai"
        )
        source_language = data.get("translation_source_language", "auto")
        target_language = data.get("translation_target_language", "zh")
        c.translation_source_language = (
            source_language
            if source_language in SUPPORTED_TRANSLATION_SOURCE_LANGUAGES
            else "auto"
        )
        c.translation_target_language = (
            target_language if target_language in SUPPORTED_LANGUAGES else "zh"
        )
        shortcut = data.get("voice_input_shortcut", "Ctrl+Shift+Space")
        c.voice_input_shortcut = shortcut if isinstance(shortcut, str) else "Ctrl+Shift+Space"
        asr_data = data.get("asr", {})
        c.asr.provider = asr_data.get("provider", "groq")
        c.asr.local_model = asr_data.get("local_model", "base")
        c.asr.language = asr_data.get("language")
        c.asr.use_vocal_separation = asr_data.get("use_vocal_separation", False)
        c.asr.use_gpu = asr_data.get("use_gpu", False)
        separation_model = asr_data.get("vocal_separation_model", "htdemucs")
        c.asr.vocal_separation_model = (
            separation_model
            if separation_model in SUPPORTED_SEPARATION_MODELS
            else "htdemucs"
        )
        c.asr.vocal_separation_use_gpu = bool(
            asr_data.get("vocal_separation_use_gpu", False)
        )
        sync_data = data.get("sync", {})
        c.sync.direction = sync_data.get("direction", "bidirectional")
        c.sync.conflict_resolution = sync_data.get("conflict_resolution", "manual")
        c.sync.auto_sync_interval_minutes = sync_data.get("auto_sync_interval_minutes", 0)
        c.sync.remote_dir = sync_data.get("remote_dir", "")
        transfer_data = data.get("transfer", {})
        c.transfer.receive_dir = str(transfer_data.get("receive_dir", ""))
        c.transfer.outbox_dir = str(transfer_data.get("outbox_dir", ""))
        c.transfer.auto_start_receiver = bool(
            transfer_data.get("auto_start_receiver", False)
        )
        c.transfer.device_alias = str(transfer_data.get("device_alias", "Echovault"))
        c.transfer.concurrent_uploads = max(
            1, min(4, int(transfer_data.get("concurrent_uploads", 2)))
        )
        c.transfer.strict_hash = bool(transfer_data.get("strict_hash", True))
        c.transfer.keep_session_days = max(
            1, int(transfer_data.get("keep_session_days", 30))
        )


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
    elif key == "asr.vocal_separation_model":
        if value not in SUPPORTED_SEPARATION_MODELS:
            raise ValueError(f"不支持的人声分离模型: {value}")
        config.asr.vocal_separation_model = value
    elif key in {
        "asr.use_vocal_separation",
        "asr.use_gpu",
        "asr.vocal_separation_use_gpu",
    }:
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
    elif key == "groq_proxy_url":
        config.groq_proxy_url = value
    elif key == "xunfei_api_key":
        config.xunfei_api_key = value
    elif key == "xunfei_app_id":
        config.xunfei_app_id = value
    elif key == "xunfei_api_secret":
        config.xunfei_api_secret = value
    elif key == "ai_model_api_key":
        config.ai_model_api_key = value
    elif key == "ai_base_url":
        config.ai_base_url = value.rstrip("/")
    elif key == "ai_model_name":
        config.ai_model_name = value
    elif key == "ai_provider":
        if value not in SUPPORTED_AI_PROVIDERS:
            raise ValueError(f"不支持的 AI Provider: {value}")
        config.ai_provider = value
    elif key == "local_ai_base_url":
        config.local_ai_base_url = value.rstrip("/")
    elif key == "local_ai_model_name":
        config.local_ai_model_name = value
    elif key == "local_ai_api_key":
        config.local_ai_api_key = value
    elif key == "translation_engine":
        if value not in SUPPORTED_TRANSLATION_ENGINES:
            raise ValueError(f"不支持的翻译引擎: {value}")
        config.translation_engine = value
    elif key == "translation_source_language":
        if value not in SUPPORTED_TRANSLATION_SOURCE_LANGUAGES:
            raise ValueError(f"不支持的翻译语言: {value}")
        setattr(config, key, value)
    elif key == "translation_target_language":
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"不支持的翻译语言: {value}")
        setattr(config, key, value)
    elif key == "voice_input_shortcut":
        config.voice_input_shortcut = value
    else:
        raise ValueError(f"未知配置项: {key}")


# 全局单例
config_manager = ConfigManager()
