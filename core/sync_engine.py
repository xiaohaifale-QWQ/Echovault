"""
文件同步引擎

核心功能:
- 扫描本地目录，生成文件清单
- 对比两个目录的差异
- 执行同步操作（复制、覆盖、冲突处理）
"""

import os
import hashlib
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class SyncDirection(Enum):
    A_TO_B = "a_to_b"
    B_TO_A = "b_to_a"
    BIDIRECTIONAL = "bidirectional"
    MIRROR_A_TO_B = "mirror_a_to_b"


class ConflictResolution(Enum):
    NEWEST = "newest"
    MANUAL = "manual"
    SKIP = "skip"


class DiffType(Enum):
    ONLY_IN_A = "only_in_a"          # 仅在 A 中存在
    ONLY_IN_B = "only_in_b"          # 仅在 B 中存在
    NEWER_IN_A = "newer_in_a"        # A 更新
    NEWER_IN_B = "newer_in_b"        # B 更新
    SAME = "same"                     # 相同
    CONFLICT = "conflict"            # 冲突（两边都更新了）


@dataclass
class FileInfo:
    """文件信息"""
    relative_path: str    # 相对于根目录的路径
    size: int
    mtime: float          # 修改时间戳
    md5: Optional[str] = None  # MD5 哈希（按需计算）
    
    def compute_md5(self, root_dir: str) -> str:
        """计算文件 MD5"""
        if self.md5 is None:
            full_path = os.path.join(root_dir, self.relative_path)
            h = hashlib.md5()
            with open(full_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            self.md5 = h.hexdigest()
        return self.md5


@dataclass
class FileDiff:
    """文件差异"""
    file: FileInfo
    diff_type: DiffType
    
    # 对方文件信息（如果存在）
    other_file: Optional[FileInfo] = None
    
    def __repr__(self):
        return f"FileDiff({self.file.relative_path}, {self.diff_type.value})"


@dataclass
class SyncPlan:
    """同步计划"""
    direction: SyncDirection
    files_to_copy: List[tuple[str, str]] = field(default_factory=list)  # (source, dest)
    files_to_delete: List[str] = field(default_factory=list)
    files_with_conflict: List[FileDiff] = field(default_factory=list)
    total_bytes: int = 0
    
    @property
    def total_operations(self) -> int:
        return len(self.files_to_copy) + len(self.files_to_delete) + len(self.files_with_conflict)
    
    @property
    def is_empty(self) -> bool:
        return self.total_operations == 0


class SyncEngine:
    """文件同步引擎"""
    
    # 支持同步的文件扩展名
    SYNC_EXTENSIONS = {
        # 音频
        ".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".ape", ".wv",
        # 歌词
        ".lrc", ".txt",
        # 封面
        ".jpg", ".jpeg", ".png", ".webp",
    }
    
    def __init__(self, conflict_resolution: ConflictResolution = ConflictResolution.MANUAL):
        self.conflict_resolution = conflict_resolution
    
    def scan_directory(self, root_dir: str) -> Dict[str, FileInfo]:
        """
        扫描目录，生成文件清单
        
        Returns:
            dict: {relative_path: FileInfo}
        """
        files = {}
        root = Path(root_dir)
        
        if not root.exists():
            return files
        
        for entry in root.rglob("*"):
            if entry.is_file() and entry.suffix.lower() in self.SYNC_EXTENSIONS:
                rel_path = str(entry.relative_to(root))
                stat = entry.stat()
                files[rel_path] = FileInfo(
                    relative_path=rel_path,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
        
        return files
    
    def compare_directories(
        self,
        dir_a: str,
        dir_b: str,
        compare_content: bool = False,
    ) -> List[FileDiff]:
        """
        对比两个目录
        
        Args:
            dir_a: 目录 A
            dir_b: 目录 B
            compare_content: 是否计算 MD5（慢但精确）
        
        Returns:
            List[FileDiff]: 差异列表
        """
        files_a = self.scan_directory(dir_a)
        files_b = self.scan_directory(dir_b)
        
        all_paths = set(files_a.keys()) | set(files_b.keys())
        diffs = []
        
        for path in sorted(all_paths):
            info_a = files_a.get(path)
            info_b = files_b.get(path)
            
            if info_a and not info_b:
                # 仅在 A 中
                diffs.append(FileDiff(info_a, DiffType.ONLY_IN_A))
            
            elif info_b and not info_a:
                # 仅在 B 中
                diffs.append(FileDiff(info_b, DiffType.ONLY_IN_B))
            
            else:
                # 两边都有，比较修改时间
                if info_a.mtime > info_b.mtime + 1:  # 1秒容差
                    diffs.append(FileDiff(info_a, DiffType.NEWER_IN_A, other_file=info_b))
                elif info_b.mtime > info_a.mtime + 1:
                    diffs.append(FileDiff(info_b, DiffType.NEWER_IN_B, other_file=info_a))
                else:
                    # 时间接近但大小不同，必须视为冲突，不能静默忽略。
                    if info_a.size != info_b.size:
                        diffs.append(FileDiff(info_a, DiffType.CONFLICT, other_file=info_b))
                    elif compare_content:
                        # 大小和时间都接近时，严格模式再计算内容哈希。
                        md5_a = info_a.compute_md5(dir_a)
                        md5_b = info_b.compute_md5(dir_b)
                        if md5_a != md5_b:
                            diffs.append(FileDiff(info_a, DiffType.CONFLICT, other_file=info_b))
                        # else: 完全相同，不加入差异
        
        return diffs
    
    def create_plan(
        self,
        diffs: List[FileDiff],
        direction: SyncDirection,
        dir_a: str,
        dir_b: str,
    ) -> SyncPlan:
        """
        根据差异和同步方向生成同步计划
        
        Args:
            diffs: 差异列表
            direction: 同步方向
            dir_a: 目录 A 的绝对路径
            dir_b: 目录 B 的绝对路径
        
        Returns:
            SyncPlan: 同步计划
        """
        plan = SyncPlan(direction=direction)
        
        for diff in diffs:
            if direction == SyncDirection.A_TO_B:
                self._plan_a_to_b(diff, dir_a, dir_b, plan)
            elif direction == SyncDirection.B_TO_A:
                self._plan_b_to_a(diff, dir_a, dir_b, plan)
            elif direction == SyncDirection.BIDIRECTIONAL:
                self._plan_bidirectional(diff, dir_a, dir_b, plan)
            elif direction == SyncDirection.MIRROR_A_TO_B:
                self._plan_mirror(diff, dir_a, dir_b, plan)
        
        return plan
    
    def _plan_a_to_b(self, diff: FileDiff, dir_a: str, dir_b: str, plan: SyncPlan):
        """A → B 单向同步"""
        if diff.diff_type == DiffType.ONLY_IN_A:
            # A 有 B 没有 → 复制到 B
            src = os.path.join(dir_a, diff.file.relative_path)
            dst = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.NEWER_IN_A:
            # A 更新 → 覆盖 B
            src = os.path.join(dir_a, diff.file.relative_path)
            dst = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.NEWER_IN_B:
            # B 更新，单向 A→B 时忽略
            pass
        
        elif diff.diff_type == DiffType.CONFLICT:
            plan.files_with_conflict.append(diff)
    
    def _plan_b_to_a(self, diff: FileDiff, dir_a: str, dir_b: str, plan: SyncPlan):
        """B → A 单向同步（与 A→B 对称）"""
        if diff.diff_type == DiffType.ONLY_IN_B:
            src = os.path.join(dir_b, diff.file.relative_path)
            dst = os.path.join(dir_a, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.NEWER_IN_B:
            src = os.path.join(dir_b, diff.file.relative_path)
            dst = os.path.join(dir_a, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
    
    def _plan_bidirectional(self, diff: FileDiff, dir_a: str, dir_b: str, plan: SyncPlan):
        """双向合并同步"""
        if diff.diff_type == DiffType.ONLY_IN_A:
            src = os.path.join(dir_a, diff.file.relative_path)
            dst = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.ONLY_IN_B:
            src = os.path.join(dir_b, diff.file.relative_path)
            dst = os.path.join(dir_a, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.NEWER_IN_A:
            src = os.path.join(dir_a, diff.file.relative_path)
            dst = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.NEWER_IN_B:
            src = os.path.join(dir_b, diff.file.relative_path)
            dst = os.path.join(dir_a, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.CONFLICT:
            plan.files_with_conflict.append(diff)
    
    def _plan_mirror(self, diff: FileDiff, dir_a: str, dir_b: str, plan: SyncPlan):
        """镜像 A→B（B 完全等于 A）"""
        if diff.diff_type == DiffType.ONLY_IN_A:
            src = os.path.join(dir_a, diff.file.relative_path)
            dst = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        elif diff.diff_type == DiffType.ONLY_IN_B:
            # B 多出来的文件 → 删除
            full_path = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_delete.append(full_path)
        
        elif diff.diff_type == DiffType.NEWER_IN_A:
            src = os.path.join(dir_a, diff.file.relative_path)
            dst = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
        
        # B 比 A 新、冲突 → 都用 A 覆盖
        elif diff.diff_type in (DiffType.NEWER_IN_B, DiffType.CONFLICT):
            src = os.path.join(dir_a, diff.file.relative_path)
            dst = os.path.join(dir_b, diff.file.relative_path)
            plan.files_to_copy.append((src, dst))
            plan.total_bytes += diff.file.size
    
    def execute_plan(
        self,
        plan: SyncPlan,
        progress_callback=None,
    ) -> Dict[str, int]:
        """
        执行同步计划
        
        Args:
            plan: 同步计划
            progress_callback: 进度回调 (current: int, total: int, filename: str)
        
        Returns:
            dict: {"copied": int, "deleted": int, "skipped": int, "errors": int}
        """
        stats = {"copied": 0, "deleted": 0, "skipped": 0, "errors": 0}
        total = plan.total_operations
        current = 0
        
        # 先处理冲突
        for conflict in plan.files_with_conflict:
            # 冲突没有可靠的自动胜出方。MANUAL 应由调用方在执行前处理；
            # 如果仍传入执行器，安全起见统一跳过而不是覆盖任一侧。
            stats["skipped"] += 1
            current += 1
            if progress_callback:
                progress_callback(current, total, conflict.file.relative_path)
        
        # 复制文件
        for src, dst in plan.files_to_copy:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)  # copy2 保留元数据
                stats["copied"] += 1
            except Exception as e:
                logger.error(f"复制失败: {src} -> {dst}: {e}")
                stats["errors"] += 1
            
            current += 1
            if progress_callback:
                progress_callback(current, total, os.path.basename(src))
        
        # 删除文件（仅镜像模式）
        for path in plan.files_to_delete:
            try:
                os.remove(path)
                stats["deleted"] += 1
            except Exception as e:
                logger.error(f"删除失败: {path}: {e}")
                stats["errors"] += 1
            
            current += 1
            if progress_callback:
                progress_callback(current, total, os.path.basename(path))
        
        return stats
