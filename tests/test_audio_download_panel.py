from types import SimpleNamespace

from tests.qt_test_app import ensure_app, keep_widget
from ui.audio_download_panel import AudioDownloadPanel, AudioPreviewResolveWorker


def _config():
    return SimpleNamespace(
        audio_sources=[
            {
                "type": "rest",
                "id": "preview-source",
                "name": "试听音源",
                "base_url": "https://catalog.example",
                "search_path": "/search?q={query}",
                "resolve_path": "/tracks/{id}?quality={quality}",
                "qualities": ["128k", "320k"],
                "headers": {},
                "terms_url": "",
                "authorized": True,
                "enabled": True,
            }
        ],
        audio_download_dir="D:/Music",
        music_dirs=[],
    )


def test_download_workspace_separates_player_and_download_controls():
    ensure_app()
    panel = keep_widget(AudioDownloadPanel(_config()))
    panel._tracks = [
        {
            "id": "1",
            "title": "第一首",
            "artist": "歌手",
            "album": "专辑",
            "duration": "03:10",
            "qualities": ["128k", "320k"],
        },
        {
            "id": "2",
            "title": "第二首",
            "artist": "歌手",
            "album": "",
            "duration": "04:20",
            "qualities": ["128k"],
        },
    ]
    panel._render_tracks(panel._tracks)

    assert not panel.preview_bar.isHidden()
    assert panel.action_bar.isHidden()
    assert panel.preview_title.text() == "第一首"
    assert panel.previous_button.toolTip() == "上一首"
    assert panel.next_button.toolTip() == "下一首"
    assert panel.stage_download_button.isEnabled()

    panel._open_download_record()

    assert panel.preview_bar.isHidden()
    assert not panel.action_bar.isHidden()
    assert panel.track_title.text() == "第一首 · 歌手"
    assert panel.download_button.isEnabled()


def test_preview_source_failure_stays_inline_without_blocking_dialog(monkeypatch):
    ensure_app()
    panel = keep_widget(AudioDownloadPanel(_config()))
    panel._tracks = [
        {
            "id": "1",
            "title": "不可用歌曲",
            "artist": "歌手",
            "album": "",
            "duration": "03:10",
            "qualities": ["128k"],
        }
    ]
    panel._render_tracks(panel._tracks)
    warning_calls = []
    monkeypatch.setattr(
        "ui.audio_download_panel.QMessageBox.warning",
        lambda *args: warning_calls.append(args),
    )

    panel._preview_token = 7
    panel._preview_failed({"token": 7, "message": "当前音源没有提供可播放地址。"})

    assert "当前歌曲不可试听" in panel.status_label.text()
    assert panel.preview_play_button.toolTip() == "重试试听"
    assert warning_calls == []


def test_preview_worker_falls_back_to_next_result(monkeypatch):
    ensure_app()
    source = _config().audio_sources[0]
    tracks = [
        {"id": "blocked", "title": "受限歌曲", "qualities": ["128k"]},
        {"id": "playable", "title": "可播放歌曲", "qualities": ["128k"]},
    ]

    def fake_resolve(_source, track, quality):
        if track["id"] == "blocked":
            raise ValueError("受版权限制")
        return "https://media.example/playable.mp3", {"X-Test": quality}

    monkeypatch.setattr("ui.audio_download_panel.resolve_download", fake_resolve)
    worker = AudioPreviewResolveWorker(9, [source], 0, tracks, 0, "测试")
    completed = []
    failed = []
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert completed[0]["track"]["id"] == "playable"
    assert completed[0]["attempts"] == 2


def test_preview_worker_searches_next_source(monkeypatch):
    ensure_app()
    first = _config().audio_sources[0]
    second = dict(first, id="second", name="备用音源")
    tracks = [{"id": "blocked", "title": "受限歌曲", "qualities": ["128k"]}]

    def fake_search(source, _query):
        assert source["id"] == "second"
        return [{"id": "alternate", "title": "备用结果", "qualities": ["128k"]}]

    def fake_resolve(_source, track, _quality):
        if track["id"] == "blocked":
            raise ValueError("无地址")
        return "https://media.example/alternate.mp3", {}

    monkeypatch.setattr("ui.audio_download_panel.search_source", fake_search)
    monkeypatch.setattr("ui.audio_download_panel.resolve_download", fake_resolve)
    worker = AudioPreviewResolveWorker(10, [first, second], 0, tracks, 0, "测试")
    completed = []
    worker.completed.connect(completed.append)

    worker.run()

    assert completed[0]["source"]["id"] == "second"
    assert completed[0]["track"]["id"] == "alternate"
    assert completed[0]["attempts"] == 2
