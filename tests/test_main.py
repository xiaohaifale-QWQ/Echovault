from main import _configure_utf8_stream


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
