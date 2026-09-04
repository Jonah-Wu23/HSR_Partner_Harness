"""Character Card v2/v3 JSON 编解码与白厄样例往返测试（V0.4.0 逻辑底座）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pair_harness.character_cards import (
    FIXED_TTS_MODEL,
    CardImportError,
    load_card_json,
    load_card_payload,
    dump_card_v3,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "character_cards" / "白厄（3.4前）.json"
# 主回归样例的原始路径；存在时用真实文件做第二轮校验。
LIVE_SAMPLE = Path(r"E:\Tavern\白厄（3.4前）.json")


def _load_sample(path: Path = FIXTURE) -> str:
    return path.read_text(encoding="utf-8")


def test_import_baiyu_sample_core_fields() -> None:
    result = load_card_json(_load_sample())
    card = result.card
    assert card.spec == "chara_card_v3"
    assert card.spec_version == "3.0"
    assert card.name == "白厄（3.4前）"
    assert "{{char}}" in card.personality
    assert "{{char}}" in card.scenario
    assert card.system_prompt.startswith("(使用中文进行对话)")
    assert "Anti-Assistant" in card.post_history_instructions
    assert card.first_mes.startswith("*午后的光穿过回廊的拱门")
    assert "<START>" in card.mes_example


def test_import_baiyu_sample_five_alternate_greetings() -> None:
    card = load_card_json(_load_sample()).card
    assert len(card.alternate_greetings) == 5
    assert all(greeting.strip() for greeting in card.alternate_greetings)
    assert card.greeting_count() == 6
    assert card.group_only_greetings == []


def test_import_baiyu_sample_world_book() -> None:
    card = load_card_json(_load_sample()).card
    book = card.character_book
    assert book is not None
    assert book.name == "翁法罗斯"
    assert len(book.entries) == 20
    first = book.entries[0]
    assert first.entry_id == 0
    assert "翁法罗斯" in first.keys
    assert first.constant is False and first.selective is True
    assert first.insertion_order == 100
    assert first.position == "before_char"
    assert first.use_regex is True
    # SillyTavern 条目扩展（probability/depth/role 等）原样保留。
    assert first.extensions["probability"] == 100
    assert first.extensions["depth"] == 4
    deep = book.entries[2]
    assert "权杖δ-me13" in deep.keys


def test_import_baiyu_sample_extensions_and_root_extras() -> None:
    result = load_card_json(_load_sample())
    card = result.card
    # v3 样例 data 与根级同字段时以 data 为权威，不从根级回退。
    assert result.report.normalized_from_root == []
    # data.extensions 的第三方扩展原样保留。
    assert card.extensions["talkativeness"] == "0.55"
    assert card.extensions["fav"] is False
    assert card.extensions["world"] == "翁法罗斯"
    depth = card.depth_prompt
    assert depth is not None and depth["depth"] == 4 and depth["role"] == "system"
    # 根级未知字段原样保留。
    assert card.root_extras["creatorcomment"] == ""
    assert card.root_extras["avatar"] == "none"
    assert card.root_extras["create_date"] == "2026-2-27 @20h 11m 01s 800ms"
    assert card.root_extras["talkativeness"] == "0.55"
    # 兼容报告列出被保留的第三方扩展与根级字段。
    assert "data.extensions.world" in result.report.preserved
    assert "create_date" in result.report.preserved


def test_baiyu_roundtrip_import_export_import() -> None:
    first = load_card_json(_load_sample())
    exported = dump_card_v3(first.card)
    second = load_card_json(exported)
    # 归一化模型往返等价：标准字段、问候、世界书、扩展、根级字段均不丢失。
    assert second.card == first.card
    payload = json.loads(exported)
    assert payload["spec"] == "chara_card_v3"
    assert payload["spec_version"] == "3.0"
    assert payload["data"]["character_book"]["name"] == "翁法罗斯"
    assert len(payload["data"]["alternate_greetings"]) == 5
    assert payload["data"]["extensions"]["depth_prompt"]["depth"] == 4
    assert payload["creatorcomment"] == ""


@pytest.mark.skipif(not LIVE_SAMPLE.exists(), reason="原始样例文件不在本机")
def test_live_baiyu_sample_roundtrip() -> None:
    live = load_card_json(LIVE_SAMPLE.read_text(encoding="utf-8"))
    again = load_card_json(dump_card_v3(live.card))
    assert again.card == live.card


def test_import_v2_root_only_card() -> None:
    v2 = {
        "name": "旧版卡",
        "description": "根级描述",
        "first_mes": "你好",
        "spec": "chara_card_v2",
    }
    result = load_card_payload(v2)
    card = result.card
    assert card.spec == "chara_card_v2"
    assert card.description == "根级描述"
    assert "缺少 data 块" in "".join(result.report.warnings)


def test_data_field_preferred_over_root() -> None:
    payload = {
        "spec": "chara_card_v3",
        "name": "根级名字",
        "description": "根级描述",
        "data": {"name": "正式名字", "description": "正式描述"},
    }
    card = load_card_payload(payload).card
    assert card.name == "正式名字"
    assert card.description == "正式描述"


def test_root_fallback_recorded_in_report() -> None:
    payload = {
        "spec": "chara_card_v3",
        "name": "卡名",
        "description": "只在根级",
        "data": {"name": "卡名"},
    }
    result = load_card_payload(payload)
    assert result.card.description == "只在根级"
    assert "description" in result.report.normalized_from_root


def test_unknown_third_party_extension_preserved() -> None:
    regex_scripts = [{"id": "rs1", "script": "example", "placement": []}]
    payload = {
        "spec": "chara_card_v3",
        "name": "带扩展的卡",
        "data": {
            "name": "带扩展的卡",
            "extensions": {
                "regex_scripts": regex_scripts,
                "talkativeness": "0.4",
                "depth_prompt": {"prompt": "p", "depth": 2, "role": "system"},
            },
        },
    }
    card = load_card_payload(payload).card
    again = load_card_json(dump_card_v3(card)).card
    assert again.extensions["regex_scripts"] == regex_scripts
    assert again.depth_prompt == {"prompt": "p", "depth": 2, "role": "system"}


def test_unknown_data_field_and_zero_insertion_order_preserved() -> None:
    payload = {
        "spec": "chara_card_v3",
        "data": {
            "name": "未来字段卡",
            "future_data_field": {"enabled": True},
            "character_book": {
                "entries": [
                    {
                        "keys": ["zero"],
                        "content": "保留零顺序",
                        "insertion_order": 0,
                        "constant": False,
                        "selective": True,
                        "use_regex": False,
                    }
                ]
            },
        },
    }
    first = load_card_payload(payload)
    assert first.card.data_extras == {"future_data_field": {"enabled": True}}
    assert "data.future_data_field" in first.report.preserved
    entry = first.card.character_book.entries[0]
    assert entry.insertion_order == 0
    assert entry.use_regex is False
    second = load_card_json(dump_card_v3(first.card)).card
    assert second.data_extras == first.card.data_extras
    assert second.character_book.entries[0].insertion_order == 0


def test_hsr_extension_roundtrip_and_fixed_model() -> None:
    payload = {
        "spec": "chara_card_v3",
        "name": "HSR 扩展卡",
        "data": {
            "name": "HSR 扩展卡",
            "extensions": {
                "world": "自定义世界",
                "hsr": {
                    "schema_version": "1.0",
                    "world_architecture": {"world_foundation": {"one_line_pitch": "x"}},
                    "character_architecture": {"identity": {"full_name": "y"}},
                    "relationship_system": {"relationship_gates": {"stages": []}},
                    "event_system": {"opening_scenarios": {}},
                    "narrative_rules": {"pacing": {}},
                    "command_panels": [
                        {"command": "$状态", "function": "状态面板", "output_format": "<div/>"}
                    ],
                    "avatar_asset": {
                        "asset_id": "asset-1",
                        "source": "png_import",
                        "source_ref": "original.png",
                        "future_field": 1,
                    },
                    "voice_profile": {
                        "state": "voice_ready",
                        "voice_id": "qwen-audio-3.0-tts-flash-demo-xxxx",
                        "target_model": "qwen-audio-3.0-tts-flash",
                        "creation_mode": "clone",
                        "prefix": "demo",
                    },
                },
            },
        },
    }
    result = load_card_payload(payload)
    card = result.card
    assert card.extensions["world"] == "自定义世界"
    hsr = card.hsr
    assert hsr is not None
    assert hsr.schema_version == "1.0"
    assert hsr.command_panels[0]["command"] == "$状态"
    assert hsr.avatar_asset is not None
    assert hsr.avatar_asset.extras == {"future_field": 1}
    assert hsr.voice_profile is not None
    assert hsr.voice_profile.voice_id.startswith("qwen-audio-3.0-tts-flash-")
    # 声明式面板标记为“已保留但未运行”。
    assert "data.extensions.hsr.command_panels" in result.report.not_executed
    again = load_card_json(dump_card_v3(card)).card
    assert again.hsr is not None
    assert again.hsr.avatar_asset is not None
    assert again.hsr.avatar_asset.extras == {"future_field": 1}
    assert again.hsr.voice_profile == hsr.voice_profile
    assert again.extensions["world"] == "自定义世界"


def test_imported_foreign_voice_model_normalized_to_fixed() -> None:
    payload = {
        "spec": "chara_card_v3",
        "name": "外部卡",
        "data": {
            "name": "外部卡",
            "extensions": {
                "hsr": {
                    "voice_profile": {
                        "state": "voice_ready",
                        "voice_id": "some-id",
                        "target_model": "cosyvoice-v3.5-plus",
                    }
                }
            },
        },
    }
    result = load_card_payload(payload)
    voice = result.card.hsr.voice_profile
    assert voice is not None
    assert voice.target_model == FIXED_TTS_MODEL
    assert any("固定模型" in warning for warning in result.report.warnings)


def test_world_book_unknown_entry_fields_preserved() -> None:
    payload = {
        "spec": "chara_card_v3",
        "name": "世界书卡",
        "data": {
            "name": "世界书卡",
            "character_book": {
                "name": "书",
                "entries": [
                    {
                        "id": "abc",
                        "keys": ["k"],
                        "content": "c",
                        "unknown_top": {"a": 1},
                        "case_sensitive": True,
                    }
                ],
                "unknown_book_field": "v",
            },
        },
    }
    card = load_card_payload(payload).card
    book = card.character_book
    assert book is not None
    entry = book.entries[0]
    assert entry.entry_id == "abc"
    assert entry.extras == {"unknown_top": {"a": 1}}
    assert entry.case_sensitive is True
    assert book.extras == {"unknown_book_field": "v"}
    again = load_card_json(dump_card_v3(card)).card
    assert again.character_book is not None
    assert again.character_book.entries[0].extras == {"unknown_top": {"a": 1}}
    assert again.character_book.extras == {"unknown_book_field": "v"}


def test_import_failures_preserve_reasons() -> None:
    with pytest.raises(CardImportError, match="JSON 解析失败"):
        load_card_json("{not json")
    with pytest.raises(CardImportError, match="JSON 对象"):
        load_card_json("[1,2]")
    with pytest.raises(CardImportError, match="name"):
        load_card_json(json.dumps({"spec": "chara_card_v3", "data": {}}))
    with pytest.raises(CardImportError, match="不支持的 spec"):
        load_card_json(json.dumps({"spec": "unknown_spec", "name": "x"}))
    with pytest.raises(CardImportError, match="data.extensions 必须是 JSON 对象"):
        load_card_json(
            json.dumps({"spec": "chara_card_v3", "data": {"name": "x", "extensions": [1]}})
        )
    with pytest.raises(CardImportError, match="alternate_greetings 必须是字符串数组"):
        load_card_json(
            json.dumps({"spec": "chara_card_v3", "data": {"name": "x", "alternate_greetings": [1]}})
        )
    with pytest.raises(CardImportError, match="character_book 必须是 JSON 对象"):
        load_card_payload({"spec": "chara_card_v3", "data": {"name": "x", "character_book": []}})
    with pytest.raises(CardImportError, match="constant 必须是布尔值"):
        load_card_payload(
            {
                "spec": "chara_card_v3",
                "data": {
                    "name": "x",
                    "character_book": {"entries": [{"constant": "false"}]},
                },
            }
        )
    with pytest.raises(CardImportError, match="hsr.voice_profile 必须是 JSON 对象"):
        load_card_payload(
            {
                "spec": "chara_card_v3",
                "data": {
                    "name": "x",
                    "extensions": {"hsr": {"voice_profile": "bad"}},
                },
            }
        )


def test_export_writes_root_compat_copies() -> None:
    card = load_card_json(_load_sample()).card
    payload = json.loads(dump_card_v3(card))
    for key in ("name", "description", "personality", "scenario", "first_mes",
                "mes_example", "tags", "alternate_greetings"):
        assert payload[key] == payload["data"][key]
    # 根级未知字段写回根，不进入 data。
    assert "create_date" in payload
    assert "create_date" not in payload["data"]


# ---------------------------------------------------------------- V0.3.7 兼容报告增补


def test_report_world_book_not_run_fields_declared() -> None:
    """条目 extensions 声明 probability/sticky/group/selectiveLogic 存而不运行。"""
    result = load_card_payload(
        {
            "spec": "chara_card_v3",
            "data": {
                "name": "存而不运行卡",
                "character_book": {
                    "entries": [
                        {
                            "keys": ["k"],
                            "content": "c",
                            "extensions": {
                                "probability": 100,
                                "sticky": 0,
                                "group": "A",
                                "selectiveLogic": 9,
                            },
                        }
                    ]
                },
            },
        }
    )
    ne = result.report.not_executed
    assert "character_book.entries[0].probability（存而不运行）" in ne
    assert "character_book.entries[0].sticky（存而不运行）" in ne
    assert "character_book.entries[0].group（存而不运行）" in ne
    # selectiveLogic 越界进 warnings，同时它本身是合法字段不在 not_executed。
    assert any("selectiveLogic 越界: 9" in w for w in result.report.warnings)


def test_report_world_book_not_run_fields_merged_by_entry_count() -> None:
    """同字段多条目合并为 entries[...] 计数形式。"""
    result = load_card_payload(
        {
            "spec": "chara_card_v3",
            "data": {
                "name": "合并卡",
                "character_book": {
                    "entries": [
                        {"keys": ["a"], "content": "1", "extensions": {"probability": 100}},
                        {"keys": ["b"], "content": "2", "extensions": {"probability": 60}},
                    ]
                },
            },
        }
    )
    assert (
        "character_book.entries[...].probability（存而不运行，2 处）"
        in result.report.not_executed
    )


def test_report_book_level_recursive_scanning_not_run() -> None:
    """CharacterBook 级 recursive_scanning（书声明）同样报告。"""
    result = load_card_payload(
        {
            "spec": "chara_card_v3",
            "data": {
                "name": "书级扫描卡",
                "character_book": {"recursive_scanning": False, "entries": []},
            },
        }
    )
    assert "character_book.recursive_scanning（存而不运行）" in result.report.not_executed


def test_report_invalid_regex_key_degrades_to_warning() -> None:
    """/bad[/i 形态 + use_regex=true 编译失败 → warnings 退化记录。"""
    result = load_card_payload(
        {
            "spec": "chara_card_v3",
            "data": {
                "name": "非法正则卡",
                "character_book": {
                    "entries": [
                        {"keys": ["/bad[/i"], "content": "c", "use_regex": True}
                    ]
                },
            },
        }
    )
    assert any(
        "character_book.entries[0].keyword 非法正则已退化字面匹配: /bad[/i" in w
        for w in result.report.warnings
    )


def test_report_non_whitelisted_macros_scanned_and_counted() -> None:
    """{{setvar}}/{{time}} 报告，{{char}}/{{user}} 白名单不报告。"""
    result = load_card_payload(
        {
            "spec": "chara_card_v3",
            "data": {
                "name": "宏卡",
                "personality": "{{setvar::x::1}} 我叫 {{char}}，你好 {{user}}",
                "description": "现在是 {{time}} 和 {{time}}",
            },
        }
    )
    ne = result.report.not_executed
    assert "macro:{{setvar::x::1}} @ data.personality（未展开，1 处）" in ne
    assert "macro:{{time}} @ data.description（未展开，2 处）" in ne
    assert not any(x.startswith("macro:{{char}}") for x in ne)
    assert not any(x.startswith("macro:{{user}}") for x in ne)


def test_report_runtime_trigger_non_turn_not_run() -> None:
    """runtime_trigger 非 turn kind 记录，turn kind 不记录。"""
    result = load_card_payload(
        {
            "spec": "chara_card_v3",
            "data": {
                "name": "mufy 卡",
                "extensions": {
                    "hsr": {
                        "event_system": {
                            "chapter1": {
                                "runtime_trigger": {"kind": "time", "at": "洛克城"},
                                "content": "夜幕降临",
                            },
                            "chapter2": {
                                "runtime_trigger": {"kind": "turn", "turn": 3},
                                "content": "第三回合",
                            },
                        }
                    }
                },
            },
        }
    )
    ne = result.report.not_executed
    assert any(
        "hsr.event_system.chapter1.runtime_trigger.kind=time（存而不运行）" in x
        for x in ne
    )
    assert not any(
        "runtime_trigger.kind=turn" in x and "chapter2" in x for x in ne
    )


def test_report_depth_prompt_whitelisted_user_not_reported() -> None:
    """depth_prompt.prompt 中 {{user}} 属白名单，不进 not_executed。"""
    result = load_card_payload(
        {
            "spec": "chara_card_v3",
            "data": {
                "name": "深度提示卡",
                "extensions": {
                    "depth_prompt": {
                        "prompt": "对 {{user}} 保持陪伴",
                        "depth": 4,
                        "role": "system",
                    }
                },
            },
        }
    )
    assert not any("macro:{{user}}" in x for x in result.report.not_executed)


def test_baiyu_fixture_report_not_run_labels_and_whitelist() -> None:
    """白厄 fixture：probability/sticky 等存而不运行标签存在，宏白名单不报告。"""
    result = load_card_json(_load_sample())
    ne = result.report.not_executed
    assert any(".probability（存而不运行" in x for x in ne)
    assert any(".sticky（存而不运行" in x for x in ne)
    assert any(".group（存而不运行" in x for x in ne)
    assert not any(x == "macro:{{char}}" or x.startswith("macro:{{char}}") for x in ne)
    assert not any(x == "macro:{{user}}" or x.startswith("macro:{{user}}") for x in ne)


def test_report_scan_idempotent() -> None:
    """同一 payload 导入两次，兼容报告 JSON 完全一致。"""
    payload = {
        "spec": "chara_card_v3",
        "data": {
            "name": "幂等卡",
            "personality": "{{setvar::a::1}} 内容",
            "character_book": {
                "recursive_scanning": True,
                "entries": [
                    {
                        "keys": ["/bad[/i"],
                        "content": "c",
                        "use_regex": True,
                        "extensions": {"probability": 100, "selectiveLogic": 5},
                    }
                ],
            },
            "extensions": {
                "hsr": {
                    "event_system": {
                        "t1": {
                            "runtime_trigger": {"kind": "time", "at": "x"},
                            "content": "触发",
                        }
                    }
                }
            },
        },
    }
    first = json.dumps(load_card_payload(payload).report.to_dict(), sort_keys=True)
    second = json.dumps(load_card_payload(payload).report.to_dict(), sort_keys=True)
    assert first == second
