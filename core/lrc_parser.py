"""
LRC 歌词文件解析器

支持标准 LRC 格式和增强型 LRC 格式：
- 标准: [mm:ss.xx]歌词文本
- 增强: [mm:ss.xxx]歌词文本（毫秒级）
- 逐字: <mm:ss.xx>每个字<mm:ss.xx>每个字
- 元数据标签: [ti:标题] [ar:歌手] [al:专辑] [by:创建者] [offset:偏移]
"""

import re
from typing import List, Optional, Tuple


# LRC 时间戳正则: [mm:ss.xx] 或 [mm:ss.xxx]
_TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:\.(\d{2,3}))?\]")
# LRC 元数据标签: [label:value]
_METADATA_RE = re.compile(r"\[([a-zA-Z]+):(.*)\]")


def parse_timestamp(tag: str) -> float:
    """
    解析时间戳标签
    
    Args:
        tag: 如 "[01:23.45]" 或 "[01:23.456]"
    
    Returns:
        float: 秒数
    """
    m = _TIMESTAMP_RE.match(tag)
    if not m:
        raise ValueError(f"无效的时间戳: {tag}")
    
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    frac = m.group(3) or "00"
    
    # 百分秒或毫秒 → 秒的小数部分
    if len(frac) == 2:
        frac_sec = int(frac) / 100.0
    else:
        frac_sec = int(frac) / 1000.0
    
    return minutes * 60 + seconds + frac_sec


def format_timestamp(seconds: float, precision: str = "cs") -> str:
    """
    将秒数格式化为 LRC 时间戳
    
    Args:
        seconds: 秒数
        precision: "cs" = 百分秒 [mm:ss.xx], "ms" = 毫秒 [mm:ss.xxx]
    
    Returns:
        str: 格式化的时间戳，如 "[01:23.45]"
    """
    minutes = int(seconds // 60)
    secs = seconds % 60
    
    if precision == "ms":
        return f"[{minutes:02d}:{secs:06.3f}]"
    else:
        return f"[{minutes:02d}:{secs:05.2f}]"


class LyricLine:
    """一行歌词"""
    
    def __init__(self, timestamp: float, text: str):
        self.timestamp = timestamp
        self.text = text.strip()
    
    def __repr__(self):
        return f"LyricLine({self.timestamp:.2f}, '{self.text[:20]}...')" if len(self.text) > 20 else f"LyricLine({self.timestamp:.2f}, '{self.text}')"
    
    def to_lrc(self, precision: str = "cs") -> str:
        """输出为 LRC 格式字符串"""
        return f"{format_timestamp(self.timestamp, precision)}{self.text}"


class LRCFile:
    """LRC 文件表示"""
    
    def __init__(self):
        self.title: Optional[str] = None
        self.artist: Optional[str] = None
        self.album: Optional[str] = None
        self.by: Optional[str] = None
        self.offset: float = 0.0
        self.lines: List[LyricLine] = []
    
    @property
    def is_empty(self) -> bool:
        return len(self.lines) == 0
    
    def apply_offset(self, delta: float):
        """对所有歌词行应用时间偏移"""
        for line in self.lines:
            line.timestamp += delta
        self.offset += delta
    
    def to_string(self, precision: str = "cs") -> str:
        """输出为 LRC 文件内容"""
        parts = []
        
        # 元数据
        if self.title:
            parts.append(f"[ti:{self.title}]")
        if self.artist:
            parts.append(f"[ar:{self.artist}]")
        if self.album:
            parts.append(f"[al:{self.album}]")
        if self.by:
            parts.append(f"[by:{self.by}]")
        if self.offset != 0:
            parts.append(f"[offset:{int(self.offset * 1000)}]")
        
        if parts:
            parts.append("")  # 空行分隔
        
        # 歌词行（按时间排序）
        sorted_lines = sorted(self.lines, key=lambda l: l.timestamp)
        for line in sorted_lines:
            parts.append(line.to_lrc(precision))
        
        return "\n".join(parts)


def parse_lrc(content: str) -> LRCFile:
    """
    解析 LRC 文件内容
    
    Args:
        content: LRC 文件文本内容
    
    Returns:
        LRCFile: 解析后的 LRC 对象
    """
    lrc = LRCFile()
    
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        
        # 尝试匹配元数据标签
        meta_m = _METADATA_RE.match(line)
        if meta_m:
            tag, value = meta_m.group(1), meta_m.group(2).strip()
            if tag == "ti":
                lrc.title = value
            elif tag == "ar":
                lrc.artist = value
            elif tag == "al":
                lrc.album = value
            elif tag == "by":
                lrc.by = value
            elif tag == "offset":
                try:
                    lrc.offset = int(value) / 1000.0
                except ValueError:
                    pass
            continue
        
        # 尝试匹配时间戳标签
        ts_matches = list(_TIMESTAMP_RE.finditer(line))
        if not ts_matches:
            continue
        
        # 提取最后一个时间戳之后的文本
        last_ts_end = ts_matches[-1].end()
        text = line[last_ts_end:].strip()
        
        # 每个时间戳对应一行（支持 [mm:ss][mm:ss]同一歌词 的简写）
        for m in ts_matches:
            ts = parse_timestamp(m.group(0))
            lrc.lines.append(LyricLine(ts, text))
    
    return lrc


def parse_lrc_file(file_path: str) -> LRCFile:
    """从文件读取并解析 LRC"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return parse_lrc(content)
