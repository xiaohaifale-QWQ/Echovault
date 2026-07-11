"""
配置管理模块
管理 API Key、模型选择、路径等全局配置。
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ASRConfig:
    """ASR 识别配置"""
    provider: str = "groq"           # groq | local | aliyun | xunfei
    local_model: str = "base"        # tiny | base | small | medium（仅 local provider）
    language: Optional[str] = None   # None=自动检测, "zh"=中文, "en"=英语, "ja"=日语, "ko"=韩语
    use_vocal_separation: bool = False  # 是否启用 Demucs 人声分离


@dataclass
class SyncConfig:
    """文件同步配置"""
    direction: str = "bidirectional"  # a_to_b | b_to_a | bidirectional | mirror_a_to_b
    conflict_resolution: str = "manual"  # newest | manual | skip
    auto_sync_interval_minutes: int = 0  # 0=手动触发


@dataclass
class AppConfig:
    """应用全局配置"""
    music_dirs: list[str] = field(default_factory=list)
    output_lrc_dir: Optional[str] = None   # None=与音频同目录
    asr: ASRConfig = field(default_factory=ASRConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    
    # API Keys（建议通过环境变量设置，这里提供默认值）
    groq_api_key: str = ""
    
    def __post_init__(self):
        # 从环境变量读取 API Key
        if not self.groq_api_key:
            self.groq_api_key = os.environ.get("GROQ_API_KEY", "")


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
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _serialize(self) -> dict:
        c = self.config
        return {
            "music_dirs": c.music_dirs,
            "output_lrc_dir": c.output_lrc_dir,
            "asr": {
                "provider": c.asr.provider,
                "local_model": c.asr.local_model,
                "language": c.asr.language,
                "use_vocal_separation": c.asr.use_vocal_separation,
            },
            "sync": {
                "direction": c.sync.direction,
                "conflict_resolution": c.sync.conflict_resolution,
                "auto_sync_interval_minutes": c.sync.auto_sync_interval_minutes,
            },
        }
    
    def _deserialize(self, data: dict):
        c = self.config
        c.music_dirs = data.get("music_dirs", [])
        c.output_lrc_dir = data.get("output_lrc_dir")
        asr_data = data.get("asr", {})
        c.asr.provider = asr_data.get("provider", "groq")
        c.asr.local_model = asr_data.get("local_model", "base")
        c.asr.language = asr_data.get("language")
        c.asr.use_vocal_separation = asr_data.get("use_vocal_separation", False)
        sync_data = data.get("sync", {})
        c.sync.direction = sync_data.get("direction", "bidirectional")
        c.sync.conflict_resolution = sync_data.get("conflict_resolution", "manual")
        c.sync.auto_sync_interval_minutes = sync_data.get("auto_sync_interval_minutes", 0)


# 全局单例
config_manager = ConfigManager()
