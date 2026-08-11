"""ASR 增量合并纯函数测试（B2.3）。

语义移植自旧项目 fun_asr_realtime_client._merge_result_events：
stable 段沉淀、包含判断、最长后缀-前缀重叠去重、partial 择优。
"""

from __future__ import annotations

from pair_harness.adapters.audio.qwen_asr import (
    _RawSentence,
    _longest_suffix_prefix_overlap,
    _prefer_more_complete,
    merge_asr_partial,
    merge_asr_segments,
)


def s(text: str, sentence_end: bool = False) -> _RawSentence:
    return _RawSentence(text=text, sentence_end=sentence_end)


# ---------------------------------------------------------------------------
# merge_asr_segments（最终转写）
# ---------------------------------------------------------------------------


def test_stable_segments_concatenated_in_order() -> None:
    events = [s("你好。", True), s("请问有什么可以帮你？", True)]
    assert merge_asr_segments(events) == "你好。请问有什么可以帮你？"


def test_partial_refined_by_longer_prefix() -> None:
    # partial 择优：后到的更长前缀覆盖先到的短 partial
    events = [s("你好"), s("你好世界")]
    assert merge_asr_segments(events) == "你好世界"


def test_partial_joined_by_suffix_prefix_overlap() -> None:
    # 无包含关系但有重叠：按最长后缀-前缀重叠拼接
    events = [s("你好世界"), s("世界你好吗")]
    assert merge_asr_segments(events) == "你好世界你好吗"


def test_duplicate_stable_segment_dropped() -> None:
    events = [s("你好。", True), s("你好。", True)]
    assert merge_asr_segments(events) == "你好。"


def test_contained_stable_segment_replaces_previous() -> None:
    events = [s("你好", True), s("你好世界", True)]
    assert merge_asr_segments(events) == "你好世界"


def test_sentence_end_settles_stable_then_new_partial() -> None:
    events = [s("你好。", True), s("请"), s("请问")]
    assert merge_asr_segments(events) == "你好。请问"


def test_empty_events_return_empty_string() -> None:
    assert merge_asr_segments([s(""), s("", True)]) == ""
    assert merge_asr_segments([]) == ""


def test_empty_text_events_skipped() -> None:
    events = [s(""), s("你好", True), s("")]
    assert merge_asr_segments(events) == "你好"


# ---------------------------------------------------------------------------
# merge_asr_partial（实时显示文本）
# ---------------------------------------------------------------------------


def test_partial_display_keeps_stable_plus_current_partial() -> None:
    events = [s("你好。", True), s("请")]
    assert merge_asr_partial(events) == "你好。请"


def test_partial_display_without_stable() -> None:
    assert merge_asr_partial([s("你"), s("你好")]) == "你好"


def test_partial_display_empty() -> None:
    assert merge_asr_partial([s("")]) == ""


# ---------------------------------------------------------------------------
# 底层辅助
# ---------------------------------------------------------------------------


def test_longest_suffix_prefix_overlap() -> None:
    assert _longest_suffix_prefix_overlap("你好世界", "世界你好吗") == 2
    assert _longest_suffix_prefix_overlap("abc", "abc") == 3
    assert _longest_suffix_prefix_overlap("abc", "def") == 0
    assert _longest_suffix_prefix_overlap("", "abc") == 0
    assert _longest_suffix_prefix_overlap("abc", "") == 0


def test_prefer_more_complete() -> None:
    assert _prefer_more_complete("你好", "你好世界") == "你好世界"
    assert _prefer_more_complete("你好世界", "你好") == "你好世界"
    assert _prefer_more_complete("", "x") == "x"
    assert _prefer_more_complete("x", "") == "x"
    assert _prefer_more_complete("abc", "abc") == "abc"
    assert _prefer_more_complete("你好世界", "世界你好吗") == "你好世界你好吗"
    assert _prefer_more_complete("短", "一个明显更长的文本") == "一个明显更长的文本"
