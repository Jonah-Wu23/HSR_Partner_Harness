"""Character Card PNG 元数据读写与头像保留测试（V0.4.0 逻辑底座）。"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest

from pair_harness.character_cards import (
    CardImportError,
    PngCardError,
    dump_card_v3,
    load_card_json,
    read_png_card,
    write_png_card,
)
from pair_harness.character_cards.png import png_image_dimensions

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "character_cards"
FIXTURE = FIXTURE_DIR / "白厄（3.4前）.json"
PNG_FIXTURE = FIXTURE_DIR / "白厄（3.4前）.png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data)) + ctype + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def make_avatar_png(width: int = 2, height: int = 2, extra_chunks: list[bytes] | None = None) -> bytes:
    """手工构造最小合法 PNG（RGB 灰度渐变），不依赖第三方图像库。"""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend((x * 60 % 256, y * 60 % 256, (x + y) * 30 % 256))
        rows.append(bytes(row))
    scanlines = b"".join(rows)
    idat = zlib.compress(scanlines)
    png = PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    if extra_chunks:
        # 附加块插在 IDAT 之前，模拟真实卡里的其他辅助块。
        ihdr_end = len(PNG_SIGNATURE) + 12 + len(ihdr)
        head, tail = png[:ihdr_end], png[ihdr_end:]
        body = b"".join(extra_chunks) + tail
        png = head + body
    return png


def _text_chunk(keyword: bytes, payload: dict) -> bytes:
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return _chunk(b"tEXt", keyword + b"\x00" + encoded)


def _png_image_bytes(data: bytes) -> list[bytes]:
    """提取 IDAT 块原始字节，用于断言头像图像数据未变。"""
    out = []
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        if ctype == b"IDAT":
            out.append(data[offset + 8 : offset + 8 + length])
        offset += 12 + length
    return out


def test_write_and_read_v3_png_roundtrip() -> None:
    card = load_card_json(FIXTURE.read_text(encoding="utf-8")).card
    avatar = make_avatar_png(4, 4)
    card_png = write_png_card(card, avatar)
    result = read_png_card(card_png)
    assert result.card == card
    # 头像图像数据在导出 PNG 中按原始字节保留。
    assert _png_image_bytes(card_png) == _png_image_bytes(avatar)
    assert any("ccv3" in warning for warning in result.report.warnings)


def test_png_double_write_replaces_old_metadata() -> None:
    card = load_card_json(FIXTURE.read_text(encoding="utf-8")).card
    avatar = make_avatar_png()
    once = write_png_card(card, avatar)
    # 把旧卡 PNG（含 ccv3）再作为头像写一次：元数据块必须被替换而非叠加。
    twice = write_png_card(card, once)
    keywords = []
    offset = len(PNG_SIGNATURE)
    while offset < len(twice):
        (length,) = struct.unpack(">I", twice[offset : offset + 4])
        ctype = twice[offset + 4 : offset + 8]
        if ctype == b"tEXt":
            body = twice[offset + 8 : offset + 8 + length]
            keywords.append(body.split(b"\x00", 1)[0])
        offset += 12 + length
    assert keywords.count(b"ccv3") == 1
    assert keywords.count(b"chara") == 0


def test_read_v2_chara_keyword_png() -> None:
    v2_payload = {
        "spec": "chara_card_v2",
        "name": "PNG 旧卡",
        "description": "v2 数据",
        "data": {"name": "PNG 旧卡", "description": "v2 数据"},
    }
    png = make_avatar_png(extra_chunks=[_text_chunk(b"chara", v2_payload)])
    result = read_png_card(png)
    assert result.card.name == "PNG 旧卡"
    assert result.card.spec == "chara_card_v2"
    assert any("chara" in warning for warning in result.report.warnings)


def test_ccv3_preferred_over_chara() -> None:
    v2_payload = {"spec": "chara_card_v2", "name": "旧数据"}
    v3_payload = {"spec": "chara_card_v3", "name": "新数据", "data": {"name": "新数据"}}
    png = make_avatar_png(
        extra_chunks=[_text_chunk(b"chara", v2_payload), _text_chunk(b"ccv3", v3_payload)]
    )
    card = read_png_card(png).card
    assert card.name == "新数据"
    assert card.spec == "chara_card_v3"


def test_png_import_then_json_export_then_reimport() -> None:
    card = load_card_json(FIXTURE.read_text(encoding="utf-8")).card
    card_png = write_png_card(card, make_avatar_png(3, 5))
    from_png = read_png_card(card_png).card
    again = load_card_json(dump_card_v3(from_png)).card
    assert again == card


def test_png_errors_preserve_reasons() -> None:
    card = load_card_json(FIXTURE.read_text(encoding="utf-8")).card
    with pytest.raises(PngCardError, match="签名不符"):
        read_png_card(b"not a png")
    with pytest.raises(PngCardError, match="签名不符"):
        write_png_card(card, b"\x00\x01")
    with pytest.raises(PngCardError, match="没有角色卡元数据"):
        read_png_card(make_avatar_png())
    broken = make_avatar_png(
        extra_chunks=[_chunk(b"tEXt", b"ccv3\x00!!!not-base64!!!")]
    )
    with pytest.raises(PngCardError, match="base64/UTF-8 解码失败"):
        read_png_card(broken)
    bad_json = make_avatar_png(
        extra_chunks=[
            _chunk(b"tEXt", b"ccv3\x00" + base64.b64encode(b"{invalid json"))
        ]
    )
    with pytest.raises(PngCardError, match="JSON 解析失败"):
        read_png_card(bad_json)
    no_name = make_avatar_png(
        extra_chunks=[_text_chunk(b"ccv3", {"spec": "chara_card_v3", "data": {}})]
    )
    with pytest.raises(PngCardError, match="name"):
        read_png_card(no_name)


def test_png_truncated_chunk_fails() -> None:
    good = write_png_card(
        load_card_json(FIXTURE.read_text(encoding="utf-8")).card, make_avatar_png()
    )
    with pytest.raises(PngCardError, match="块"):
        read_png_card(good[: len(good) - 7])


def test_png_bad_crc_and_missing_iend_fail() -> None:
    avatar = bytearray(make_avatar_png())
    avatar[29] ^= 0x01  # IHDR CRC 的一个字节
    with pytest.raises(PngCardError, match="CRC"):
        write_png_card(
            load_card_json(FIXTURE.read_text(encoding="utf-8")).card,
            bytes(avatar),
        )
    missing_iend = make_avatar_png()[:-12]
    with pytest.raises(PngCardError, match="IEND"):
        write_png_card(
            load_card_json(FIXTURE.read_text(encoding="utf-8")).card,
            missing_iend,
        )


def test_png_metadata_is_v3_json_with_avatar_card_data() -> None:
    card = load_card_json(FIXTURE.read_text(encoding="utf-8")).card
    card_png = write_png_card(card, make_avatar_png())
    offset = len(PNG_SIGNATURE)
    while offset < len(card_png):
        (length,) = struct.unpack(">I", card_png[offset : offset + 4])
        ctype = card_png[offset + 4 : offset + 8]
        body = card_png[offset + 8 : offset + 8 + length]
        if ctype == b"tEXt" and body.startswith(b"ccv3\x00"):
            payload = json.loads(base64.b64decode(body[5:].decode("ascii")))
            assert payload["spec"] == "chara_card_v3"
            assert payload["data"]["name"] == "白厄（3.4前）"
            assert len(payload["data"]["character_book"]["entries"]) == 20
            break
        offset += 12 + length
    else:
        pytest.fail("导出 PNG 中没有 ccv3 元数据块")


# ---- V0.3.7 新增：PNG fixture 与 png_image_dimensions ----


def test_png_fixture_exists_and_parses() -> None:
    """契约 §12：白厄 PNG fixture 存在，且 read_png_card 能解析其内容。"""
    assert PNG_FIXTURE.exists()
    result = read_png_card(PNG_FIXTURE.read_bytes())
    assert result.card.name == "白厄（3.4前）"
    assert len(result.card.character_book.entries) == 20
    assert len(result.card.alternate_greetings) == 5
    assert result.card.spec == "chara_card_v3"


def test_png_image_dimensions_of_fixture() -> None:
    """契约 §1.1：png_image_dimensions 对白厄 fixture 返回 (64, 64)。"""
    assert png_image_dimensions(PNG_FIXTURE.read_bytes()) == (64, 64)


def test_png_image_dimensions_kept_after_write_png_card() -> None:
    """契约 §1.3：write_png_card 只复制原头像图像块，尺寸保持不变。"""
    card = load_card_json(FIXTURE.read_text(encoding="utf-8")).card
    avatar = make_avatar_png(18, 27)
    card_png = write_png_card(card, avatar)
    assert png_image_dimensions(avatar) == (18, 27)
    assert png_image_dimensions(card_png) == (18, 27)
    # 图像块原始字节复制（尺寸保持的另一层证据）。
    assert _png_image_bytes(card_png) == _png_image_bytes(avatar)


def _png_with_ihdr(width: int, height: int) -> bytes:
    """只构造 IHDR 声明给定宽高的最小 PNG（不生成真实扫描线）。

    用于非法尺寸用例：png_image_dimensions 只读 IHDR，IDAT 内容无关紧要，
    避免 make_avatar_png 为超大宽高分配像素缓冲。
    """
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(b""))
        + _chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    "label,malformed",
    [
        ("空字节", b""),
        ("仅签名", PNG_SIGNATURE),
        ("签名错", b"not a png"),
        ("块头截断", PNG_SIGNATURE + b"\x00\x00"),
        ("IHDR 数据截断（不足宽高 8 字节）", PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + b"\x00\x00"),
        ("首块非 IHDR", PNG_SIGNATURE + struct.pack(">I", 0) + b"IDAT" + struct.pack(">I", 0)),
        ("宽为 0", _png_with_ihdr(0, 10)),
        ("高为 0", _png_with_ihdr(10, 0)),
        ("宽超 2^31-1", _png_with_ihdr(2**31, 10)),
        ("高超 2^31-1", _png_with_ihdr(10, 2**31)),
    ],
)
def test_png_image_dimensions_malformed_returns_none(label: str, malformed: bytes) -> None:
    """契约 §1.1：畸形输入一律返回 None，不抛异常。"""
    assert png_image_dimensions(malformed) is None
