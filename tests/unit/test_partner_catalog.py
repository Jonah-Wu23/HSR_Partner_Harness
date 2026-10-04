from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pair_harness.character_cards.models import (
    AvatarAsset,
    CharacterCard,
    HsrExtension,
    VoiceProfile,
)
from pair_harness.character_cards.repository import CharacterCardRepository
from pair_harness.config.pairs import PAIR_CATALOG_IDS, list_pair_configs
from pair_harness.partner_catalog import (
    PartnerBindingRepository,
    PartnerCatalogError,
    PartnerCatalogService,
)
from pair_harness.storage.sqlite_store import SQLiteStore

API_PAIR = "phainon_ancient_machine"


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "data" / "pair_harness.db")
    yield store
    store.close()


@pytest.fixture()
def cards(store: SQLiteStore) -> CharacterCardRepository:
    return CharacterCardRepository(store)


@pytest.fixture()
def bindings(store: SQLiteStore) -> PartnerBindingRepository:
    return PartnerBindingRepository(store)


@pytest.fixture()
def service(
    store: SQLiteStore,
    cards: CharacterCardRepository,
    bindings: PartnerBindingRepository,
) -> PartnerCatalogService:
    return PartnerCatalogService(
        store, cards, bindings, tuple(list_pair_configs())
    )


def _pairs_by_id() -> dict:
    return {pair.pair_id: pair for pair in list_pair_configs()}


def _saved_card(
    cards: CharacterCardRepository, name: str = "自定义角色", *, ready_voice: bool = False
) -> str:
    draft = cards.create_draft(name=name)
    card = CharacterCard(name=name)
    if ready_voice:
        card.hsr = HsrExtension(
            avatar_asset=AvatarAsset(asset_id="asset-1"),
            voice_profile=VoiceProfile(state="voice_ready", voice_id="voice-1"),
        )
    cards.update_card(draft.card_id, card)
    cards.publish_card(draft.card_id)
    return draft.card_id


def _card_option(service: PartnerCatalogService, card_id: str) -> dict | None:
    options, _ = service.list_options()
    found = [item for item in options if item["character_card_id"] == card_id]
    return found[0] if found else None


# ---------------------------------------------------------------- 目录


def test_fresh_catalog_has_three_builtin_options(service) -> None:
    options, version = service.list_options()
    pairs = _pairs_by_id()

    assert version == 0
    assert [item["pair_id"] for item in options] == list(PAIR_CATALOG_IDS)
    assert [item["binding_id"] for item in options] == [
        f"builtin:{pair_id}" for pair_id in PAIR_CATALOG_IDS
    ]
    for item in options:
        assert set(item) == {
            "binding_id",
            "pair_id",
            "character_card_id",
            "source",
            "character",
            "assistant",
            "theme",
        }
        assert item["source"] == "builtin"
        assert item["character_card_id"] is None
        pair = pairs[item["pair_id"]]
        assert item["character"] == {
            "id": pair.character.id,
            "name": pair.character.name,
            "voice_id": pair.character.voice_id,
            "avatar_ref": None,
            "avatar_version": None,
            "missing": False,
        }
        assert item["assistant"] == {
            "id": pair.assistant.id,
            "name": pair.assistant.name,
            "voice_id": pair.assistant.voice_id,
        }
        assert item["theme"] == pair.theme.model_dump(mode="json")


def test_create_binding_is_idempotent_and_card_option_appears(
    service, cards: CharacterCardRepository, bindings: PartnerBindingRepository
) -> None:
    card_id = _saved_card(cards)

    first = bindings.create_binding(card_id, API_PAIR)
    second = bindings.create_binding(card_id, API_PAIR)

    assert first == second
    assert first.source == "card"
    assert len(bindings.list_bindings()) == 4
    option = _card_option(service, card_id)
    assert option is not None
    assert option["binding_id"] == first.binding_id
    assert option["pair_id"] == API_PAIR
    assert option["character"] == {
        "id": card_id,
        "name": "自定义角色",
        "voice_id": "",
        "avatar_ref": None,
        "avatar_version": cards.get_card(card_id).updated_at,
        "missing": False,
    }


