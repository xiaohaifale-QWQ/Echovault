"""
ASR 路由器

根据配置自动选择合适的 ASR Provider，支持自动回退。
"""

import logging
from typing import Optional, List

from .base import ASRProvider, TranscriptionResult

logger = logging.getLogger(__name__)

# 尝试导入 Groq Provider（可能未安装 groq 包）
try:
    from .groq_whisper import GroqWhisperProvider
    _HAS_GROQ = True
except ImportError:
    _HAS_GROQ = False
    GroqWhisperProvider = None

# 尝试导入本地 Whisper Provider
try:
    from .local_whisper import LocalWhisperProvider
    _HAS_LOCAL = True
except ImportError:
    _HAS_LOCAL = False
    LocalWhisperProvider = None


class ASRRouter:
    """
    ASR 路由器
    
    策略：
    1. 优先使用配置的 provider
    2. 如果不可用，按优先级自动回退
    3. 回退顺序: groq → local → aliyun → xunfei
    """
    
    # Provider 回退优先级
    FALLBACK_ORDER = ["groq", "local", "aliyun", "xunfei"]
    
    def __init__(self, config=None):
        """
        Args:
            config: AppConfig 实例（可选，用于初始化 Provider）
        """
        self._providers: dict[str, ASRProvider] = {}
        self._config = config
        
        # 注册内置 Provider
        if GroqWhisperProvider is not None:
            self.register(GroqWhisperProvider(
                api_key=config.groq_api_key if config else None
            ))
        else:
            logger.warning("Groq SDK 未安装，跳过 Groq Provider。安装: pip install groq")
        
        if LocalWhisperProvider is not None:
            model = config.asr.local_model if config else "base"
            use_gpu = config.asr.use_gpu if config else False
            self.register(LocalWhisperProvider(model_name=model, use_gpu=use_gpu))
        else:
            logger.warning("openai-whisper 未安装，跳过本地 Provider。安装: pip install openai-whisper")
    
    def register(self, provider: ASRProvider):
        """注册一个 Provider"""
        self._providers[provider.name] = provider
        logger.info(f"已注册 ASR Provider: {provider.display_name}")
    
    def get(self, name: str) -> Optional[ASRProvider]:
        """获取指定名称的 Provider"""
        return self._providers.get(name)
    
    def list_available(self) -> List[ASRProvider]:
        """列出所有可用的 Provider"""
        return [p for p in self._providers.values() if p.is_available()]
    
    def transcribe(
        self,
        audio_path: str,
        provider_name: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        使用指定的 Provider 转录音频
        
        Args:
            audio_path: 音频文件路径
            provider_name: 指定 Provider，None = 使用配置的默认值
            language: 语言代码
        
        Returns:
            TranscriptionResult
        
        Raises:
            RuntimeError: Provider 不可用或识别失败
        """
        # 确定使用的 provider：显式指定 > 配置 > 报错
        name = provider_name or (self._config.asr.provider if self._config else None)
        if not name:
            # 没有配置，按优先级找第一个可用的
            for n in self.FALLBACK_ORDER:
                p = self._providers.get(n)
                if p and p.is_available():
                    name = n
                    break
            if not name:
                raise RuntimeError("没有可用的 ASR Provider")
        
        provider = self._providers.get(name)
        if provider is None:
            raise RuntimeError(
                f"Provider '{name}' 未注册。\n"
                f"可用: {[p.display_name for p in self._providers.values()]}"
            )
        if not provider.is_available():
            raise RuntimeError(
                f"Provider '{provider.display_name}' 不可用。\n"
                f"请检查配置（API Key、模型文件等）。"
            )
        
        logger.info(f"使用 Provider: {provider.display_name}")
        return provider.transcribe(audio_path, language=language)


# 全局路由器实例（延迟初始化）
_router: Optional[ASRRouter] = None


def get_router(config=None) -> ASRRouter:
    global _router
    if config is not None or _router is None:
        _router = ASRRouter(config)
    return _router
