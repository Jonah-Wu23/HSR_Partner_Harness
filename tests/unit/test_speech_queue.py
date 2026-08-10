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


def test_playback_state_pauses_and_resumes_vad() -> None:
    queue = SpeechQueue()
    queue.begin_playback()
    assert queue.playing is True
    queue.end_playback()
    assert queue.playing is False


def test_push_to_talk_stops_playback_first() -> None:
    queue = SpeechQueue()
    queue.enqueue(_request("一"))
    queue.begin_playback()
    queue.stop()
    assert queue.pending == 0
    assert queue.playing is False
