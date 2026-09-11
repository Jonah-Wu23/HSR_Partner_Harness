"""世界书运行时激活引擎测试（V0.3.7 契约 §3、§6、§12 锚点）。"""

from __future__ import annotations

import random

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


# ---------------------------------------------------------------- 预算口径（V039-S4-017）


def test_budget_english_counterexample_marginal_not_per_entry() -> None:
    """最小反例：两英文单字符条目的边际之和是 1，而单条估算之和是 2。

    token_estimate 对非 CJK 取 ceil(len/4)，单条估算之和会高于拼接文本的
    整体估算。分量必须按边际归因，才能与 budget_used 对齐。
    """
    book = _book([
        _entry(entry_id=0, keys=["x"], content="a", insertion_order=200),
        _entry(entry_id=1, keys=["x"], content="b", insertion_order=100),
    ], token_budget=100)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    assert [a.text for a in result.before_char] == ["b", "a"]  # 拼接序小序在前
    assert token_estimate("a\nb") == 1
    assert token_estimate("a") + token_estimate("b") == 2      # 单条之和
    assert d.budget_used == 1
    assert d.budget_prunable_used == 1
    assert d.overflow_entries == []
    assert d.warnings == []


def test_budget_marginal_is_reproducible_from_warning_numbers() -> None:
    """分量可从门控累计过程逐步复算：英文常量 + 英文非恒定，超限时告警。

    该用例同时验证「constant 免裁剪仍计入累计门控」：总量超限来自 constant。
    """
    # 预算 27 = 常量边际 25 + 拼接后的 "b" 增量 2：门控恰好未触发（阈值是
    # 候选累计值 >= budget_total），可同时验证常量边际与紧随其后的增量。
    book = _book([
        _entry(entry_id=1, keys=[], content="a" * 99, insertion_order=200,
               constant=True),
        _entry(entry_id=2, keys=["x"], content="b", insertion_order=100),
    ], token_budget=27)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    step1 = token_estimate("a" * 99)
    step2 = token_estimate("a" * 99 + "\n" + "b")
    assert step1 == 25 and step2 == 26           # 单条估算 25 会低估拼接后的 26
    assert d.budget_constant_used == step1 == 25
    assert d.budget_prunable_used == step2 - step1 == 1
    assert d.budget_used == step2 == 26
    assert d.budget_used <= d.budget_total
    assert d.budget_limit_reached is False
    assert d.warnings == []
    assert [e.entry.entry_id for e in result.before_char] == [2, 1]  # 拼接序小序在前


def test_budget_marginal_sum_within_limit_under_rounding() -> None:
    """逐条取整不会让受门控边际之和越过限额（单条估算之和则可能）。

    预算 3、十二条 "a"：单条估算之和为 12（远超限额），而门控接受的边际之和
    为 2；第 5 条起被排除，限额恰好生效。
    """
    book = _book([
        _entry(entry_id=i, keys=["x"], content="a", insertion_order=100 + i)
        for i in range(12)
    ], token_budget=3)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    assert token_estimate("a") * 12 == 12 > d.budget_total   # 单条之和无上界
    assert d.activated_count == 4
    assert d.budget_prunable_used == 2 <= d.budget_total
    assert d.budget_used == 2
    assert d.budget_limit_reached is True
    # 激活序为 insertion_order 降序，故注入的是 8–11 四条；桶内拼接序升序，
    # 故注入集按 8,9,10,11 输出；排除清单按激活序记录其余 8 条。
    assert [e.entry.entry_id for e in result.before_char] == [8, 9, 10, 11]
    assert sorted(d.overflow_entries, key=int) == [str(i) for i in range(0, 8)]


def test_budget_used_splits_into_constant_and_prunable() -> None:
    """常量边际与非恒定边际分开计量，且能还原实际注入体积。

    constant 条目不受预算裁剪（契约 §3.5），但其文本计入累计门控：注入集内
    既有 constant 也有非恒定条目，两个分量各自负责本分区的边际。
    """
    book = _book([
        _entry(entry_id=1, keys=["x"], content="甲乙", insertion_order=300,
               comment="大序非恒定"),
        _entry(entry_id=2, keys=[], content="常驻内容", insertion_order=200,
               constant=True, comment="恒定条目"),
        _entry(entry_id=3, keys=["x"], content="丙丁", insertion_order=100,
               comment="小序非恒定"),
    ], token_budget=3)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    # 激活序：甲乙（估 2 < 3，注入）→ 常驻内容（constant，注入）→ 丙丁（估 8 ≥ 3，排除）。
    assert [e.entry.entry_id for e in result.before_char] == [2, 1]
    assert d.budget_total == 3
    assert d.budget_prunable_used == token_estimate("甲乙") == 2
    assert d.budget_constant_used == token_estimate("甲乙\n常驻内容") - 2
    assert d.budget_used == token_estimate("甲乙\n常驻内容")
    assert d.budget_prunable_used <= d.budget_total
    assert d.budget_limit_reached is True
    # overflow_entries 只列确实未注入的条目（恒定条目不在其中）。
    assert d.overflow_entries == ["小序非恒定"]
    injected = {e.entry.entry_id for e in result.before_char}
    assert 3 not in injected


