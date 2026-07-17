"""FFmpeg-backed audio editing operations used by the desktop editor."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.audio_utils import find_ffmpeg, get_audio_info
from core.metadata import write_tags
from core.process_utils import hidden_window_kwargs
from core.transfer_session import register_artifact

SUPPORTED_OUTPUT_SUFFIXES = {
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
}


@dataclass(frozen=True)
class AudioEditResult:
    outputs: list[str]
    message: str


def _codec_args(path: str | Path) -> list[str]:
    suffix = Path(path).suffix.lower()
    return {
        ".wav": ["-c:a", "pcm_s16le"],
        ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
        ".flac": ["-c:a", "flac"],
        ".m4a": ["-c:a", "aac", "-b:a", "256k"],
        ".aac": ["-c:a", "aac", "-b:a", "256k"],
        ".ogg": ["-c:a", "libvorbis", "-q:a", "5"],
        ".opus": ["-c:a", "libopus", "-b:a", "192k"],
    }.get(suffix, ["-c:a", "pcm_s16le"])


def _atempo_chain(speed: float) -> str:
    if speed <= 0:
        raise ValueError("速度必须大于 0。")
    values: list[float] = []
    remaining = speed
    while remaining > 2.0:
        values.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        values.append(0.5)
        remaining /= 0.5
    values.append(remaining)
    return ",".join(f"atempo={value:.6f}" for value in values)


def _require_inputs(inputs: list[str], count: int = 1) -> list[Path]:
    paths = [Path(value) for value in inputs if value]
    if len(paths) < count:
        raise ValueError(f"此功能至少需要 {count} 个输入文件。")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing[0])
    return paths


def _run_ffmpeg(args: list[str]) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法执行音频编辑。")
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-y", *args],
        capture_output=True,
        text=True,
        **hidden_window_kwargs(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "FFmpeg 音频处理失败。")


def _media_duration(path: Path) -> float:
    duration = float(get_audio_info(str(path)).get("duration") or 0.0)
    if duration <= 0:
        raise ValueError("无法读取有效的音频时长。")
    return duration


def _selection_input_args(path: Path, params: dict[str, Any]) -> list[str]:
    """Build an FFmpeg input limited to the editor's active time selection."""
    raw_start = params.get("selection_start")
    raw_end = params.get("selection_end")
    if raw_start is None or raw_end is None:
        return ["-i", str(path)]
    start = max(0.0, float(raw_start))
    end = float(raw_end)
    duration = _media_duration(path)
    end = min(duration, end)
    if end <= start:
        raise ValueError("选区终点必须大于起点。")
    if start >= duration:
        raise ValueError("选区起点不能超过音频总时长。")
    return ["-ss", f"{start:.3f}", "-i", str(path), "-t", f"{end - start:.3f}"]


def _atomic_single_output(args: list[str], output_path: str) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output.stem}-",
        suffix=output.suffix,
        dir=output.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    try:
        temp_path.unlink(missing_ok=True)
        _run_ffmpeg([*args, str(temp_path)])
        if not temp_path.is_file() or temp_path.stat().st_size == 0:
            raise RuntimeError("音频处理没有生成有效文件。")
        temp_path.replace(output)
    finally:
        temp_path.unlink(missing_ok=True)
    return str(output)


def _register(inputs: list[Path], outputs: list[str], operation: str) -> None:
    source = inputs[0]
    for output in outputs:
        register_artifact(source, output, f"audio_edit_{operation}")


