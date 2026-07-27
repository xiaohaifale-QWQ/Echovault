import io
import json
import shutil
from pathlib import Path

import pytest

import core.audio_sources as audio_sources
from core.audio_sources import (
    download_audio,
    import_lx_source,
    parse_lx_source_metadata,
    resolve_download,
    search_source,
    suggested_filename,
    validate_source_config,
)
from core.output_paths import unique_output_path


class FakeResponse:
    def __init__(self, payload: bytes, content_length: bool = False):
        self.payload = io.BytesIO(payload)
        self.headers = {
            "Content-Length": str(len(payload))
        } if content_length else {}

    def read(self, size=-1):
        return self.payload.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def source():
    return {
        "id": "licensed-catalog",
        "name": "授权曲库",
        "base_url": "https://catalog.example",
        "search_path": "/search?q={query}",
        "resolve_path": "/tracks/{id}?quality={quality}",
        "qualities": ["128k", "320k", "flac"],
        "headers": {"Authorization": "Bearer demo"},
        "terms_url": "https://catalog.example/terms",
        "authorized": True,
        "enabled": True,
    }


def test_source_validation_requires_https_and_authorization():
    validated = validate_source_config(source())
    assert validated["id"] == "licensed-catalog"
    invalid = source()
    invalid["base_url"] = "http://remote.example"
    with pytest.raises(ValueError):
        validate_source_config(invalid)
    invalid = source()
    invalid["authorized"] = False
    with pytest.raises(ValueError):
        validate_source_config(invalid)


def test_search_and_resolve_follow_declarative_contract():
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, request.headers, timeout))
        if "/search?" in request.full_url:
            return FakeResponse(
                json.dumps(
                    {
                        "tracks": [
                            {
                                "id": "42",
                                "title": "海岸",
                                "artist": "Echo",
                                "album": "Blue",
                                "qualities": ["320k", "flac"],
                            }
                        ]
                    }
                ).encode()
            )
        return FakeResponse(
            json.dumps({"url": "https://cdn.example/42.flac"}).encode()
        )

    tracks = search_source(source(), "海 岸", opener=opener)
    assert tracks[0]["title"] == "海岸"
    assert "%E6%B5%B7%20%E5%B2%B8" in calls[0][0]
    url, headers = resolve_download(source(), tracks[0], "flac", opener=opener)
    assert url == "https://cdn.example/42.flac"
    assert headers["Authorization"] == "Bearer demo"


def test_download_and_output_paths_never_overwrite(tmp_path):
    source_file = tmp_path / "song.wav"
    source_file.write_bytes(b"source")
    assert Path(unique_output_path(source_file, [str(source_file)])).name == "song_edited.wav"
    existing = tmp_path / "Echo - 海岸.flac"
    existing.write_bytes(b"old")
    output = download_audio(
        "https://cdn.example/song.flac",
        {},
        existing,
        opener=lambda *_args, **_kwargs: FakeResponse(b"audio", True),
    )
    assert Path(output).name == "Echo - 海岸_2.flac"
    assert Path(output).read_bytes() == b"audio"
    assert existing.read_bytes() == b"old"
    assert suggested_filename({"title": "坏:/名字", "artist": "歌手"}, "320k").endswith(
        ".mp3"
    )


def test_lx_metadata_and_config_validation(tmp_path):
    script = """
/* @name 测试音源
 * @version 1.2.3
 * @author Echo
 */
"""
    metadata = parse_lx_source_metadata(script)
    assert metadata["name"] == "测试音源"
    assert metadata["version"] == "1.2.3"
    config = validate_source_config(
        {
            "type": "lx_js",
            "id": "lx-test-kw",
            "name": "测试音源 · 酷我",
            "script_path": str(tmp_path / "source.js"),
            "source_key": "kw",
            "qualities": ["128k", "flac", "unknown"],
            "metadata": metadata,
        }
    )
    assert config["type"] == "lx_js"
    assert config["qualities"] == ["128k", "flac"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_lx_script_import_expands_platforms(tmp_path):
    source_file = tmp_path / "demo.js"
    source_file.write_text(
        """
/* @name Demo Source
 * @version 1.0.0
 */
globalThis.lx.on(lx.EVENT_NAMES.request, ({ source, info }) =>
  Promise.resolve(`https://audio.example/${source}/${info.type}.mp3`)
)
lx.send(lx.EVENT_NAMES.inited, {
  sources: {
    kw: {
      name: '酷我',
      type: 'music',
      actions: ['musicUrl'],
      qualitys: ['128k', 'flac'],
    },
    kg: {
      name: '酷狗',
      type: 'music',
      actions: ['musicUrl'],
      qualitys: ['128k'],
    },
  },
})
""",
        encoding="utf-8",
    )
    configs = import_lx_source(source_file, tmp_path / "stored")
    assert [item["source_key"] for item in configs] == ["kw", "kg"]
    assert all(Path(item["script_path"]).exists() for item in configs)
    url, headers = resolve_download(
        configs[0],
        {"music_info": {"songmid": "42"}},
        "128k",
    )
    assert url == "https://audio.example/kw/128k.mp3"
    assert headers == {}


def test_lx_unavailable_track_error_is_explained(monkeypatch, tmp_path):
    script_path = tmp_path / "source.js"
    script_path.write_text("// demo", encoding="utf-8")
    config = validate_source_config(
        {
            "type": "lx_js",
            "id": "lx-test-wy",
            "name": "测试音源 · 网易",
            "script_path": str(script_path),
            "source_key": "wy",
            "qualities": ["128k"],
        }
    )
    monkeypatch.setattr(
        audio_sources,
        "_run_lx_worker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("failed")),
    )

    with pytest.raises(ValueError, match="当前音源没有提供这首歌"):
        resolve_download(
            config,
            {"music_info": {"songmid": "42"}},
            "128k",
        )
