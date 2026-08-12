from __future__ import annotations

import json

import pytest

from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.desktop_backend.events import EventEmitter
from pair_harness.desktop_backend.protocol import (
    encode_message,
    parse_request,
    protocol_error,
    response_error,
)


def test_parse_request_and_encode_jsonl() -> None:
    command = parse_request(
        '{"kind":"request","id":"req-1","method":"app.bootstrap","params":{}}'
    )
    assert command == DesktopCommand("req-1", "app.bootstrap", {})
    encoded = encode_message({"kind": "response", "ok": True, "text": "白厄"})
    assert json.loads(encoded) == {"kind": "response", "ok": True, "text": "白厄"}
    assert "\n" not in encoded


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("{", "invalid_json"),
        ("[]", "invalid_message"),
        ('{"kind":"event"}', "invalid_kind"),
        ('{"kind":"request","id":"x","method":"unknown"}', "unknown_method"),
    ],
)
def test_bad_lines_are_structured_protocol_errors(line: str, code: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_request(line)
    assert getattr(exc_info.value, "code") == code
    assert protocol_error(code, str(exc_info.value))["kind"] == "error"


def test_event_emitter_assigns_monotonic_sequence() -> None:
    events: list[dict] = []
    emitter = EventEmitter(events.append)
    emitter.emit("backend.ready", {"demo": True})
    emitter.emit("message.created", {"message": {"message_id": "m1"}})
    assert [event["sequence"] for event in events] == [0, 1]
    assert emitter.next_sequence == 2
    assert response_error("req-1", "bad", "失败")["ok"] is False
