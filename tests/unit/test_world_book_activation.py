"""世界书运行时激活引擎测试（V0.3.7 契约 §3、§6、§12 锚点）。"""

from __future__ import annotations

from pair_harness.character_cards import (
    ActivatedEntry,
    CharacterBook,
    WorldBookEntry,
    activate_world_book,
    collect_turn_triggers,
    iter_runtime_trigger_declarations,
    token_estimate,
)


def _entry(**kwargs: object) -> WorldBookEntry:
    defaults = {
        "keys": [],
        "secondary_keys": [],
        "content": "",
        "enabled": True,
        "constant": False,
        "selective": True,
        "insertion_order": 100,
        "position": "before_char",
        "use_regex": True,
        "comment": "",
        "entry_id": None,
        "extensions": {},
        "extras": {},
    }
    defaults.update(kwargs)
    return WorldBookEntry(**defaults)


def _book(entries: list[WorldBookEntry], **kwargs: object) -> CharacterBook:
    return CharacterBook(entries=entries, **kwargs)


def _texts(*lines: str) -> list[str]:
    return list(lines)


# ---------------------------------------------------------------- 主关键字


def test_main_key_hit_and_miss() -> None:
    book = _book([
        _entry(entry_id=1, keys=["星星"], content="命中"),
        _entry(entry_id=2, keys=["月亮"], content="未命中"),
    ])
    result = activate_world_book(book, _texts("今晚的星星很亮"))
    assert [e.entry.entry_id for e in result.before_char] == [1]
    assert result.before_char[0].matched_keys == ["星星"]
    assert result.diagnostics.activated_count == 1


def test_empty_keys_skipped() -> None:
    book = _book([_entry(entry_id=1, keys=[], content="无关键字")])
    result = activate_world_book(book, _texts("x"))
    assert result.before_char == []
    assert result.diagnostics.activated_count == 0


# ---------------------------------------------------------------- 次关键字


def test_secondary_key_four_logics() -> None:
    def run(entry: WorldBookEntry, *lines: str) -> list[ActivatedEntry]:
        return activate_world_book(_book([entry]), _texts(*lines)).before_char

    # AND_ANY(0)：任一次 key 命中 -> 激活
    e = _entry(entry_id=1, keys=["主"], secondary_keys=["次1", "次2"], content="A")
    assert run(e, "主 次1")
    assert run(e, "主") == []
    # NOT_ALL(1)：并非全部命中 -> 激活
    e = _entry(entry_id=2, keys=["主"], secondary_keys=["次1", "次2"], content="B",
               extensions={"selectiveLogic": 1})
    assert run(e, "主 次1")
    assert run(e, "主 次1 次2") == []
    # NOT_ANY(2)：全部未命中 -> 激活
    e = _entry(entry_id=3, keys=["主"], secondary_keys=["次1", "次2"], content="C",
               extensions={"selectiveLogic": 2})
    assert run(e, "主")
    assert run(e, "主 次1") == []
    # AND_ALL(3)：全部命中 -> 激活
    e = _entry(entry_id=4, keys=["主"], secondary_keys=["次1", "次2"], content="D",
               extensions={"selectiveLogic": 3})
    assert run(e, "主 次1 次2")
    assert run(e, "主 次1") == []


def test_selective_false_ignores_secondary() -> None:
    book = _book([
        _entry(entry_id=1, keys=["主"], secondary_keys=["次"], content="A", selective=False),
        _entry(entry_id=2, keys=["主"], secondary_keys=["次"], content="B", selective=True,
               extensions={"selectiveLogic": 0}),
    ])
    result = activate_world_book(book, _texts("主"))
    # 条目1：selective=False 次 key 不参与 -> 命中；条目2：AND_ANY 次 key 未命中 -> 不命中。
    assert [e.entry.entry_id for e in result.before_char] == [1]


