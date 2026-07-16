import socket
from pathlib import Path

from server import localsend_receiver as receiver_module
from server.localsend_receiver import LocalSendReceiver
from server.localsend_sender import LocalSendDevice, LocalSendSender


def _free_port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


def test_localsend_sender_and_receiver_transfer_real_file(monkeypatch, tmp_path):
    transfer_port = _free_port()
    browse_port = _free_port()
    monkeypatch.setattr(receiver_module, "HTTP_PORT", transfer_port)
    monkeypatch.setattr(receiver_module, "BROWSE_PORT", browse_port)
    monkeypatch.setattr(LocalSendReceiver, "_start_udp_multicast", lambda _self: None)
    monkeypatch.setattr(LocalSendReceiver, "_send_announcement", lambda _self: None)
    completed = []
    receive_root = tmp_path / "received"
    receiver = LocalSendReceiver(
        str(receive_root),
        "Receiver",
        on_session_completed=completed.append,
    )
    receiver.start()
    source = tmp_path / "歌词.lrc"
    source.write_text("[00:01.00]测试\n", encoding="utf-8")
    try:
        results = LocalSendSender("Sender").send_files(
            LocalSendDevice(
                alias="Receiver",
                ip="127.0.0.1",
                port=transfer_port,
                protocol="https",
                fingerprint=receiver.fingerprint,
            ),
            [source],
        )
    finally:
        receiver.stop()

    assert results[0]["status"] == "sent"
    assert len(completed) == 1
    received_path = next(Path(completed[0]["workspace"]).glob("*.lrc"))
    assert received_path.read_bytes() == source.read_bytes()
