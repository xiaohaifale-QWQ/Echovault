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
            self.register(LocalWhisperProvider(model_name=model))
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
        使用最佳可用的 Provider 转录音频
        
        Args:
            audio_path: 音频文件路径
            provider_name: 指定 Provider，None = 使用配置的默认值
            language: 语言代码
        
        Returns:
            TranscriptionResult
        
        Raises:
            RuntimeError: 所有 Provider 都不可用
        """
        # 确定尝试顺序
        if provider_name:
            candidates = [provider_name]
        elif self._config:
            candidates = [self._config.asr.provider] + [
                p for p in self.FALLBACK_ORDER if p != self._config.asr.provider
            ]
        else:
            candidates = self.FALLBACK_ORDER.copy()
        
        last_error = None
        for name in candidates:
            provider = self._providers.get(name)
            if provider is None:
                continue
            if not provider.is_available():
                logger.info(f"Provider '{name}' 不可用，尝试下一个...")
                continue
            
            try:
                logger.info(f"使用 Provider: {provider.display_name}")
                return provider.transcribe(audio_path, language=language)
            except Exception as e:
                logger.warning(f"Provider '{name}' 失败: {e}")
                last_error = e
                continue
        
        raise RuntimeError(
            f"所有 ASR Provider 都不可用。最后错误: {last_error}\n"
            f"可用 Provider: {[p.display_name for p in self.list_available()]}"
        )


# 全局路由器实例（延迟初始化）
_router: Optional[ASRRouter] = None


def get_router(config=None) -> ASRRouter:
    global _router
    if config is not None or _router is None:
        _router = ASRRouter(config)
    return _router