def process_audio(
    operation: str,
    inputs: list[str],
    output_path: str,
    params: dict[str, Any] | None = None,
) -> AudioEditResult:
    """Execute one validated audio editing operation."""
    params = dict(params or {})
    minimum_inputs = 2 if operation in {"concat", "mix"} else 1
    paths = _require_inputs(inputs, minimum_inputs)
    output = Path(output_path)
    if not output.suffix:
        raise ValueError("输出文件必须包含音频格式扩展名。")
    if output.suffix.lower() not in SUPPORTED_OUTPUT_SUFFIXES:
        raise ValueError(f"不支持的输出格式：{output.suffix}")
    resolved_inputs = {path.resolve() for path in paths}
    if output.resolve() in resolved_inputs:
        raise ValueError("输出文件不能覆盖输入原文件。")
    if operation == "tags" and output.suffix.lower() != paths[0].suffix.lower():
        raise ValueError("标签编辑的输出格式必须与输入文件一致。")

    if operation == "extract":
        result = _atomic_single_output(
            ["-i", str(paths[0]), "-map", "0:a:0", "-vn", *_codec_args(output)],
            str(output),
        )
        outputs = [result]
    elif operation in {"trim", "edit"}:
        start = max(
            0.0,
            float(params.get("selection_start", params.get("start", 0.0))),
        )
        end = float(params.get("selection_end", params.get("end", 0.0)))
        if end and end <= start:
            raise ValueError("结束时间必须大于开始时间。")
        source_duration = _media_duration(paths[0])
        if start >= source_duration:
            raise ValueError("开始时间不能超过音频总时长。")
        if end > source_duration:
            end = source_duration
        filters: list[str] = []
        fade_in = max(0.0, float(params.get("fade_in", 0.0)))
        fade_out = max(0.0, float(params.get("fade_out", 0.0)))
        duration = end - start if end else source_duration - start
        if fade_in:
            filters.append(f"afade=t=in:st=0:d={min(fade_in, duration):.3f}")
        if fade_out:
            filters.append(
                f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:"
                f"d={min(fade_out, duration):.3f}"
            )
        args = ["-ss", f"{start:.3f}", "-i", str(paths[0])]
        if end:
            args.extend(["-t", f"{end - start:.3f}"])
        if filters:
            args.extend(["-af", ",".join(filters)])
        outputs = [_atomic_single_output([*args, *_codec_args(output)], str(output))]
    elif operation == "concat":
        args: list[str] = []
        chains: list[str] = []
        for index, path in enumerate(paths):
            args.extend(["-i", str(path)])
            chains.append(
                f"[{index}:a]aresample=44100,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo"
                f"[a{index}]"
            )
        joined = "".join(f"[a{index}]" for index in range(len(paths)))
        filter_graph = ";".join(chains + [f"{joined}concat=n={len(paths)}:v=0:a=1[out]"])
        outputs = [
            _atomic_single_output(
                [*args, "-filter_complex", filter_graph, "-map", "[out]", *_codec_args(output)],
                str(output),
            )
        ]
    elif operation == "mix":
        args = []
        chains = []
        volumes = params.get("volumes") or [1.0] * len(paths)
        for index, path in enumerate(paths):
            args.extend(["-i", str(path)])
            volume = float(volumes[index]) if index < len(volumes) else 1.0
            chains.append(
                f"[{index}:a]aresample=44100,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={volume:.4f}[a{index}]"
            )
        joined = "".join(f"[a{index}]" for index in range(len(paths)))
        filter_graph = ";".join(
            chains
            + [
                f"{joined}amix=inputs={len(paths)}:duration=longest:"
                "dropout_transition=2:normalize=0[out]"
            ]
        )
        outputs = [
            _atomic_single_output(
                [*args, "-filter_complex", filter_graph, "-map", "[out]", *_codec_args(output)],
                str(output),
            )
        ]
    elif operation == "fade":
        selection_start = params.get("selection_start")
        selection_end = params.get("selection_end")
        duration = (
            float(selection_end) - float(selection_start)
            if selection_start is not None and selection_end is not None
            else _media_duration(paths[0])
        )
        fade_in = max(0.0, float(params.get("fade_in", 2.0)))
        fade_out = max(0.0, float(params.get("fade_out", 2.0)))
        filters = [
            f"afade=t=in:st=0:d={min(fade_in, duration):.3f}",
            f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:"
            f"d={min(fade_out, duration):.3f}",
        ]
        outputs = [
            _atomic_single_output(
                [
                    *_selection_input_args(paths[0], params),
                    "-af",
                    ",".join(filters),
                    *_codec_args(output),
                ],
                str(output),
            )
        ]
    elif operation == "speed_pitch":
        speed = float(params.get("speed", 1.0))
        semitones = float(params.get("semitones", 0.0))
        sample_rate = int(get_audio_info(str(paths[0])).get("sample_rate") or 44100)
        pitch = 2 ** (semitones / 12.0)
        filters = [
            f"asetrate={sample_rate}*{pitch:.8f}",
            f"aresample={sample_rate}",
            _atempo_chain(speed / pitch),
        ]
        outputs = [
            _atomic_single_output(
                [
                    *_selection_input_args(paths[0], params),
                    "-af",
                    ",".join(filters),
                    *_codec_args(output),
                ],
                str(output),
            )
        ]
    elif operation == "denoise":
        noise_floor = min(-20.0, max(-80.0, float(params.get("noise_floor", -25.0))))
        outputs = [
            _atomic_single_output(
                [
                    *_selection_input_args(paths[0], params),
                    "-af",
                    f"afftdn=nf={noise_floor:.1f}",
                    *_codec_args(output),
                ],
                str(output),
            )
        ]
    elif operation == "normalize":
        target = min(-5.0, max(-30.0, float(params.get("target_lufs", -14.0))))
        peak = min(-0.1, max(-5.0, float(params.get("true_peak", -1.0))))
        loudnorm = f"loudnorm=I={target:.1f}:LRA=11:TP={peak:.1f}"
        outputs = [
            _atomic_single_output(
                [
                    *_selection_input_args(paths[0], params),
                    "-af",
                    loudnorm,
                    *_codec_args(output),
                ],
                str(output),
            )
        ]
    elif operation == "split":
        seconds = float(params.get("segment_seconds", 30.0))
        if seconds <= 0:
            raise ValueError("分段时长必须大于 0。")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{output.stem}-split-",
            dir=output.parent,
        ) as temp_dir:
            temp_pattern = Path(temp_dir) / f"{output.stem}_%03d{output.suffix}"
            _run_ffmpeg(
                [
                    *_selection_input_args(paths[0], params),
                    "-map",
                    "0:a:0",
                    *_codec_args(temp_pattern),
                    "-f",
                    "segment",
                    "-segment_time",
                    f"{seconds:.3f}",
                    "-reset_timestamps",
                    "1",
                    str(temp_pattern),
                ]
            )
            generated = sorted(Path(temp_dir).glob(f"{output.stem}_*{output.suffix}"))
            if not generated:
                raise RuntimeError("音频分割没有生成文件。")
            outputs = []
            for index, source in enumerate(generated):
                destination = output.with_name(
                    f"{output.stem}_{index:03d}{output.suffix}"
                )
                if destination.resolve() in resolved_inputs:
                    raise ValueError("分割结果会覆盖输入原文件，请修改输出文件名。")
                source.replace(destination)
                outputs.append(str(destination))
    elif operation == "equalizer":
        bass = float(params.get("bass", 0.0))
        middle = float(params.get("middle", 0.0))
        treble = float(params.get("treble", 0.0))
        filters = (
            f"bass=g={bass:.2f},"
            f"equalizer=f=1000:t=q:w=1:g={middle:.2f},"
            f"treble=g={treble:.2f}"
        )
        outputs = [
            _atomic_single_output(
                [
                    *_selection_input_args(paths[0], params),
                    "-af",
                    filters,
                    *_codec_args(output),
                ],
                str(output),
            )
        ]
    elif operation == "volume":
        gain_db = min(30.0, max(-60.0, float(params.get("gain_db", 0.0))))
        outputs = [
            _atomic_single_output(
                [
                    *_selection_input_args(paths[0], params),
                    "-af",
                    f"volume={gain_db:.2f}dB",
                    *_codec_args(output),
                ],
                str(output),
            )
        ]
    elif operation == "tags":
        output.parent.mkdir(parents=True, exist_ok=True)
        if paths[0].resolve() != output.resolve():
            shutil.copy2(paths[0], output)
        write_tags(str(output), params)
        outputs = [str(output)]
    elif operation == "reverse":
        outputs = [
            _atomic_single_output(
                ["-i", str(paths[0]), "-af", "areverse", *_codec_args(output)],
                str(output),
            )
        ]
    elif operation == "convert":
        channels = int(params.get("channels", 0))
        sample_rate = int(params.get("sample_rate", 0))
        args = ["-i", str(paths[0])]
        if channels in {1, 2}:
            args.extend(["-ac", str(channels)])
        if sample_rate > 0:
            args.extend(["-ar", str(sample_rate)])
        outputs = [_atomic_single_output([*args, *_codec_args(output)], str(output))]
    else:
        raise ValueError(f"未知音频编辑操作：{operation}")

    _register(paths, outputs, operation)
    return AudioEditResult(outputs, f"已生成 {len(outputs)} 个文件。")
