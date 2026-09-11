"""S4 真机批次夹具生成（只造历史数据，不掺入任何模拟链路）。

输入：E:\\Tavern\\崩铁-匹诺康尼補充版.json（SillyTavern 世界书导出，402,315 B）。
输出三份夹具：

1. ``fix-a-single-msg.txt``  —— 原文整体作为一条消息正文（> 256 KiB，直接触发正文阈值）。
2. ``fix-b-chunks.json``     —— 切成 80 条、每条约 5 KB，按四个聊天各生成一套并打
   ``FIXTURE-PINOCONY-{chat}-{seq}`` 标记；单套总量 > 256 KiB。
3. ``fix-c-worldbook-card.json`` —— 把世界书转成角色卡 v3 的 ``data.character_book``，
   供 ``card.import_json`` 走候选真实导入路径。

说明：语料是酒馆原生世界书导出（``key``/``keysecondary``/``order``/``disable`` 命名），
候选的角色卡编解码只认 v3 ``character_book`` 命名（``keys``/``secondary_keys``/
``insertion_order``/``enabled``），因此 fix-c 做字段名对齐；``position`` 归一化为
契约支持的 ``0/1/4``。

用法：
    python make_fixtures.py [--out <目录>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CORPUS = Path(r"E:\Tavern\崩铁-匹诺康尼補充版.json")
CHAT_TAGS = ("chat1", "chat2", "chat3", "chat4")
CHUNK_COUNT = 80

# 契约 §3.6 支持的 position；酒馆原生约定 0=before_char、1=after_char、4=atDepth。
_POSITION_MAP = {"0": 0, "1": 1, "4": 4, 0: 0, 1: 1, 4: 4}
_DEFAULT_POSITION = 0


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_str_list(value: object) -> list[str]:
    """酒馆把 keys 存成 JSON 字符串（如 ``'["翁法罗斯"]'``）或数组。"""
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                return [text]
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        return [text]
    return []


def convert_world_book(corpus: dict) -> dict:
    """酒馆原生世界书 → 角色卡 v3 ``character_book``。"""
    raw_entries = corpus.get("entries")
    if isinstance(raw_entries, dict):
        items = [raw_entries[key] for key in sorted(raw_entries, key=_as_int)]
    elif isinstance(raw_entries, list):
        items = list(raw_entries)
    else:
        raise ValueError(f"世界书 entries 形状不支持：{type(raw_entries).__name__}")

    entries = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        position_raw = item.get("position", _DEFAULT_POSITION)
        position = _POSITION_MAP.get(position_raw, _DEFAULT_POSITION)
        entries.append(
            {
                "keys": _as_str_list(item.get("key")),
                "secondary_keys": _as_str_list(item.get("keysecondary")),
                "content": str(item.get("content", "")),
                "enabled": not _as_bool(item.get("disable"), default=False),
                "constant": _as_bool(item.get("constant")),
                "selective": _as_bool(item.get("selective"), default=True),
                "insertion_order": _as_int(item.get("order"), default=100),
                "position": position,
                "use_regex": not _as_bool(item.get("useRegex")),
                "comment": str(item.get("comment", "")),
                "entry_id": _as_int(item.get("uid"), default=index),
            }
        )

    return {
        "name": "崩铁-匹诺康尼補充版",
        "description": "S4 真机批次长世界书夹具（源自酒馆世界书导出，字段名对齐 v3）。",
        "entries": entries,
    }


def build_card(book: dict, corpus_text: str) -> dict:
    """把世界书包成可被 ``card.import_json`` 接受的 v3 角色卡。"""
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": "匹诺康尼补充版（S4 长世界书夹具）",
            "description": (
                "S4 真机批次夹具角色：用于承载 393KB 世界书、长字段与混合时间线用例。"
            ),
            "personality": "夹具角色，不含人设意图，仅承载世界书与长字段。",
            "scenario": "S4 真机验证批次。",
            "first_mes": "（夹具角色，仅用于导入导出与长字段用例。）",
            "creator_notes": "S4 fixture；来源 E:\\Tavern\\崩铁-匹诺康尼補充版.json",
            "tags": ["S4-fixture", "world-book"],
            "character_book": book,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "fixtures"))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = CORPUS.read_bytes()
    corpus_text = raw.decode("utf-8")
    corpus = json.loads(corpus_text)

    # 夹具 A：原文整体作为一条消息正文。
    fix_a = out_dir / "fix-a-single-msg.txt"
    fix_a.write_bytes(raw)

    # 夹具 B：80 条 × 约 5 KB，四个聊天各一套。
    chunk_size = max(1, len(corpus_text) // CHUNK_COUNT)
    chat_sets: dict[str, list[str]] = {}
    for tag in CHAT_TAGS:
        messages = []
        for seq in range(CHUNK_COUNT):
            slice_text = corpus_text[seq * chunk_size : (seq + 1) * chunk_size]
            if not slice_text and seq > 0:
                break
            messages.append(f"FIXTURE-PINOCONY-{tag}-{seq:02d}\n{slice_text}")
        chat_sets[tag] = messages
    fix_b = out_dir / "fix-b-chunks.json"
    sizes = [
        len(message.encode("utf-8"))
        for messages in chat_sets.values()
        for message in messages
    ]
    set_bytes = sum(
        len(message.encode("utf-8")) for message in chat_sets[CHAT_TAGS[0]]
    )
    fix_b.write_text(
        json.dumps(
            {
                "note": "S4 夹具 B：80 条 × 约 5KB，按聊天标记，总量超 256KiB。",
                "source": str(CORPUS),
                "chunk_count": CHUNK_COUNT,
                "sets": chat_sets,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    # 夹具 C：世界书 → 角色卡 v3。
    book = convert_world_book(corpus)
    card = build_card(book, corpus_text)
    fix_c = out_dir / "fix-c-worldbook-card.json"
    fix_c.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")

    # 夹具 B2：80 条 × 约 1 KB，总量低于 256 KiB —— 专门隔离"条数≥80"触发路径。
    small_sets: dict[str, list[str]] = {}
    small_chunk = max(1, len(corpus_text) // (CHUNK_COUNT * 5))
    for tag in CHAT_TAGS[:1]:
        small_sets[tag] = [
            f"FIXTURE-PINOCONY-SMALL-{tag}-{seq:02d}\n"
            + corpus_text[seq * small_chunk : (seq + 1) * small_chunk]
            for seq in range(CHUNK_COUNT)
        ]
    fix_b2 = out_dir / "fix-b2-count-only.json"
    small_sizes = [len(m.encode("utf-8")) for m in small_sets[CHAT_TAGS[0]]]
    small_total = sum(small_sizes)
    fix_b2.write_text(
        json.dumps(
            {
                "note": "S4 夹具 B2：80 条 × 约 1KB，合计 < 256KiB，用于隔离条数阈值",
                "source": str(CORPUS),
                "chunk_count": CHUNK_COUNT,
                "total_bytes": small_total,
                "sets": small_sets,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "script": str(Path(__file__).resolve()),
        "source": {
            "path": str(CORPUS),
            "size": len(raw),
            "sha256": _sha256(raw),
            "kind": "SillyTavern world info export",
            "entry_count": len(corpus.get("entries", {})),
        },
        "fixtures": [
            {
                "id": "fix-a",
                "path": str(fix_a),
                "size": fix_a.stat().st_size,
                "sha256": _sha256(fix_a.read_bytes()),
                "usage": "作为一条消息正文发送；402,315 B > 256 KiB，直接触发正文阈值",
                "import": "协议写入：chat.submit(text=整篇原文)",
            },
            {
                "id": "fix-b",
                "path": str(fix_b),
                "size": fix_b.stat().st_size,
                "sha256": _sha256(fix_b.read_bytes()),
                "usage": (
                    f"{CHUNK_COUNT} 条 × {min(sizes)}~{max(sizes)} B（均值 "
                    f"{sum(sizes) // len(sizes)} B），四套（chat1..chat4）；"
                    f"单套正文合计 {set_bytes} B > 256 KiB"
                ),
                "import": "协议写入：chat.submit 逐条提交，标记 FIXTURE-PINOCONY-{chat}-{seq}",
            },
            {
                "id": "fix-b2",
                "path": str(fix_b2),
                "size": fix_b2.stat().st_size,
                "sha256": _sha256(fix_b2.read_bytes()),
                "usage": (
                    f"{CHUNK_COUNT} 条 × {min(small_sizes)}~{max(small_sizes)} B，"
                    f"合计 {small_total} B < 256 KiB，专门隔离\"条数≥80\"触发路径"
                ),
                "import": "协议写入：chat.submit 逐条提交后立即 task.cancel（不产生 80 轮真实模型往返）",
            },
            {
                "id": "fix-c",
                "path": str(fix_c),
                "size": fix_c.stat().st_size,
                "sha256": _sha256(fix_c.read_bytes()),
                "usage": "长世界书/角色卡体，绑定两个项目、四个聊天",
                "import": "协议写入：card.import_json(path=该文件)",
            },
        ],
        "conversion_note": (
            "酒馆原生字段 key/keysecondary/order/disable → v3 keys/secondary_keys/"
            "insertion_order/enabled；position 归一化到契约支持的 0/1/4。"
        ),
    }
    manifest_path = out_dir / "fixtures-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
