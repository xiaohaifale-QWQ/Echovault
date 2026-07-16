from pathlib import Path

from core.artifact_diff import scan_session_diffs
from core.transfer_session import TransferSessionManager


def test_transfer_session_tracks_generated_modified_and_returned_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audio = workspace / "歌曲.mp3"
    lyrics = workspace / "歌曲.lrc"
    audio.write_bytes(b"audio")
    lyrics.write_text("[00:01.00]原文\n", encoding="utf-8")
    manager = TransferSessionManager(
        tmp_path / "state",
        outbox_dir=tmp_path / "outbox",
        sent_cache_dir=tmp_path / "cache",
    )
    session = manager.create_session(
        session_id="session-1",
        sender={"alias": "Phone"},
        workspace=workspace,
        files=[audio, lyrics],
    )

    lyrics.write_text("[00:01.00]修改后\n", encoding="utf-8")
    translated = workspace / "歌曲.zh.lrc"
    translated.write_text("[00:01.00]译文\n", encoding="utf-8")
    manager.register_artifact(audio, translated, "translation")
    session = manager.load(session.session_id)
    diffs = scan_session_diffs(session)
    by_name = {diff.relative_path: diff for diff in diffs}

    assert by_name["歌曲.mp3"].status == "unchanged"
    assert by_name["歌曲.lrc"].status == "modified"
    staged = next(diff for diff in diffs if diff.operation == "translation")
    assert staged.status == "generated"
    assert staged.recommended is True
    assert Path(staged.path).is_relative_to(tmp_path / "outbox")

    manager.record_return(
        session,
        device={"alias": "Phone"},
        results=[{"path": staged.path, "status": "sent"}],
    )
    returned = scan_session_diffs(manager.load(session.session_id))
    archived = next(diff for diff in returned if diff.operation == "translation")
    assert archived.returned
    assert Path(archived.path).is_relative_to(tmp_path / "cache")
    assert not Path(staged.path).exists()


def test_transfer_session_registers_output_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "song.wav"
    source.write_bytes(b"source")
    output = tmp_path / "exports" / "song_vocals.wav"
    output.parent.mkdir()
    output.write_bytes(b"vocals")
    manager = TransferSessionManager(
        tmp_path / "state",
        outbox_dir=tmp_path / "outbox",
        sent_cache_dir=tmp_path / "cache",
    )
    session = manager.create_session(
        session_id="session-2",
        sender={"alias": "Phone"},
        workspace=workspace,
        files=[source],
    )

    assert manager.register_artifact(source, output, "vocal_separation")
    diffs = scan_session_diffs(manager.load(session.session_id))

    staged = next(diff for diff in diffs if diff.operation == "vocal_separation")
    assert Path(staged.path).read_bytes() == output.read_bytes()
