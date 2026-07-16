from core.artifact_diff import scan_session_diffs
from core.transfer_session import TransferSessionManager


def test_transfer_session_tracks_generated_modified_and_returned_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audio = workspace / "歌曲.mp3"
    lyrics = workspace / "歌曲.lrc"
    audio.write_bytes(b"audio")
    lyrics.write_text("[00:01.00]原文\n", encoding="utf-8")
    manager = TransferSessionManager(tmp_path / "state")
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
    assert by_name["歌曲.zh.lrc"].status == "generated"
    assert by_name["歌曲.zh.lrc"].recommended is True

    manager.record_return(
        session,
        device={"alias": "Phone"},
        results=[{"path": str(translated), "status": "sent"}],
    )
    returned = scan_session_diffs(manager.load(session.session_id))
    assert next(diff for diff in returned if diff.path == str(translated.resolve())).returned


def test_transfer_session_registers_output_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "song.wav"
    source.write_bytes(b"source")
    output = tmp_path / "exports" / "song_vocals.wav"
    output.parent.mkdir()
    output.write_bytes(b"vocals")
    manager = TransferSessionManager(tmp_path / "state")
    session = manager.create_session(
        session_id="session-2",
        sender={"alias": "Phone"},
        workspace=workspace,
        files=[source],
    )

    assert manager.register_artifact(source, output, "vocal_separation")
    diffs = scan_session_diffs(manager.load(session.session_id))

    assert any(diff.path == str(output.resolve()) for diff in diffs)