def test_selective_logic_out_of_range_warns_and_falls_back() -> None:
    book = _book([
        _entry(entry_id=1, keys=["主"], secondary_keys=["次"], content="A",
               extensions={"selectiveLogic": 7}),
    ])
    result = activate_world_book(book, _texts("主 次"))
    # 越界记 warning 并按 0(AND_ANY) 处理；次 key 命中 -> 激活。
    assert [e.entry.entry_id for e in result.before_char] == [1]
    assert any("selectiveLogic" in w for w in result.diagnostics.warnings)


def test_matched_keys_recorded() -> None:
    book = _book([
        _entry(entry_id=1, keys=["星", "月"], secondary_keys=["夜"], content="A",
               extensions={"selectiveLogic": 3}),
    ])
    result = activate_world_book(book, _texts("星星 夜"))
    # 主 key「星」命中、次 key「夜」命中；AND_ALL 全部命中。
    assert result.before_char[0].matched_keys == ["星", "夜"]


# ---------------------------------------------------------------- 常驻与禁用


def test_constant_unconditional_and_budget_exempt() -> None:
    book = _book([
        _entry(entry_id=1, keys=[], content="恒定超长内容内容内容", insertion_order=200,
               constant=True, comment="恒定条目"),
        _entry(entry_id=2, keys=["x"], content="短", insertion_order=100, comment="小序条目"),
    ], token_budget=3)
    result = activate_world_book(book, _texts("x"))
    # constant 无条件激活（不做关键字匹配、不受预算排除）；非恒定条目溢出排除。
    assert [e.entry.entry_id for e in result.before_char] == [1]
    assert result.diagnostics.overflow_entries == ["小序条目"]


def test_constant_exempt_from_budget_after_overflow_point() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="长长长长长", insertion_order=200,
               comment="大序非恒定"),
        _entry(entry_id=2, keys=["x"], content="短", insertion_order=100,
               constant=True, comment="恒定条目"),
    ], token_budget=3)
    result = activate_world_book(book, _texts("x"))
    # 大序非恒定条目先触发溢出；其后 constant 条目仍激活。
    assert [e.entry.entry_id for e in result.before_char] == [2]
    assert result.diagnostics.overflow_entries == ["大序非恒定"]
    assert result.diagnostics.activated_count == 1


def test_enabled_false_skipped() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="启用", enabled=True),
        _entry(entry_id=2, keys=["x"], content="禁用", enabled=False),
    ])
    result = activate_world_book(book, _texts("x"))
    assert [e.entry.entry_id for e in result.before_char] == [1]
    assert result.diagnostics.activated_count == 1


# ---------------------------------------------------------------- 正则与大小写


def test_regex_form_valid() -> None:
    book = _book([
        _entry(entry_id=1, keys=["/星星/"], content="A"),
        _entry(entry_id=2, keys=["/stars/i"], content="B"),
    ])
    result = activate_world_book(book, _texts("看见星星闪耀 STARS"))
    assert [e.entry.entry_id for e in result.before_char] == [1, 2]
    assert result.diagnostics.warnings == []


def test_regex_invalid_degrade_literal_with_warning() -> None:
    book = _book([
        _entry(entry_id=1, keys=["/[a-"], content="A", comment="未字面命中"),
        _entry(entry_id=2, keys=["/("], content="B", comment="字面命中"),
    ])
    result = activate_world_book(book, _texts("普通文本 /( 出现"))
    # 非法正则退化为字面包含：条目1 原文不在 haystack 未命中，条目2 字面命中。
    assert [e.entry.entry_id for e in result.before_char] == [2]
    assert len(result.diagnostics.warnings) == 2
    assert all("退化" in w for w in result.diagnostics.warnings)


def test_use_regex_bare_key() -> None:
    book = _book([
        _entry(entry_id=1, keys=["星{2}"], content="正则命中", use_regex=True),
        _entry(entry_id=2, keys=["星{2}"], content="字面未命中", use_regex=False),
    ])
    result = activate_world_book(book, _texts("星星"))
    # use_regex=True 把 key 按正则编译（星{2} 匹配“星星”）；False 则字面匹配不命中。
    assert [e.entry.entry_id for e in result.before_char] == [1]


