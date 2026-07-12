"""
ASR Provider 抽象接口

所有语音识别后端都必须实现此接口，实现可插拔的 Provider 架构。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Segment:
    """识别结果的一段文本（带时间戳）"""
    start_time: float       # 开始时间（秒）
    end_time: float         # 结束时间（秒）
    text: str               # 识别的文本
    confidence: float = 1.0 # 置信度 0.0 ~ 1.0


@dataclass
class TranscriptionResult:
    """完整的识别结果"""
    segments: List[Segment] = field(default_factory=list)
    language: str = "unknown"
    duration: float = 0.0       # 音频总时长（秒）
    
    @property
    def full_text(self) -> str:
        """获取完整文本（不带时间戳）"""
        return "".join(seg.text for seg in self.segments)
    
    @property
    def is_empty(self) -> bool:
        return len(self.segments) == 0


class ASRProvider(ABC):
    """ASR Provider 抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称，如 'groq', 'local_whisper'"""
        ...
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """显示名称，如 'Groq Whisper (云端)'"""
        ...
    
    @abstractmethod
    def transcribe(self, audio_path: str, language: Optional[str] = None) -> TranscriptionResult:
        """
        转录音频文件
        
        Args:
            audio_path: 音频文件路径（建议 16kHz mono WAV）
            language: 语言代码，None 表示自动检测
        
        Returns:
            TranscriptionResult: 识别结果
        
        Raises:
            FileNotFoundError: 音频文件不存在
            RuntimeError: 识别过程出错
        """
        ...
    
    def is_available(self) -> bool:
        """检查 Provider 当前是否可用（网络连接、API Key 等）"""
        return True
    
    def detect_language(self, audio_path: str) -> str:
        """
        检测音频语言（可选实现）
        默认通过 transcribe 的实现来检测
        """
        result = self.transcribe(audio_path)
        return result.language
