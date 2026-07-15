from core.config import AppConfig
from core.online_lyrics import LyricsMatch, MediaSearchMetadata
from tests.qt_test_app import ensure_app, keep_widget
from ui.batch_operations_panel import BatchOnlineLyricsWorker, BatchOperationsPanel


def _match(score=91.0, synced=True):
    return LyricsMatch(
        record_id=7,
        track_name="Song",
        artist_name="Artist",
        album_name="Album",
        duration=120.0,
        instrumental=False,
        plain_lyrics="one\ntwo",
        synced_lyrics="[00:01.00]one\n[00:02.00]two" if synced else "",
        score=score,
    )


def test_batch_panel_consolidates_three_operations_and_reports_scope():
    ensure_app()
    panel = keep_widget(BatchOperationsPanel(AppConfig()))

    panel.update_scope(
        [
            {"has_lrc": False, "instrumental": False},
            {"has_lrc": True, "instrumental": False},
            {"has_lrc": False, "instrumental": True},
        ]
    )

    assert panel.batch_transcribe_button.text() == "开始批量识别"
    assert panel.batch_translate_button.text() == "开始批量翻译"
    assert panel.batch_online_button.text() == "开始批量在线匹配"
    assert "当前素材：3 个" in panel.scope_label.text()
    assert "待识别 1 个" in panel.scope_label.text()
    assert "可翻译 1 个" in panel.scope_label.text()
    assert panel.apply_best_checkbox.isChecked() is False
    assert panel.minimum_score.value() == 80


def test_batch_online_worker_reports_best_match_without_writing(monkeypatch, tmp_path):
    ensure_app()
    media_path = tmp_path / "Artist - Song.mp3"
    media_path.write_bytes(b"audio")
    monkeypatch.setattr(
        "ui.batch_operations_panel.media_search_metadata",
        lambda _path: MediaSearchMetadata("Song", "Artist", "", 120.0),
    )
    monkeypatch.setattr(
        "ui.batch_operations_panel.search_lrclib",
        lambda *_args, **_kwargs: [_match(77.0), _match(93.0)],
    )
    captured = []
    worker = keep_widget(
        BatchOnlineLyricsWorker(
            [{"path": str(media_path)}], apply_best=False, minimum_score=80
        )
    )
    worker.completed.connect(captured.extend)

    worker.run()

    assert captured[0]["status"] == "matched"
    assert captured[0]["score"] == 93.0
    assert not media_path.with_suffix(".lrc").exists()