def test_budget_limit_reached_when_total_stays_within_limit() -> None:
    """限额已生效但注入量本身未超限时，仍必须有可判告警与排除清单。

    注入文本 "常\n常" 估 3 == 限额 3；紧随其后的非恒定条目在门控处被排除，
    单看 budget_used/budget_total 判不出限额已生效，必须依赖
    budget_limit_reached 与 warnings。
    """
    book = _book([
        _entry(entry_id=1, keys=[], content="常", insertion_order=300,
               constant=True),
        _entry(entry_id=2, keys=[], content="常", insertion_order=200,
               constant=True),
        _entry(entry_id=3, keys=["x"], content="甲", insertion_order=100),
        _entry(entry_id=4, keys=["x"], content="乙", insertion_order=90),
    ], token_budget=3)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    assert d.budget_used == token_estimate("常\n常") == 3
    assert d.budget_used == d.budget_total
    # 两条常量的边际：首条 1、第二条（拼接后）2，合计 3。
    assert d.budget_constant_used == 3
    assert d.budget_prunable_used == 0
    assert d.budget_limit_reached is True
    assert len(d.warnings) == 1
    assert "已排除 2 条未注入条目" in d.warnings[0]
    # 溢出清单只列确实未进入提示词的条目（此处条目 3、4）；拼接序为
    # insertion_order 升序，故注入集为 [2, 1]。
    assert [e.entry.entry_id for e in result.before_char] == [2, 1]
    assert d.overflow_entries == ["3", "4"]


def test_budget_constant_alone_exceeds_limit() -> None:
    """constant 单独超限：受门控边际为 0，超限量全部来自 constant。"""
    book = _book([
        _entry(entry_id=1, keys=[], content="长" * 50, insertion_order=100,
               constant=True),
    ], token_budget=4)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    assert d.budget_used == d.budget_constant_used == 50
    assert d.budget_prunable_used == 0
    assert d.budget_limit_reached is False
    assert d.overflow_entries == []
    assert d.warnings and "constant" in d.warnings[0]
    assert [e.entry.entry_id for e in result.before_char] == [1]


def test_budget_within_limit_produces_no_warning() -> None:
    """预算内不产生任何告警（告警只在真实超限或被排除时出现）。"""
    book = _book([
        _entry(entry_id=1, keys=["x"], content="甲", insertion_order=100),
        _entry(entry_id=2, keys=[], content="恒定", insertion_order=90,
               constant=True),
    ], token_budget=100)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    assert d.budget_used <= d.budget_total
    assert d.warnings == []
    assert d.budget_limit_reached is False


def test_budget_diagnostic_defaults_without_book() -> None:
    """无世界书（book=None）时新字段取确定性默认，形状与有书一致。"""
    result = activate_world_book(None, _texts("x"))
    d = result.diagnostics
    assert d.budget_constant_used == 0
    assert d.budget_prunable_used == 0
    assert d.budget_limit_reached is False
    assert d.budget_used == 0
    assert d.overflow_entries == []
    assert d.warnings == []


def test_budget_keeps_empty_content_entries_as_activated() -> None:
    """空正文条目照常激活：进桶、计入 activated_count，自身长度 0。

    冻结门控按插入序逆序求值：先入累计的是「甲」，空正文条目随后并入时累计
    文本从 "甲" 变为 "甲\n"（多出分隔符），因此它的边际并不为 0——空正文条目
    不能假定为不改变注入内容。
    """
    book = _book([
        _entry(entry_id=1, keys=["x"], content="甲", insertion_order=200),
        _entry(entry_id=2, keys=["x"], content="", insertion_order=100),
    ], token_budget=100)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    # 两条都激活：空正文条目仍在桶内（拼接序小序在前）、计入 activated_count。
    assert [e.entry.entry_id for e in result.before_char] == [2, 1]
    assert d.activated_count == 2
    # 边际归因："甲" 先并入（累计 "甲"，边际 1），空正文条目再并入
    # （累计 "甲\n"，边际 1）；它自身长度仍为 0。
    assert token_estimate("") == 0
    assert token_estimate("甲\n") > token_estimate("甲")
    assert d.budget_constant_used == 0
    assert d.budget_prunable_used == 2
    assert d.budget_used == token_estimate("甲\n") == 2
    assert d.budget_limit_reached is False
    assert d.overflow_entries == []
    assert d.warnings == []


