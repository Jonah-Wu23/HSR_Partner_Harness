"""extract_speech_segments 测试（B2.4）：Markdown 输出切 TTS 段落。"""

from __future__ import annotations

from pair_harness.core.voice_policy import extract_speech_segments


def test_plain_paragraph_kept() -> None:
    assert extract_speech_segments("你好，我是白厄。") == ["你好，我是白厄。"]


def test_fenced_code_block_removed() -> None:
    text = "已完成修改。\n```python\nprint(\"hello\")\nx = 1\n```\n现在可以运行了。"
    assert extract_speech_segments(text) == ["已完成修改。", "现在可以运行了。"]


def test_inline_code_removed() -> None:
    text = "请运行 `python main.py` 这个命令。"
    assert extract_speech_segments(text) == ["请运行 这个命令。"]


def test_command_path_lines_removed() -> None:
    text = (
        "修改完成。\n"
        "E:\\AI\\HSR Partner Harness\\src\\main.py\n"
        "python main.py --verbose\n"
        "cd src && pytest\n"
        "结果如下。"
    )
    assert extract_speech_segments(text) == ["修改完成。", "结果如下。"]


def test_unix_executable_path_removed() -> None:
    text = "请查看这个文件：\n/home/user/run.sh\n内容如上。"
    assert extract_speech_segments(text) == ["请查看这个文件：", "内容如上。"]


def test_cjk_line_with_embedded_path_kept() -> None:
    # 含中文的整行不判定为命令行（路径作为句子一部分时保留）
    text = "路径 /home/user/run.sh 不存在。"
    assert extract_speech_segments(text) == ["路径 /home/user/run.sh 不存在。"]


def test_paragraph_split_on_blank_lines() -> None:
    text = "第一段。\n\n第二段。\n\n\n第三段。"
    assert extract_speech_segments(text) == ["第一段。", "第二段。", "第三段。"]


def test_multiline_paragraph_joined() -> None:
    text = "第一行内容。\n第二行延续。\n\n另起一段。"
    assert extract_speech_segments(text) == ["第一行内容。 第二行延续。", "另起一段。"]


def test_empty_input_returns_empty() -> None:
    assert extract_speech_segments("") == []
    assert extract_speech_segments("   \n  ") == []


def test_only_code_returns_empty() -> None:
    assert extract_speech_segments("```python\nx = 1\n```") == []


def test_order_preserved() -> None:
    text = "甲。\n\n乙。\n\n丙。"
    assert extract_speech_segments(text) == ["甲。", "乙。", "丙。"]


def test_cjk_sentence_with_command_words_not_deleted() -> None:
    # 含中文的句子即使带命令关键词也不判定为命令行
    text = "运行 python 脚本前请先检查依赖。"
    assert extract_speech_segments(text) == ["运行 python 脚本前请先检查依赖。"]


def test_english_sentence_not_a_command() -> None:
    text = "The result looks good.\n\nPlease review it."
    assert extract_speech_segments(text) == ["The result looks good.", "Please review it."]
