from main import CLI_OUTPUT_PATH_ENV, _configure_utf8_stream


class FakeStream:
    encoding = "gbk"

    def __init__(self):
        self.options = None

    def reconfigure(self, **options):
        self.options = options


def test_configure_utf8_stream_accepts_windowed_mode_none():
    stream = _configure_utf8_stream(None)

    try:
        assert stream.writable()
        stream.write("hidden windowed output")
    finally:
        stream.close()


def test_configure_utf8_stream_reconfigures_console():
    stream = FakeStream()

    result = _configure_utf8_stream(stream)

    assert result is stream
    assert stream.options == {"encoding": "utf-8", "errors": "replace"}


def test_configure_utf8_stream_captures_windowed_cli_output(tmp_path, monkeypatch):
    output_path = tmp_path / "cli-output.log"
    monkeypatch.setenv(CLI_OUTPUT_PATH_ENV, str(output_path))

    stream = _configure_utf8_stream(None, capture_cli_output=True)
    try:
        stream.write("诊断结果")
    finally:
        stream.close()

    assert output_path.read_text(encoding="utf-8") == "诊断结果"


def test_configure_utf8_stream_keeps_stderr_out_of_cli_capture(tmp_path, monkeypatch):
    output_path = tmp_path / "cli-output.log"
    monkeypatch.setenv(CLI_OUTPUT_PATH_ENV, str(output_path))

    stream = _configure_utf8_stream(None, capture_cli_output=False)
    try:
        stream.write("dependency diagnostic")
    finally:
        stream.close()

    assert not output_path.exists()
