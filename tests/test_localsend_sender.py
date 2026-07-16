from server.localsend_sender import LocalSendDevice, LocalSendSender


def test_localsend_sender_prepares_and_uploads_selected_files(monkeypatch, tmp_path):
    first = tmp_path / "歌词.lrc"
    second = tmp_path / "vocals.wav"
    first.write_text("[00:01.00]歌词\n", encoding="utf-8")
    second.write_bytes(b"audio")
    sender = LocalSendSender("Echovault")
    captured = {}

    def fake_json(_device, method, path, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return 200, {
            "sessionId": "session",
            "files": {file_id: f"token-{index}" for index, file_id in enumerate(payload["files"])},
        }

    uploaded = []

    def fake_upload(_device, **kwargs):
        uploaded.append(kwargs["path"].name)
        kwargs["progress"](kwargs["path"].stat().st_size)
        return kwargs["path"].stat().st_size

    monkeypatch.setattr(sender, "_json_request", fake_json)
    monkeypatch.setattr(sender, "_upload_file", fake_upload)
    progress = []
    results = sender.send_files(
        LocalSendDevice(alias="Phone", ip="127.0.0.1", protocol="http"),
        [first, second],
        progress=lambda *values: progress.append(values),
    )

    assert captured["path"] == "/api/localsend/v2/prepare-upload"
    assert {item["fileName"] for item in captured["payload"]["files"].values()} == {
        "歌词.lrc",
        "vocals.wav",
    }
    assert uploaded == ["歌词.lrc", "vocals.wav"]
    assert [result["status"] for result in results] == ["sent", "sent"]
    assert progress[-1][3] == first.stat().st_size + second.stat().st_size


def test_localsend_sender_handles_receiver_skip(monkeypatch, tmp_path):
    path = tmp_path / "same.lrc"
    path.write_text("same", encoding="utf-8")
    sender = LocalSendSender()
    monkeypatch.setattr(sender, "_json_request", lambda *_args, **_kwargs: (204, {}))

    results = sender.send_files(
        LocalSendDevice(alias="Phone", ip="127.0.0.1", protocol="http"),
        [path],
    )

    assert results == [{"path": str(path.resolve()), "status": "skipped"}]
