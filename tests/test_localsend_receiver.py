from io import BytesIO

import pytest

from server.localsend_receiver import _safe_file_link, _stream_to_file


def test_stream_to_file_writes_exact_content(tmp_path):
    destination = tmp_path / "upload.part"
    source = BytesIO(b"abcdef")
    progress = []

    received = _stream_to_file(source, destination, 6, progress.append)

    assert received == 6
    assert destination.read_bytes() == b"abcdef"
    assert progress[-1] == 6


def test_stream_to_file_rejects_incomplete_upload(tmp_path):
    destination = tmp_path / "upload.part"

    with pytest.raises(EOFError, match="incomplete"):
        _stream_to_file(BytesIO(b"abc"), destination, 6)


def test_safe_file_link_escapes_html_and_encodes_url():
    label, href = _safe_file_link('<script>alert(1)</script> 中文.mp3')

    assert "<script>" not in label
    assert "&lt;script&gt;" in label
    assert " " not in href
    assert "%E4%B8%AD%E6%96%87" in href