def test_case_sensitivity_matching() -> None:
    book = _book([
        _entry(entry_id=1, keys=["star"], content="默认不敏感", case_sensitive=None),
        _entry(entry_id=2, keys=["star"], content="敏感不命中", case_sensitive=True),
        _entry(entry_id=3, keys=["Star"], content="敏感命中", case_sensitive=True),
    ])
    result = activate_world_book(book, _texts("A Star is born"))
    assert [e.entry.entry_id for e in result.before_char] == [1, 3]


def test_use_regex_case_sensitive_bare_key_no_i_flag() -> None:
    book = _book([
        _entry(entry_id=1, keys=["star"], content="敏感正则不命中", use_regex=True,
               case_sensitive=True),
        _entry(entry_id=2, keys=["Star"], content="敏感正则命中", use_regex=True,
               case_sensitive=True),
    ])
    result = activate_world_book(book, _texts("A Star"))
    # case_sensitive 时裸 key 正则不带 i flag。
    assert [e.entry.entry_id for e in result.before_char] == [2]


# ---------------------------------------------------------------- 位置


def test_position_dispatch_and_unsupported_excluded() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="前", position="before_char"),
        _entry(entry_id=2, keys=["x"], content="后", position="after_char"),
        _entry(entry_id=3, keys=["x"], content="深度", position="atDepth",
               extensions={"depth": 2, "role": 1}),
        _entry(entry_id=4, keys=["x"], content="ANTop", position="ANTop"),
        _entry(entry_id=5, keys=["x"], content="数值2", position=2),
        _entry(entry_id=6, keys=["x"], content="数值5", position=5),
    ])
    result = activate_world_book(book, _texts("x"))
    assert [e.entry.entry_id for e in result.before_char] == [1]
    assert [e.entry.entry_id for e in result.after_char] == [2]
    assert [(g.depth, g.role) for g in result.depth_entries] == [(2, "user")]
    # 不支持位置：不注入、逐条进入 not_run_fields 聚合。
    assert result.diagnostics.activated_count == 3
    labels = result.diagnostics.not_run_fields
    assert "不支持位置(ANTop)" in labels
    assert "不支持位置(2)" in labels
    assert "不支持位置(5)" in labels


# ---------------------------------------------------------------- 顺序


def test_activation_priority_consumes_budget() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="甲", insertion_order=200, comment="大序"),
        _entry(entry_id=2, keys=["x"], content="乙乙乙乙乙", insertion_order=100, comment="小序"),
    ], token_budget=3)
    result = activate_world_book(book, _texts("x"))
    # 激活优先序：大 order 先耗预算，小 order 条目整体溢出排除。
    assert [e.entry.entry_id for e in result.before_char] == [1]
    assert result.diagnostics.overflow_entries == ["小序"]


def test_join_order_small_insertion_first() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="小序", insertion_order=100),
        _entry(entry_id=2, keys=["x"], content="大序", insertion_order=200),
    ])
    result = activate_world_book(book, _texts("x"))
    # 桶内拼接序：insertion_order 升序（小 order 在前）。
    assert [e.entry.entry_id for e in result.before_char] == [1, 2]
    assert [e.text for e in result.before_char] == ["小序", "大序"]


# ---------------------------------------------------------------- 预算


def test_budget_declared_and_default_2048() -> None:
    book = _book([_entry(keys=["x"], content="c")], token_budget=100)
    result = activate_world_book(book, _texts("x"))
    assert result.diagnostics.budget_total == 100
    book_default = _book([_entry(keys=["x"], content="c")], token_budget=None)
    result_default = activate_world_book(book_default, _texts("x"))
    assert result_default.diagnostics.budget_total == 2048  # round(0.25 * 8192)
    # context_tokens 可覆盖冻结预算基准。
    result_custom = activate_world_book(book_default, _texts("x"), context_tokens=8000)
    assert result_custom.diagnostics.budget_total == 2000