def test_budget_used_is_activation_order_estimate_not_assembled_text() -> None:
    """budget_used 是冻结契约的激活序累计估算，不等于各模块文本的估算之和。

    「甲」在 before_char、「乙」在 after_char：门控按单一序列累计 "甲\n乙"
    （估 3），装配器则分成两个桶各自拼接，两模块估算之和为 2。
    """
    book = _book([
        _entry(entry_id=1, keys=["x"], content="甲", insertion_order=200,
               position="before_char"),
        _entry(entry_id=2, keys=["x"], content="乙", insertion_order=100,
               position="after_char"),
    ], token_budget=100)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    assert d.budget_used == token_estimate("甲\n乙") == 3
    module_sum = token_estimate("甲") + token_estimate("乙")
    assert module_sum == 2
    assert d.budget_used != module_sum
    assert d.budget_prunable_used == 3      # 分量跟随门控累计口径
    assert d.overflow_entries == []


def test_budget_used_follows_frozen_first_entry_rule_with_leading_empty() -> None:
    """冻结门控以「累计文本是否为空」判定序列首条。

    激活序首条正文为空时累计文本仍为空串（估 0），紧随其后的「甲」同样按首条
    处理、不加分隔符，因此本夹具下门控累计（估 1）恰好等于装配侧模块估算之和。
    门控累计与装配体积的一般差异（跨桶各自拼接）由
    ``test_budget_used_is_activation_order_estimate_not_assembled_text`` 覆盖。
    """
    # 空正文条目为 constant 且 insertion_order 更大，故它就是激活序首条
    # （累计序列首位）；空 keys 的非 constant 条目会被候选筛选跳过。
    book = _book([
        _entry(entry_id=1, keys=[], content="", insertion_order=200,
               constant=True),
        _entry(entry_id=2, keys=["x"], content="甲", insertion_order=100),
    ], token_budget=100)
    result = activate_world_book(book, _texts("x"))
    d = result.diagnostics
    injected_texts = [a.text for a in result.before_char]
    assert injected_texts == ["甲", ""]
    assembled_module_estimate = sum(token_estimate(t) for t in injected_texts if t)
    assert d.budget_used == token_estimate("甲") == 1
    assert assembled_module_estimate == token_estimate("甲") == 1
    assert d.budget_prunable_used == 1
    assert d.budget_limit_reached is False


def test_budget_accounting_holds_across_generated_books() -> None:
    """跨混合语料/空正文/常量组合核对预算记账（确定性生成，非实现复述）。

    断言的是可复算关系：budget_used 等于门控接受的累计拼接文本估算；两个
    分量是边际归因之和；受门控边际之和不超过限额；激活计数等于实际注入集
    大小；被排除条目不在注入集内。
    """
    rng = random.Random(20260910)
    contents = ["甲", "甲乙丙", "a", "b", "ab", "星", "", "晚安"]
    for _ in range(60):
        entries = [
            _entry(
                entry_id=i,
                keys=["x"] if rng.random() < 0.8 else [],
                content=rng.choice(contents),
                constant=rng.random() < 0.3,
                insertion_order=rng.choice([90, 100, 200, 300]),
                position=rng.choice(["before_char", "after_char", "atDepth"]),
            )
            for i in range(rng.randint(1, 7))
        ]
        budget = rng.choice([1, 2, 3, 5, 20, 100])
        result = activate_world_book(_book(entries, token_budget=budget), _texts("x"))
        d = result.diagnostics
        injected = list(result.before_char) + list(result.after_char)
        for group in result.depth_entries:
            injected += list(group.entries)
        injected_ids = {e.entry.entry_id for e in injected}
        assert d.activated_count == len(injected)
        assert d.budget_prunable_used <= d.budget_total
        for ref in d.overflow_entries:
            assert ref not in {str(i) for i in injected_ids}
        if d.budget_limit_reached:
            assert d.overflow_entries

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