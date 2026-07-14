import pytest

from core.runtime_protocol import (
    PROTOCOL_VERSION,
    RuntimeProtocolError,
    decode_message,
    encode_message,
    make_request,
)


def test_protocol_round_trip_preserves_chinese_text():
    request = make_request("job-1", "ping", message="简体中文")

    decoded = decode_message(encode_message(request))

    assert decoded == request
    assert decoded["protocol_version"] == PROTOCOL_VERSION


@pytest.mark.parametrize(
    "raw",
    ["not-json", "[]", '{"protocol_version": 2}', '{"protocol_version": null}'],
)
def test_protocol_rejects_invalid_or_incompatible_messages(raw):
    with pytest.raises(RuntimeProtocolError):
        decode_message(raw)


def test_make_request_requires_id_and_action():
    with pytest.raises(RuntimeProtocolError):
        make_request("", "ping")
    with pytest.raises(RuntimeProtocolError):
        make_request("job", "")