def test_budget_overflow_excludes_entry_and_records_ref() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="长长长长长", insertion_order=200,
               comment="先触发溢出"),
        _entry(keys=["x"], content="后", insertion_order=100,
               entry_id="id2", comment=""),
    ], token_budget=1)
    result = activate_world_book(book, _texts("x"))
    # 首个条目 step_cost 即达预算，其后所有非 constant 条目一并排除。
    assert result.before_char == []
    assert result.diagnostics.overflow_entries == ["先触发溢出", "id2"]
    assert result.diagnostics.budget_used == 0


def test_budget_used_is_injected_content_estimate() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="甲", insertion_order=100),
    ], token_budget=1000)
    result = activate_world_book(book, _texts("x"))
    assert result.diagnostics.budget_used == token_estimate("甲") == 1


# ---------------------------------------------------------------- token 估算


def test_token_estimate_mixed() -> None:
    assert token_estimate("你好世界") == 4
    assert token_estimate("中文abc") == 3      # 2 CJK + ceil(3/4)
    assert token_estimate("Hello") == 2        # ceil(5/4)
    assert token_estimate("abcdefgh") == 2     # ceil(8/4)
    assert token_estimate("") == 0
    # 假名 + 谚文均计入 CJK。
    assert token_estimate("仮名カナ한글") == 6
    # 换行符计入非 CJK。
    assert token_estimate("甲\n乙") == 3


# ---------------------------------------------------------------- 扫描缓冲与深度聚合


def test_scan_depth_buffer() -> None:
    book = _book([
        _entry(entry_id=1, keys=["旧"], content="A"),
        _entry(entry_id=2, keys=["新"], content="B"),
    ], scan_depth=1)
    result = activate_world_book(book, _texts("旧消息", "新消息"))
    # 只扫描最后 1 条；「旧」不命中。
    assert [e.entry.entry_id for e in result.before_char] == [2]
    assert result.diagnostics.scan_depth == 1
    assert result.diagnostics.scanned_message_count == 2


def test_scan_depth_default_two() -> None:
    book = _book([
        _entry(entry_id=1, keys=["旧"], content="A"),
        _entry(entry_id=2, keys=["新"], content="B"),
    ], scan_depth=None)
    result = activate_world_book(book, _texts("旧消息", "新消息"))
    assert [e.entry.entry_id for e in result.before_char] == [1, 2]
    assert result.diagnostics.scan_depth == 2


def test_depth_aggregation_defaults_and_role_map() -> None:
    book = _book([
        _entry(entry_id=1, keys=["x"], content="默认深度", position="atDepth"),
        _entry(entry_id=2, keys=["x"], content="数值角色", position="atDepth",
               extensions={"role": 1}),
        _entry(entry_id=3, keys=["x"], content="同组合并", position="atDepth",
               extensions={"depth": 4, "role": "system"}),
        _entry(entry_id=4, keys=["x"], content="非法角色", position="atDepth",
               extensions={"role": 9}),
        _entry(entry_id=5, keys=["x"], content="指定深度", position="atDepth",
               extensions={"depth": 2}),
    ])
    result = activate_world_book(book, _texts("x"))
    groups = {(g.depth, g.role): [e.entry.entry_id for e in g.entries]
              for g in result.depth_entries}
    # 缺省 depth=4 / role=system：条目 1、3、4 聚合到 (4, system)。
    assert groups[(4, "system")] == [1, 3, 4]
    # 数值 role=1 -> user。
    assert groups[(4, "user")] == [2]
    # 指定 depth=2 独立成组。
    assert groups[(2, "system")] == [5]
    assert any("非法" in w for w in result.diagnostics.warnings)


# ---------------------------------------------------------------- 存而不运行字段


