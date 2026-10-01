from __future__ import annotations

from pair_harness.core.audio import SpeechQueue
from pair_harness.core.contracts import SpeechRequest


def _request(text: str) -> SpeechRequest:
    return SpeechRequest(text=text, voice_id="demo", message_id=text)


def test_queue_keeps_fifo_order() -> None:
    queue = SpeechQueue()
    queue.enqueue(_request("一"))
    queue.enqueue(_request("二"))
    assert queue.pop_next().text == "一"
    assert queue.pop_next().text == "二"
    assert queue.pop_next() is None


def test_stop_advances_epoch_and_clears_queue() -> None:
    queue = SpeechQueue()
    queue.enqueue(_request("一"))
    queue.enqueue(_request("二"))
    queue.begin_playback()

    queue.stop()

    assert queue.epoch == 1
    assert queue.pending == 0
    assert queue.pop_next() is None
    assert not queue.playing


def test_skip_current_keeps_pending_on_new_epoch() -> None:
    queue = SpeechQueue()
    queue.enqueue(_request("一"))
    queue.enqueue(_request("二"))
    queue.begin_playback()

    assert queue.skip_current() == 1
    assert queue.pending == 2
    assert queue.pending_message_id == "一"
    assert queue.pop_next().text == "一"
    assert queue.pop_next().text == "二"
    assert queue.pop_next() is None
