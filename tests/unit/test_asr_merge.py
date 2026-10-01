from __future__ import annotations

import pytest

from pair_harness.adapters.audio.qwen_asr import merge_asr_sentences


def s(begin_time: int, text: str) -> dict[str, object]:
    return {"begin_time": begin_time, "text": text}


@pytest.mark.parametrize(
    ("sentences", "expected"),
    [
        # 同一 begin_time 是同一句的逐次结果，后到的覆盖先到的，即使更短
        ([s(170, "好"), s(170, "好，我知道")], "好，我知道"),
        ([s(170, "好，我知到"), s(170, "好，我")], "好，我"),
        # 不同 begin_time 是不同的句子，按起始时刻拼接
        ([s(0, "你好。"), s(1200, "请问"), s(1200, "请问有什么可以帮你？")], "你好。请问有什么可以帮你？"),
        ([s(900, "第二句。"), s(0, "第一句。")], "第一句。第二句。"),
        ([s(0, "好的。"), s(900, "好的。")], "好的。好的。"),
        ([], ""),
        ([s(0, ""), s(500, "")], ""),
    ],
)
def test_merge_asr_sentences_by_begin_time(sentences, expected) -> None:
    assert merge_asr_sentences(sentences) == expected
