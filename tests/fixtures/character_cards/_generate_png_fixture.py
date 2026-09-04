"""生成角色卡 PNG 二进制 fixture（白厄（3.4前）.png）。

用途：契约 §12 规定 PNG fixture 由「白厄 JSON + 程序合成最小真实 PNG
头像字节（zlib 构造 IHDR/IDAT/IEND，不新增依赖）经 write_png_card 生成，
入库为二进制 fixture」。

本脚本用标准库 zlib/struct 合成 64x64、RGB、8-bit 的最小真实 PNG 头像
（含正确 CRC），读取同目录 ``白厄（3.4前）.json``，经
``load_card_json`` + ``write_png_card`` 产出 ``白厄（3.4前）.png``。

再生成方法（仓库根目录，Git Bash）：

    ./.venv/Scripts/python.exe tests/fixtures/character_cards/_generate_png_fixture.py

生成后建议用测试验证 fixture 内容有效：

    ./.venv/Scripts/python.exe -m pytest -q tests/unit/test_character_card_png.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from pair_harness.character_cards import load_card_json, write_png_card

HERE = Path(__file__).resolve().parent
JSON_PATH = HERE / "白厄（3.4前）.json"
PNG_PATH = HERE / "白厄（3.4前）.png"

WIDTH = 64
HEIGHT = 64
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(ctype: bytes, data: bytes) -> bytes:
    """构造单个 PNG 块（长度 + 类型 + 数据 + CRC）。"""
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def make_avatar_png() -> bytes:
    """合成最小但真实可解码的 PNG 头像（64x64、RGB、8-bit）。"""
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    rows = []
    for y in range(HEIGHT):
        row = bytearray([0])  # filter type 0（None），每行一个前置字节
        for x in range(WIDTH):
            # 简单的确定性渐变，保证行内数据非平凡、zlib 压缩有意义。
            row.extend((x * 3 % 256, y * 5 % 256, (x + y) * 7 % 256))
        rows.append(bytes(row))
    idat = zlib.compress(b"".join(rows))
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def main() -> None:
    card = load_card_json(JSON_PATH.read_text(encoding="utf-8")).card
    avatar = make_avatar_png()
    card_png = write_png_card(card, avatar)
    PNG_PATH.write_bytes(card_png)
    print(f"已生成 {PNG_PATH}（{len(card_png)} 字节，头像 {WIDTH}x{HEIGHT}）")


if __name__ == "__main__":
    main()