def test_builtin_binding_creation_is_stable_and_single_row(
    bindings: PartnerBindingRepository,
) -> None:
    binding = bindings.create_binding(None, "firefly_sam")

    assert binding.binding_id == "builtin:firefly_sam"
    assert bindings.create_binding(None, "firefly_sam") == binding
    count = bindings.connection.execute(
        "SELECT COUNT(*) FROM partner_bindings WHERE base_pair_id = 'firefly_sam'"
    ).fetchone()[0]
    assert count == 1


def test_card_option_reads_live_name_avatar_and_voice(
    service, cards: CharacterCardRepository, bindings: PartnerBindingRepository
) -> None:
    card_id = _saved_card(cards, name="初名", ready_voice=True)
    bindings.create_binding(card_id, API_PAIR)

    option = _card_option(service, card_id)
    assert option is not None
    assert option["character"]["voice_id"] == "voice-1"
    assert option["character"]["avatar_ref"] == "asset-1"
    assert option["character"]["avatar_version"] == cards.get_card(card_id).updated_at

    card = cards.get_card(card_id).card
    card.name = "改名后"
    cards.update_card(card_id, card)

    renamed = _card_option(service, card_id)
    assert renamed is not None
    assert renamed["character"]["name"] == "改名后"


def test_draft_archived_and_deleted_cards_leave_catalog(
    service, cards: CharacterCardRepository, bindings: PartnerBindingRepository
) -> None:
    draft = cards.create_draft(name="草稿角色")
    bindings.create_binding(draft.card_id, API_PAIR)
    assert _card_option(service, draft.card_id) is None

    cards.publish_card(draft.card_id)
    assert _card_option(service, draft.card_id) is not None

    cards.archive_card(draft.card_id)
    assert _card_option(service, draft.card_id) is None

    cards.unarchive_card(draft.card_id)
    assert _card_option(service, draft.card_id) is not None

    cards.delete_card(draft.card_id, confirm=True)
    assert _card_option(service, draft.card_id) is None


def test_disabled_binding_leaves_catalog_and_validate_raises(
    service, cards: CharacterCardRepository, bindings: PartnerBindingRepository
) -> None:
    card_id = _saved_card(cards)
    binding = bindings.create_binding(card_id, API_PAIR)

    bindings.set_enabled(binding.binding_id, False)
    assert _card_option(service, card_id) is None
    assert {item.binding_id for item in bindings.list_bindings(include_disabled=True)} >= {
        binding.binding_id
    }
    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(binding_id=binding.binding_id)
    assert failure.value.code == "binding_disabled"

    bindings.set_enabled(binding.binding_id, True)
    assert _card_option(service, card_id) is not None


def test_update_base_pair_switches_assistant(
    service, cards: CharacterCardRepository, bindings: PartnerBindingRepository
) -> None:
    card_id = _saved_card(cards)
    binding = bindings.create_binding(card_id, API_PAIR)

    bindings.update_base_pair(binding.binding_id, "firefly_sam")
    option = _card_option(service, card_id)

    assert option is not None
    assert option["pair_id"] == "firefly_sam"
    assert option["assistant"]["name"] == _pairs_by_id()["firefly_sam"].assistant.name


def test_update_base_pair_rejects_duplicate_scope(
    store: SQLiteStore, cards: CharacterCardRepository, bindings: PartnerBindingRepository
) -> None:
    card_id = _saved_card(cards)
    bindings.create_binding(card_id, API_PAIR)
    other = bindings.create_binding(card_id, "firefly_sam")

    with pytest.raises(sqlite3.IntegrityError):
        bindings.update_base_pair(other.binding_id, API_PAIR)
    store.connection.rollback()


def test_binding_outside_pair_catalog_fails_loudly(
    store: SQLiteStore, service, bindings: PartnerBindingRepository
) -> None:
    store.connection.execute(
        "INSERT INTO partner_bindings("
        "binding_id, character_card_id, base_pair_id, enabled, created_at, updated_at"
        ") VALUES ('bogus', NULL, 'no_such_pair', 1, '', '')"
    )

    with pytest.raises(PartnerCatalogError) as failure:
        service.list_options()
    assert failure.value.code == "pair_not_found"

    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(binding_id="bogus")
    assert failure.value.code == "pair_not_found"
    assert bindings.get_binding("bogus").base_pair_id == "no_such_pair"


