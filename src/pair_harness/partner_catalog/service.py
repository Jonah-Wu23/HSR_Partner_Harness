# 搭档目录服务：把持久化绑定、角色卡与内置 YAML 搭档配置汇成一张可选搭档目录。
# list_options 与 resolve_character_identity 只读；validate_for_create 只校验，
# 都不写库。绑定创建与目录版本递增发生在 application 层，由调用方统一提交。

from __future__ import annotations

from dataclasses import dataclass

from pair_harness.character_cards.repository import CharacterCardRepository
from pair_harness.character_cards.states import CharacterVoiceState
from pair_harness.config.pairs import PairConfig
from pair_harness.storage.sqlite_store import SQLiteStore

from .repository import PartnerBinding, PartnerBindingRepository

# 进入目录与允许新建会话的角色卡状态；draft 不出现。
ELIGIBLE_CARD_STATES = frozenset({"saved", "imported"})


class PartnerCatalogError(RuntimeError):
    """搭档目录校验失败。

    ``code`` 是稳定的失败原因，取值：binding_not_found、binding_disabled、
    card_not_found、card_invalid_state、pair_not_found，以及参数缺失的
    invalid_request。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedBinding:
    """新建会话时确定下来的搭档身份。"""

    binding_id: str
    base_pair_id: str
    character_card_id: str | None


def _assistant_payload(pair: PairConfig) -> dict:
    return {
        "id": pair.assistant.id,
        "name": pair.assistant.name,
        "voice_id": pair.assistant.voice_id,
    }


class PartnerCatalogService:
    """可选搭档目录与身份解析的单一入口。

    构造参数 ``pair_catalog`` 是 ``config.pairs.list_pair_configs()`` 的结果；
    绑定里出现目录之外的 base_pair_id 时直接抛 PartnerCatalogError，不静默跳过。
    """

    def __init__(
        self,
        store: SQLiteStore,
        card_repository: CharacterCardRepository,
        binding_repository: PartnerBindingRepository,
        pair_catalog: tuple[PairConfig, ...],
    ) -> None:
        self.store = store
        self.card_repository = card_repository
        self.binding_repository = binding_repository
        self.pair_catalog = tuple(pair_catalog)
        self._pairs_by_id = {pair.pair_id: pair for pair in self.pair_catalog}

    # ---------------------------------------------------------------- 目录

    def list_options(self) -> tuple[list[dict], int]:
        """返回（目录项列表, 目录版本）。

        内置三项在前（按 pair_catalog 顺序），卡绑定按创建顺序随后。卡不存在、
        已归档、state 不是 saved/imported 或绑定已停用的条目不出现在目录里。
        """
        items: list[dict] = []
        bindings = self.binding_repository.list_bindings()
        builtin = [item for item in bindings if item.character_card_id is None]
        builtin.sort(key=lambda item: self._pair_index(item.base_pair_id))
        for binding in builtin:
            items.append(self._builtin_option(binding))
        for binding in bindings:
            if binding.character_card_id is None:
                continue
            option = self._card_option(binding)
            if option is not None:
                items.append(option)
        return items, self.binding_repository.catalog_version()

    def _builtin_option(self, binding: PartnerBinding) -> dict:
        pair = self._require_pair(binding.base_pair_id)
        return {
            "binding_id": binding.binding_id,
            "pair_id": binding.base_pair_id,
            "character_card_id": None,
            "source": "builtin",
            "character": {
                "id": pair.character.id,
                "name": pair.character.name,
                "voice_id": pair.character.voice_id,
                "avatar_ref": None,
                "avatar_version": None,
                "missing": False,
            },
            "assistant": _assistant_payload(pair),
            "theme": pair.theme.model_dump(mode="json"),
        }

    def _card_option(self, binding: PartnerBinding) -> dict | None:
        """卡绑定的目录项；卡不可用时返回 None，由调用方跳过该条目。"""
        try:
            record = self.card_repository.get_card(binding.character_card_id)
        except KeyError:
            return None
        if record.state not in ELIGIBLE_CARD_STATES:
            return None
        if self.card_repository.is_archived(record.card_id):
            return None
        pair = self._require_pair(binding.base_pair_id)
        hsr = record.card.hsr
        voice_id = ""
        if (
            hsr is not None
            and hsr.voice_profile is not None
            and hsr.voice_profile.state == CharacterVoiceState.READY.value
        ):
            voice_id = hsr.voice_profile.voice_id
        avatar_ref = None
        if hsr is not None and hsr.avatar_asset is not None and hsr.avatar_asset.asset_id:
            avatar_ref = hsr.avatar_asset.asset_id
        return {
            "binding_id": binding.binding_id,
            "pair_id": binding.base_pair_id,
            "character_card_id": record.card_id,
            "source": "card",
            "character": {
                "id": record.card_id,
                "name": record.card.name,
                "voice_id": voice_id,
                "avatar_ref": avatar_ref,
                "avatar_version": record.updated_at,
                "missing": False,
            },
            "assistant": _assistant_payload(pair),
            "theme": pair.theme.model_dump(mode="json"),
        }

    # ---------------------------------------------------------------- 身份解析

    def resolve_character_identity(
        self, pair_id: str, character_card_id: str | None
    ) -> dict:
        """会话展示用的统一身份解析。

        ``character_card_id`` 为 None 时按 ``pair_id`` 的内置角色解析；卡不存在
        返回 missing=True 与空名字，由调用方决定提示文案。
        """
        if character_card_id is None:
            pair = self._require_pair(pair_id)
            return {
                "name": pair.character.name,
                "avatar_ref": None,
                "avatar_version": None,
                "missing": False,
                "source": "builtin",
            }
        try:
            record = self.card_repository.get_card(character_card_id)
        except KeyError:
            return {
                "name": "",
                "avatar_ref": None,
                "avatar_version": None,
                "missing": True,
                "source": "card",
            }
        hsr = record.card.hsr
        avatar_ref = None
        if hsr is not None and hsr.avatar_asset is not None and hsr.avatar_asset.asset_id:
            avatar_ref = hsr.avatar_asset.asset_id
        return {
            "name": record.card.name,
            "avatar_ref": avatar_ref,
            "avatar_version": record.updated_at,
            "missing": False,
            "source": "card",
        }

    # ---------------------------------------------------------------- 新建校验

    def validate_for_create(
        self,
        binding_id: str | None = None,
        pair_id: str | None = None,
        character_card_id: str | None = None,
    ) -> ResolvedBinding:
        """新建会话前校验并确定搭档身份。

        优先级：binding_id > (pair_id + character_card_id) > pair_id（内置角色）。
        校验绑定存在且启用、角色卡可用（saved/imported 且未归档）、base_pair_id
        在目录中；失败抛 PartnerCatalogError。三参数全为空是调用方错误，
        抛 code=invalid_request。
        """
        if binding_id is None and pair_id is None:
            raise PartnerCatalogError(
                "invalid_request", "新建会话必须给出 binding_id 或 pair_id"
            )
        if binding_id is not None:
            binding = self._require_binding(binding_id)
        else:
            self._require_pair(pair_id)
            binding = self._require_binding_for_pair(pair_id, character_card_id)
        self._require_pair(binding.base_pair_id)
        if not binding.enabled:
            raise PartnerCatalogError(
                "binding_disabled", f"搭档绑定已停用：{binding.binding_id}"
            )
        if binding.character_card_id is not None:
            self._require_eligible_card(binding.character_card_id)
        return ResolvedBinding(
            binding_id=binding.binding_id,
            base_pair_id=binding.base_pair_id,
            character_card_id=binding.character_card_id,
        )

    # ---------------------------------------------------------------- 内部

    def _require_binding(self, binding_id: str) -> PartnerBinding:
        try:
            return self.binding_repository.get_binding(binding_id)
        except KeyError as exc:
            raise PartnerCatalogError(
                "binding_not_found", f"搭档绑定不存在：{binding_id}"
            ) from exc

    def _require_binding_for_pair(
        self, pair_id: str, character_card_id: str | None
    ) -> PartnerBinding:
        """按 (pair_id, character_card_id) 找绑定；character_card_id 为 None 找内置绑定。"""
        binding = self.binding_repository.find_binding(character_card_id, pair_id)
        if binding is None:
            raise PartnerCatalogError(
                "binding_not_found",
                f"角色卡与搭档没有绑定：{character_card_id!r} / {pair_id}",
            )
        return binding

    def _require_pair(self, pair_id: str) -> PairConfig:
        pair = self._pairs_by_id.get(pair_id)
        if pair is None:
            raise PartnerCatalogError("pair_not_found", f"搭档配置不存在：{pair_id}")
        return pair

    def _pair_index(self, pair_id: str) -> int:
        for index, pair in enumerate(self.pair_catalog):
            if pair.pair_id == pair_id:
                return index
        raise PartnerCatalogError("pair_not_found", f"搭档配置不存在：{pair_id}")

    def _require_eligible_card(self, card_id: str) -> None:
        try:
            record = self.card_repository.get_card(card_id)
        except KeyError as exc:
            raise PartnerCatalogError("card_not_found", f"角色卡不存在：{card_id}") from exc
        if record.state not in ELIGIBLE_CARD_STATES or self.card_repository.is_archived(
            card_id
        ):
            raise PartnerCatalogError(
                "card_invalid_state", f"角色卡当前不可用于新建会话：{card_id}"
            )