def test_not_run_fields_aggregation() -> None:
    book = _book([
        _entry(
            entry_id=1, keys=["x"], content="A",
            comment="@@activate\n存而不运行样例",
            extensions={
                "probability": 100,
                "useProbability": True,
                "recursive_scanning": True,
                "group": "g",
                "groupOverride": True,
                "groupWeight": 50,
                "sticky": 1,
                "cooldown": 2,
                "delay": 3,
                "min_activations": 1,
                "automation_id": "auto-1",
                "match_persona_description": True,
                "match_character_description": True,
                "scan_depth": 5,
                "ignore_budget": True,
                "world": "外链世界书",
            },
        ),
    ])
    result = activate_world_book(book, _texts("x"))
    fields = result.diagnostics.not_run_fields
    for label in (
        "probability", "useProbability", "recursive_scanning", "group",
        "groupOverride", "groupWeight", "sticky", "cooldown", "delay",
        "min_activations", "automationId", "matchPersona*", "matchCharacter*",
        "条目级scanDepth", "ignoreBudget", "extensions.world",
        "@@activate 装饰器",
    ):
        assert label in fields, f"缺少存而不运行标签 {label}"
    # 激活条目的 not_run_fields 同样携带这些标签。
    assert "probability" in result.before_char[0].not_run_fields


# ---------------------------------------------------------------- 确定性触发


def test_iter_runtime_trigger_declarations_nested() -> None:
    event_system = {
        "opening": {"runtime_trigger": {"kind": "turn", "turn": 1}},
        "nested": {
            "list": [
                {"sub": {"runtime_trigger": {"kind": "turn", "turn": 5, "once": False}}},
                {"plain": 1},
            ]
        },
    }
    declarations = list(iter_runtime_trigger_declarations(event_system))
    assert len(declarations) == 2
    turns = sorted(t["turn"] for _, t in declarations)
    assert turns == [1, 5]


def test_iter_runtime_trigger_only_dict_value() -> None:
    # runtime_trigger 非 dict 值不视为声明。
    event_system = {"bad": {"runtime_trigger": "turn:1"}}
    assert list(iter_runtime_trigger_declarations(event_system)) == []


def test_collect_turn_triggers_once_semantics() -> None:
    def names(hits: list[dict]) -> set[str]:
        return {e["name"] for e in hits}

    event_system = {
        "a": {"name": "a", "runtime_trigger": {"kind": "turn", "turn": 3, "once": True}},
        "b": {"name": "b", "runtime_trigger": {"kind": "turn", "turn": 3, "once": False}},
        "c": {"name": "c", "runtime_trigger": {"kind": "time"}},
        "d": {"name": "d", "runtime_trigger": {"kind": "turn", "turn": 0}},
        "e": {"name": "e", "runtime_trigger": {"kind": "turn", "turn": -1}},
        "f": {"name": "f", "runtime_trigger": {"kind": "turn", "turn": "3"}},
        "g": {"name": "g", "runtime_trigger": {"kind": "turn", "turn": 2}},
    }
    # 第 2 回合：仅 g（once=true 缺省，turn_index == 2）命中。
    assert names(collect_turn_triggers(event_system, 2)) == {"g"}
    # 第 3 回合：a（==3）与 b（>=3）命中。
    assert names(collect_turn_triggers(event_system, 3)) == {"a", "b"}
    # 第 4 回合：仅 b（>=3）命中。
    assert names(collect_turn_triggers(event_system, 4)) == {"b"}


def test_budget_uses_candidate_total_not_duplicated_accumulation() -> None:
    # Codex Review P1 回归：预算判断必须以「候选拼接文本」的总估算为比较
    # 值（此处候选 "甲\n乙" 估 3 < 预算 4），不得再叠加旧 budget_used——
    # 旧实现 1 + 候选总 3 ≥ 4 会把仍在预算内的第二条误排除。
    book = _book([
        _entry(entry_id=1, keys=["x"], content="甲", insertion_order=200),
        _entry(entry_id=2, keys=["x"], content="乙", insertion_order=100),
    ], token_budget=4)
    result = activate_world_book(book, _texts("x"))
    # 桶内拼接序为 insertion_order 升序：小序 2 在前。
    assert [e.entry.entry_id for e in result.before_char] == [2, 1]
    assert result.diagnostics.overflow_entries == []
