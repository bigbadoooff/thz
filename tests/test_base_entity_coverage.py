"""Coverage tests for base_entity.py (THZBaseEntity).

Covers __init__ branches, _generate_unique_id, async_added_to_hass /
async_will_remove_from_hass (periodic update timer subscribe/unsubscribe),
_async_scheduled_update, extra_state_attributes and device_info.
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.thz.base_entity as base_entity_mod
from custom_components.thz.base_entity import THZBaseEntity
from custom_components.thz.const import DOMAIN


def _make_device():
    device = MagicMock()
    return device


def _make_entity(name="pTestEntity", command="0A0100", **kwargs):
    return THZBaseEntity(
        name=name,
        command=command,
        device=_make_device(),
        device_id="dev1",
        **kwargs,
    )


class TestInit:
    """Tests for THZBaseEntity.__init__."""

    def test_default_icon(self):
        entity = _make_entity()
        assert entity._attr_icon == "mdi:eye"

    def test_custom_icon(self):
        entity = _make_entity(icon="mdi:custom")
        assert entity._attr_icon == "mdi:custom"

    def test_translation_key_sets_has_entity_name_and_no_attr_name(self):
        entity = _make_entity(translation_key="op_mode")
        assert entity._attr_translation_key == "op_mode"
        assert entity._attr_has_entity_name is True
        assert not hasattr(entity, "_attr_name")

    def test_no_translation_key_sets_attr_name(self):
        entity = _make_entity(name="pTestEntity")
        assert entity._attr_name == "pTestEntity"
        assert not hasattr(entity, "_attr_translation_key")

    def test_explicit_unique_id_used(self):
        entity = _make_entity(unique_id="my_custom_id")
        assert entity._attr_unique_id == "my_custom_id"

    def test_auto_generated_unique_id(self):
        entity = _make_entity(name="pTestEntity", command="0A0100")
        assert entity._attr_unique_id == "thz_set_0a0100_ptestentity"

    def test_default_scan_interval(self):
        entity = _make_entity()
        assert entity._update_interval == timedelta(seconds=600)

    def test_custom_scan_interval(self):
        entity = _make_entity(scan_interval=120)
        assert entity._update_interval == timedelta(seconds=120)

    def test_unsub_update_initially_none(self):
        entity = _make_entity()
        assert entity._unsub_update is None

    def test_entity_registry_enabled_default_hidden_for_program_names(self):
        entity = _make_entity(name="programHC1_Mo_0")
        assert entity._attr_entity_registry_enabled_default is False

    def test_entity_registry_enabled_default_true_for_normal_names(self):
        entity = _make_entity(name="pOpMode")
        assert entity._attr_entity_registry_enabled_default is True


class TestEntityCategory:
    """Tests for THZBaseEntity's EntityCategory tagging."""

    def test_advanced_entity_gets_config_category(self):
        from homeassistant.const import EntityCategory

        entity = _make_entity(name="p13GradientHC1")
        assert entity._attr_entity_category == EntityCategory.CONFIG

    def test_normal_entity_has_no_entity_category(self):
        entity = _make_entity(name="pOpMode")
        assert getattr(entity, "_attr_entity_category", None) is None


class TestAvailable:
    """Tests for THZBaseEntity.available."""

    def test_available_true_by_default(self):
        entity = _make_entity()
        assert entity.available is True

    def test_available_reflects_attr_available(self):
        entity = _make_entity()
        entity._attr_available = False
        assert entity.available is False


class TestGenerateUniqueId:
    """Tests for THZBaseEntity._generate_unique_id."""

    def test_generate_unique_id_lowercases_and_replaces_spaces(self):
        entity = _make_entity()
        result = entity._generate_unique_id("0A0100", "My Test Name")
        assert result == "thz_set_0a0100_my_test_name"


class TestExtraStateAttributes:
    """Tests for THZBaseEntity.extra_state_attributes."""

    def test_extra_state_attributes_contains_command(self):
        entity = _make_entity(command="0A0100")
        assert entity.extra_state_attributes == {"register_command": "0A0100"}


class TestDeviceInfo:
    """Tests for THZBaseEntity.device_info."""

    def test_device_info_contains_identifiers(self):
        entity = _make_entity()
        info = entity.device_info
        assert (DOMAIN, "dev1") in info["identifiers"]


class TestAsyncAddedToHass:
    """Tests for THZBaseEntity.async_added_to_hass."""

    @pytest.mark.asyncio
    async def test_schedules_periodic_update(self, monkeypatch):
        entity = _make_entity(scan_interval=300)
        entity.hass = MagicMock()

        # The mocked Entity base class has no async_added_to_hass method;
        # patch it in for the duration of this test.
        monkeypatch.setattr(
            base_entity_mod.Entity, "async_added_to_hass", AsyncMock(), raising=False
        )

        unsub_sentinel = MagicMock()
        monkeypatch.setattr(
            base_entity_mod,
            "async_track_time_interval",
            MagicMock(return_value=unsub_sentinel),
        )

        await entity.async_added_to_hass()

        assert entity._unsub_update is unsub_sentinel
        base_entity_mod.async_track_time_interval.assert_called_once_with(
            entity.hass, entity._async_scheduled_update, entity._update_interval
        )


class TestAsyncScheduledUpdate:
    """Tests for THZBaseEntity._async_scheduled_update."""

    @pytest.mark.asyncio
    async def test_triggers_forced_refresh(self):
        entity = _make_entity()
        entity.async_update_ha_state = AsyncMock()

        await entity._async_scheduled_update(datetime.now())

        entity.async_update_ha_state.assert_awaited_once_with(force_refresh=True)


class TestAsyncWillRemoveFromHass:
    """Tests for THZBaseEntity.async_will_remove_from_hass."""

    @pytest.mark.asyncio
    async def test_cancels_active_timer(self, monkeypatch):
        entity = _make_entity()
        unsub = MagicMock()
        entity._unsub_update = unsub

        monkeypatch.setattr(
            base_entity_mod.Entity,
            "async_will_remove_from_hass",
            AsyncMock(),
            raising=False,
        )

        await entity.async_will_remove_from_hass()

        unsub.assert_called_once()
        assert entity._unsub_update is None

    @pytest.mark.asyncio
    async def test_noop_when_no_active_timer(self, monkeypatch):
        entity = _make_entity()
        entity._unsub_update = None

        super_mock = AsyncMock()
        monkeypatch.setattr(
            base_entity_mod.Entity,
            "async_will_remove_from_hass",
            super_mock,
            raising=False,
        )

        await entity.async_will_remove_from_hass()

        assert entity._unsub_update is None
        super_mock.assert_awaited_once()
