# PNG 角色卡沿用 SillyTavern 惯例：tEXt 块关键字 chara（v2）或 ccv3（v3），值为 base64(UTF-8 JSON)。
# 写入只写 ccv3，读取 ccv3 优先；元数据块以外的 PNG 块按原始字节复制，头像图像数据不重编码。

from __future__ import annotations

import base64
import struct
import zlib

from pair_harness.character_cards.codec import ImportResult, dump_card_v3, load_card_json
from pair_harness.character_cards.models import CharacterCard

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEYWORD_V2 = b"chara"
KEYWORD_V3 = b"ccv3"


class PngCardError(ValueError):
    """PNG 载体错误：签名或块结构不合法、缺少元数据块、base64/UTF-8 解码失败。"""


def _iter_chunks(data: bytes):
    """按 PNG 块结构迭代并校验 CRC，产出 (type, data)。"""
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
        yield ctype, cdata
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

    载体问题抛 :class:`PngCardError`；卡片 JSON 或字段非法时与 JSON 导入一样抛
    ``CardImportError``。
    """
    if not data.startswith(PNG_SIGNATURE):
        raise PngCardError("不是合法 PNG 文件（签名不符）")
    payloads: dict[bytes, bytes] = {}
    for ctype, cdata in _iter_chunks(data):
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
    result = load_card_json(card_json)
    result.report.warnings.append(f"PNG 元数据来源 tEXt 关键字: {keyword.decode()}")
    return result


def write_png_card(card: CharacterCard, avatar_png: bytes) -> bytes:
    """把 v3 角色卡元数据写入头像 PNG，返回单文件角色卡字节。

    去掉原有 ``chara``/``ccv3`` tEXt 块，在 IHDR 之后插入新的 ``ccv3`` 块，
    其余块原样保留。JPEG/WebP 头像无法承载 PNG 块，直接报错。
    """
    if not avatar_png.startswith(PNG_SIGNATURE):
        raise PngCardError(
            "头像不是 PNG 图片（文件签名不符），无法导出 PNG 角色卡；"
            "请把头像换成 PNG 图片后再导出，或改用 JSON 导出"
        )
    card_json = dump_card_v3(card, for_export=True).encode("utf-8")
    text = base64.b64encode(card_json)
    chunk = _make_text_chunk(KEYWORD_V3, text)

    out = bytearray(PNG_SIGNATURE)
    for index, (ctype, cdata) in enumerate(_iter_chunks(avatar_png)):
        if ctype == b"tEXt":
            sep = cdata.find(b"\x00")
            keyword = cdata[:sep] if sep >= 0 else cdata
            if keyword in (KEYWORD_V3, KEYWORD_V2):
                continue
        out += _chunk_bytes(ctype, cdata)
        # _iter_chunks 已保证首块是 IHDR，元数据块紧随其后。
        if index == 0:
            out += chunk
    return bytes(out)


def _chunk_bytes(ctype: bytes, cdata: bytes) -> bytes:
    header = struct.pack(">I", len(cdata)) + ctype
    crc = struct.pack(">I", zlib.crc32(ctype + cdata) & 0xFFFFFFFF)
    return header + cdata + crc


def _make_text_chunk(keyword: bytes, text: bytes) -> bytes:
    return _chunk_bytes(b"tEXt", keyword + b"\x00" + text)


def png_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """读取已通过 :func:`read_png_card` 校验的 PNG 的 IHDR 宽高。

    首块必为 IHDR，宽高是数据区前 8 字节。宽高为 0 或超过 PNG 规范上限
    ``2**31 - 1`` 时返回 None。
    """
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width < 2**31 and 0 < height < 2**31):
        return None
    return width, height