def test_catalog_version_bumps_without_internal_commit(
    store: SQLiteStore, service, bindings: PartnerBindingRepository
) -> None:
    assert bindings.catalog_version() == 0
    assert bindings.bump_catalog_version() == 1
    assert bindings.bump_catalog_version() == 2
    assert service.list_options()[1] == 2

    store.connection.commit()
    assert bindings.catalog_version() == 2


def test_missing_binding_write_paths_raise_keyerror(
    bindings: PartnerBindingRepository,
) -> None:
    with pytest.raises(KeyError):
        bindings.get_binding("no-such-binding")
    with pytest.raises(KeyError):
        bindings.set_enabled("no-such-binding", False)
    with pytest.raises(KeyError):
        bindings.update_base_pair("no-such-binding", "firefly_sam")


# ---------------------------------------------------------------- 校验


def test_validate_for_create_resolves_all_three_paths(
    cards: CharacterCardRepository, bindings: PartnerBindingRepository, service
) -> None:
    card_id = _saved_card(cards)
    binding = bindings.create_binding(card_id, API_PAIR)

    by_binding = service.validate_for_create(binding_id=binding.binding_id)
    assert (by_binding.binding_id, by_binding.base_pair_id, by_binding.character_card_id) == (
        binding.binding_id,
        API_PAIR,
        card_id,
    )

    by_pair = service.validate_for_create(pair_id=API_PAIR, character_card_id=card_id)
    assert by_pair == by_binding

    builtin = service.validate_for_create(pair_id="firefly_sam")
    assert builtin.binding_id == "builtin:firefly_sam"
    assert builtin.base_pair_id == "firefly_sam"
    assert builtin.character_card_id is None


def test_validate_for_create_error_codes(
    cards: CharacterCardRepository, bindings: PartnerBindingRepository, service
) -> None:
    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create()
    assert failure.value.code == "invalid_request"

    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(binding_id="no-such-binding")
    assert failure.value.code == "binding_not_found"

    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(pair_id="no_such_pair")
    assert failure.value.code == "pair_not_found"

    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(pair_id=API_PAIR, character_card_id="card-gone")
    assert failure.value.code == "binding_not_found"

    draft = cards.create_draft(name="草稿")
    draft_binding = bindings.create_binding(draft.card_id, API_PAIR)
    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(binding_id=draft_binding.binding_id)
    assert failure.value.code == "card_invalid_state"

    cards.publish_card(draft.card_id)
    cards.archive_card(draft.card_id)
    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(binding_id=draft_binding.binding_id)
    assert failure.value.code == "card_invalid_state"

    deleted = _saved_card(cards, name="将删除")
    deleted_binding = bindings.create_binding(deleted, API_PAIR)
    cards.delete_card(deleted, confirm=True)
    with pytest.raises(PartnerCatalogError) as failure:
        service.validate_for_create(binding_id=deleted_binding.binding_id)
    assert failure.value.code == "card_not_found"


# ---------------------------------------------------------------- 身份解析


def test_resolve_character_identity(service, cards: CharacterCardRepository) -> None:
    pairs = _pairs_by_id()

    builtin = service.resolve_character_identity(API_PAIR, None)
    assert builtin == {
        "name": pairs[API_PAIR].character.name,
        "avatar_ref": None,
        "avatar_version": None,
        "missing": False,
        "source": "builtin",
    }

    card_id = _saved_card(cards, name="带头像", ready_voice=True)
    card = service.resolve_character_identity(API_PAIR, card_id)
    assert card == {
        "name": "带头像",
        "avatar_ref": "asset-1",
        "avatar_version": cards.get_card(card_id).updated_at,
        "missing": False,
        "source": "card",
    }

    missing = service.resolve_character_identity(API_PAIR, "card-gone")
    assert missing == {
        "name": "",
        "avatar_ref": None,
        "avatar_version": None,
        "missing": True,
        "source": "card",
    }

    with pytest.raises(PartnerCatalogError) as failure:
        service.resolve_character_identity("no_such_pair", None)
    assert failure.value.code == "pair_not_found"
