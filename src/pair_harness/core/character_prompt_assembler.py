"""角色提示词装配器（V0.3.5 纯模块，本期不接入对话链路）。

契约出处：

- 装配顺序：``docs/character-card/角色卡数据契约.md`` §9（运行时装配顺序，
  本阶段实现其子集：标准字段 + ``data.extensions.hsr`` 内容块）；
- 本阶段装配子集与降级语义：``docs/plans/V0.3.5-契约冻结.md`` §4.2。

装配职责只到「定序 + 小节标题 + 结构化呈现」：标准字段按作者原文装配，
``data.extensions.hsr`` 内容块渲染为确定性的「键: 值」行文本；不改写、
不摘要、不补全、不解析作者内容，不做任何语义猜测。

世界书（``character_book``，常驻/关键词条目）与 ``depth_prompt`` 的
运行时装配归 V0.3.7（契约 §9 第 3、4 步），本模块保留对接位置但不实现：
它们存在时不产生对应模块（边界由测试锁定）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pair_harness.character_cards.models import CharacterCard


@dataclass(frozen=True)
class AssemblyModule:
    """一个可诊断的提示词装配模块。

    - ``kind``：模块类型标识。标准字段为字段名（``description`` 等），
      HSR 内容块为 ``hsr.<块名>``（如 ``hsr.world_architecture``）；
    - ``source_field``：来源字段路径。标准字段为字段名本身；HSR 内容块
      按 JSON 路径 ``data.extensions.hsr.<块名>`` 标记；
    - ``title``：装配时使用的小节标题（中文）；
    - ``content``：该模块装配后的作者原文（不做任何改写）；
    - ``char_count``：内容字符数（诊断用）。
    """

    kind: str
    source_field: str
    title: str
    content: str
    char_count: int


@dataclass(frozen=True)
class AssembledPrompt:
    """装配结果：最终 system 文本 + 可诊断模块列表 + 首句原文。"""

    system_text: str
    modules: list[AssemblyModule]
    first_mes: str


# 标准字段装配规格：(字段名, kind, 小节标题)；元组顺序即装配顺序，
# 对应角色卡数据契约 §9 第 1、2 步与第 5 步（本阶段跳过第 3、4 步的世界书
# 与 depth_prompt，归 V0.3.7）。
_STANDARD_SPECS = (
    ("description", "description", "角色设定"),
    ("personality", "personality", "性格"),
    ("scenario", "scenario", "场景"),
    ("system_prompt", "system_prompt", "系统提示"),
    ("post_history_instructions", "post_history_instructions", "历史后指令"),
)

# HSR 高级扩展装配规格：(块名, kind, 小节标题)；元组顺序即契约 §9 第 6、7 步
# 的拼接顺序。``card.hsr`` 为 None 或块为空 dict 时不产生模块。
_HSR_SPECS = (
    ("world_architecture", "hsr.world_architecture", "世界架构"),
    ("character_architecture", "hsr.character_architecture", "角色架构"),
    ("narrative_rules", "hsr.narrative_rules", "叙事规则"),
    ("relationship_system", "hsr.relationship_system", "关系系统"),
    ("event_system", "hsr.event_system", "事件系统"),
)

# 框架引导模板（装配框架，不是人设合成）。
_FRAME_TEMPLATE = "你扮演 {name}。"


def assemble_character_prompt(card: CharacterCard) -> AssembledPrompt:
    """按契约 §9 / V0.3.5 §4.2 装配角色提示词（纯函数，无副作用）。

    - 每个非空模块渲染为 ``## <标题>\\n<内容>`` 小节，模块间空行分隔；
    - str 字段以 ``.strip()`` 后非空为装配条件；内容保留作者原文，
      不因装配而裁剪前后空白；
    - ``card.hsr`` 非 None 时逐块装配，块为空 dict 时跳过；内容块渲染为
      「键: 值」行文本：键按作者原始键名与顺序输出（不翻译、不排序、
      不删除任何键），嵌套 dict 递归渲染并缩进两个空格，list 逐项
      ``- `` 行；值一律原样，不改写、不摘要、不补全；
    - 文本最前永远有一行框架引导 ``你扮演 {name}。``；空卡（只有 name）
      ``system_text`` 即该行本身，``modules`` 为空列表；
    - 世界书与 depth_prompt 本阶段不装配（归 V0.3.7），不产生模块。
    """
    modules: list[AssemblyModule] = []
    for field_name, kind, title in _STANDARD_SPECS:
        value = getattr(card, field_name)
        if value.strip():
            modules.append(
                AssemblyModule(
                    kind=kind,
                    source_field=field_name,
                    title=title,
                    content=value,
                    char_count=len(value),
                )
            )
    hsr = card.hsr
    if hsr is not None:
        for block_name, kind, title in _HSR_SPECS:
            block = getattr(hsr, block_name)
            if block:
                content = _render_block_text(block)
                modules.append(
                    AssemblyModule(
                        kind=kind,
                        source_field=f"data.extensions.hsr.{block_name}",
                        title=title,
                        content=content,
                        char_count=len(content),
                    )
                )
    frame = _FRAME_TEMPLATE.format(name=card.name)
    sections = "\n\n".join(
        f"## {module.title}\n{module.content}" for module in modules
    )
    system_text = frame if not sections else f"{frame}\n\n{sections}"
    return AssembledPrompt(
        system_text=system_text,
        modules=modules,
        first_mes=card.first_mes,
    )


# ---------------------------------------------------------------- 结构块渲染


def _render_block_text(value: object) -> str:
    """把结构块渲染为确定性行文本（顶部块为 dict）。

    - dict：按作者原始键名与顺序输出 ``键: 值`` 行；值为 dict/list 时
      该行只输出键名，内容在下一层渲染；
    - 嵌套 dict/list 缩进两个空格；list 逐项 ``- `` 行；
    - 字符串与其余标量按原样呈现（空字符串不追加尾随空格）；
    - 不做翻译、不排序语义化、不删除任何键、不修改任何值。
    """
    return "\n".join(_block_lines(value, ""))


def _block_lines(value: object, indent: str) -> list[str]:
    """递归渲染一个结构值，返回带缩进行的行文本。"""
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}{key}:")
                lines.extend(_block_lines(item, indent + "  "))
            else:
                rendered = _scalar_text(item)
                if rendered:
                    lines.append(f"{indent}{key}: {rendered}")
                else:
                    lines.append(f"{indent}{key}:")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                nested = _block_lines(item, indent + "  ")
                if nested:
                    # 条目首行内联到 ``- `` 后，其余行保持该项的续行缩进。
                    lines.append(f"{indent}- {nested[0][len(indent) + 2:]}")
                    lines.extend(nested[1:])
                else:
                    lines.append(f"{indent}-")
            elif isinstance(item, list):
                lines.append(f"{indent}-")
                lines.extend(_block_lines(item, indent + "  "))
            else:
                rendered = _scalar_text(item)
                if rendered:
                    lines.append(f"{indent}- {rendered}")
                else:
                    lines.append(f"{indent}-")
        return lines
    return [f"{indent}{_scalar_text(value)}"]


def _scalar_text(value: object) -> str:
    """标量行文本：字符串原样输出，其余类型按 Python 确定性转字符串。"""
    if isinstance(value, str):
        return value
    return str(value)
