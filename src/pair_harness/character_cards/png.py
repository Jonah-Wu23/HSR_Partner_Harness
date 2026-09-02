"""Character Card v2/v3 PNG 元数据读取与 v3 PNG 写入。

PNG 角色卡约定（SillyTavern 惯例）：

- v2：``tEXt`` 块，关键字 ``chara``，值为 base64(UTF-8 JSON)；
- v3：``tEXt`` 块，关键字 ``ccv3``，值为 base64(UTF-8 JSON)。

写入时只写 ``ccv3``（v3 PNG 导出）；读取时 ``ccv3`` 优先，回退
``chara``。除元数据块外的全部 PNG 块按原始字节复制，头像图像
数据在导入—导出—再导入过程中保持不变。
"""

from __future__ import annotations

import base64
import json
import struct
import zlib

from pair_harness.character_cards.codec import (
    CardImportError,
    ImportResult,
    dump_card_v3,
    load_card_payload,
)
from pair_harness.character_cards.models import CharacterCard

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEYWORD_V2 = b"chara"
KEYWORD_V3 = b"ccv3"


class PngCardError(ValueError):
    """PNG 角色卡读取/写入失败（签名不符、缺元数据、base64 或 JSON 非法）。"""


def _iter_chunks(data: bytes):
    """按 PNG 块结构迭代，返回 (type, data, start, end)。"""
    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    saw_iend = False
    while offset < len(data):
        if offset + 8 > len(data):
            raise PngCardError(f"PNG 块头不完整（偏移 {offset}）")
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            raise PngCardError(f"PNG 块数据不完整（type={ctype!r}）")
        cdata = data[start:end]
        expected_crc = struct.unpack(">I", data[end : end + 4])[0]
        actual_crc = zlib.crc32(ctype + cdata) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise PngCardError(f"PNG 块 CRC 错误（type={ctype!r}）")
        if chunk_index == 0 and (ctype != b"IHDR" or length != 13):
            raise PngCardError("PNG 首块必须是长度为 13 的 IHDR")
        yield ctype, cdata, offset, end + 4
        offset = end + 4
        chunk_index += 1
        if ctype == b"IEND":
            saw_iend = True
            if offset != len(data):
                raise PngCardError("PNG 的 IEND 后存在额外数据")
            break
    if not saw_iend:
        raise PngCardError("PNG 缺少 IEND 块")


def read_png_card(data: bytes) -> ImportResult:
    """从 PNG 字节读取角色卡元数据并归一化。

    ``ccv3``（v3）优先于 ``chara``（v2/旧 v3）。
    """
    if not data.startswith(PNG_SIGNATURE):
        raise PngCardError("不是合法 PNG 文件（签名不符）")
    payloads: dict[bytes, bytes] = {}
    for ctype, cdata, _start, _end in _iter_chunks(data):
        if ctype != b"tEXt":
            continue
        sep = cdata.find(b"\x00")
        if sep < 0:
            continue
        keyword, text = cdata[:sep], cdata[sep + 1 :]
        if keyword in (KEYWORD_V3, KEYWORD_V2):
            payloads[keyword] = text
    if KEYWORD_V3 in payloads:
        keyword, text = KEYWORD_V3, payloads[KEYWORD_V3]
    elif KEYWORD_V2 in payloads:
        keyword, text = KEYWORD_V2, payloads[KEYWORD_V2]
    else:
        raise PngCardError("PNG 中没有角色卡元数据（缺少 chara/ccv3 tEXt 块）")
    try:
        card_json = base64.b64decode(text, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise PngCardError(
            f"PNG 元数据 base64/UTF-8 解码失败（关键字 {keyword.decode()}）: {exc}"
        ) from exc
    try:
        payload = json.loads(card_json)
    except json.JSONDecodeError as exc:
        raise PngCardError(f"PNG 元数据 JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise PngCardError("PNG 元数据必须是 JSON 对象")
    try:
        result = load_card_payload(payload)
    except CardImportError as exc:
        raise PngCardError(f"PNG 角色卡导入失败: {exc}") from exc
    keyword_note = keyword.decode()
    result.report.warnings.append(f"PNG 元数据来源 tEXt 关键字: {keyword_note}")
    return result


def write_png_card(card: CharacterCard, avatar_png: bytes) -> bytes:
    """把 v3 角色卡元数据写入头像 PNG，返回单文件角色卡字节。

    移除原有 ``chara``/``ccv3`` tEXt 块后在 IHDR 之后插入新的
    ``ccv3`` 块；其余块（含图像数据）原样保留。
    """
    if not avatar_png.startswith(PNG_SIGNATURE):
        raise PngCardError("头像不是合法 PNG 文件（签名不符）")
    card_json = dump_card_v3(card).encode("utf-8")
    text = base64.b64encode(card_json)
    chunk = _make_text_chunk(KEYWORD_V3, text)

    out = bytearray(PNG_SIGNATURE)
    inserted = False
    for ctype, cdata, _start, _end in _iter_chunks(avatar_png):
        if ctype == b"tEXt":
            sep = cdata.find(b"\x00")
            keyword = cdata[:sep] if sep >= 0 else cdata
            if keyword in (KEYWORD_V3, KEYWORD_V2):
                continue  # 替换旧元数据
        out += _chunk_bytes(ctype, cdata)
        if not inserted and ctype == b"IHDR":
            out += chunk
            inserted = True
    if not inserted:
        raise PngCardError("头像 PNG 缺少 IHDR 块")
    return bytes(out)


def _chunk_bytes(ctype: bytes, cdata: bytes) -> bytes:
    header = struct.pack(">I", len(cdata)) + ctype
    crc = struct.pack(">I", zlib.crc32(ctype + cdata) & 0xFFFFFFFF)
    return header + cdata + crc


def _make_text_chunk(keyword: bytes, text: bytes) -> bytes:
    return _chunk_bytes(b"tEXt", keyword + b"\x00" + text)


def png_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """探测 PNG 头像尺寸（IHDR 宽高），不做完整校验。

    本函数只做尺寸探测：校验 PNG 签名后读取首块 IHDR 数据区的宽高
    （大端 uint32，偏移 0 与 4）。宽高为 0 或超过 ``2**31 - 1`` 视为
    非法，返回 None。任何畸形输入（签名不符、首块非 IHDR、IHDR 长度
    或数据截断、数据区不足 8 字节）一律返回 None，不抛异常。

    完整校验（块结构、CRC、IEND、元数据解码）是
    :func:`read_png_card` 的职责；本函数供 ``card.peek_import`` 的
    PNG 分支快速取头像尺寸，解析失败如实返回 None 并入 warnings。
    """
    if not data.startswith(PNG_SIGNATURE):
        return None
    # 首块头紧跟 8 字节签名：4 字节长度 + 4 字节块类型。
    if len(data) < len(PNG_SIGNATURE) + 12:
        return None
    (length,) = struct.unpack(">I", data[8:12])
    if data[12:16] != b"IHDR" or length < 8:
        return None
    if len(data) < 16 + 8:
        return None
    width, height = struct.unpack(">II", data[16:24])
    max_dim = 2**31 - 1
    if width <= 0 or height <= 0 or width > max_dim or height > max_dim:
        return None
    return width, height
