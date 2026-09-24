"""Tests for base_entity.py (THZBaseEntity).

Covers __init__ branches, _generate_unique_id, where the value comes from
(poller subscription or block coordinator, see async_added_to_hass),
availability, async_update, extra_state_attributes and device_info.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.thz.base_entity as base_entity_mod
from custom_components.thz.base_entity import THZBaseEntity, THZParameterEntity
from custom_components.thz.const import DOMAIN
from custom_components.thz.exceptions import THZConnectionError
from tests.helpers import write_param


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

    def test_not_listening_initially(self):
        entity = _make_entity()
        assert entity._unsub_poll is None

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


KEY = ("0A0100", 4, 2)


class _PolledEntity(THZBaseEntity):
    """A base entity polling KEY that records the values it applies."""

    def __init__(self):
        super().__init__(
            name="pTestEntity", command="0A0100", device=MagicMock(), device_id="d"
        )
        self.applied = []
        self.hass = MagicMock()
        self.async_write_ha_state = MagicMock()

    def _poll_key(self):
        return KEY

    def _apply_value(self, value_bytes):
        self.applied.append(value_bytes)


@pytest.fixture(autouse=True)
def _entity_lifecycle(monkeypatch):
    """The mocked Entity base class has no lifecycle methods; add no-ops."""
    for method in ("async_added_to_hass", "async_will_remove_from_hass"):
        monkeypatch.setattr(base_entity_mod.Entity, method, AsyncMock(), raising=False)


def _poller(data=None):
    poller = MagicMock()
    poller.data = data if data is not None else {}
    return poller


class TestPollerSubscription:
    """Entities with a _poll_key subscribe it at the poller."""

    @pytest.mark.asyncio
    async def test_subscribes_and_unsubscribes(self):
        entity = _PolledEntity()
        entity._poller = poller = _poller()

        await entity.async_added_to_hass()
        poller.async_subscribe.assert_called_once_with(KEY, entity._handle_poll)
        assert entity.applied == []

        await entity.async_will_remove_from_hass()
        poller.async_subscribe.return_value.assert_called_once_with()
        assert entity._unsub_poll is None

    @pytest.mark.asyncio
    async def test_takes_a_known_result_right_away(self):
        entity = _PolledEntity()
        entity._poller = _poller({KEY: b"\x00\x10"})

        await entity.async_added_to_hass()

        assert entity.applied == [b"\x00\x10"]
        entity.async_write_ha_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_without_poller_or_key_nothing_is_subscribed(self):
        entity = _make_entity()
        entity._poller = poller = _poller()
        await entity.async_added_to_hass()
        poller.async_subscribe.assert_not_called()

        polled = _PolledEntity()
        await polled.async_added_to_hass()  # no poller set
        assert polled._unsub_poll is None

    @pytest.mark.asyncio
    async def test_remove_without_subscription(self):
        entity = _make_entity()
        await entity.async_will_remove_from_hass()
        assert entity._unsub_poll is None


class TestPollResults:
    """_handle_poll: bytes are applied, None is unavailable, b"" keeps."""

    def test_value_is_applied_and_written(self):
        entity = _PolledEntity()
        entity._handle_poll(b"\x01")
        assert entity.applied == [b"\x01"]
        assert entity.available is True
        entity.async_write_ha_state.assert_called_once()

    def test_failed_read_makes_unavailable_until_the_next_value(self):
        entity = _PolledEntity()
        entity._handle_poll(None)
        entity._handle_poll(None)
        assert entity.available is False
        assert entity.applied == []

        entity._handle_poll(b"\x02")
        assert entity.available is True
        assert entity.applied == [b"\x02"]

    def test_empty_answer_keeps_the_value(self):
        entity = _PolledEntity()
        entity._handle_poll(b"")
        assert entity.applied == []
        assert entity.available is True

    @pytest.mark.asyncio
    async def test_write_drops_the_polled_result(self):
        entity = _PolledEntity()
        entity._poller = poller = _poller()
        await entity._async_after_write()
        poller.async_invalidate.assert_called_once_with(KEY)

    @pytest.mark.asyncio
    async def test_write_without_poller_is_a_noop(self):
        await _make_entity()._async_after_write()


class TestAsyncUpdate:
    """async_update reads _poll_key from the device directly."""

    @pytest.mark.asyncio
    async def test_reads_the_poll_key(self):
        entity = _PolledEntity()
        entity._device.async_execute = AsyncMock(return_value=b"\x00\x05")

        await entity.async_update()

        entity._device.async_execute.assert_awaited_once_with(
            entity.hass, entity._device.read_value, bytes.fromhex("0A0100"), "get", 4, 2
        )
        assert entity.applied == [b"\x00\x05"]

    @pytest.mark.asyncio
    async def test_device_error_makes_unavailable(self):
        entity = _PolledEntity()
        entity._device.async_execute = AsyncMock(side_effect=THZConnectionError("x"))

        await entity.async_update()

        assert entity.available is False
        assert entity.applied == []

    @pytest.mark.asyncio
    async def test_empty_answer_keeps_the_value(self):
        entity = _PolledEntity()
        entity._device.async_execute = AsyncMock(return_value=b"")
        await entity.async_update()
        assert entity.applied == []

    @pytest.mark.asyncio
    async def test_entity_without_key_reads_nothing(self):
        entity = _make_entity()
        entity._device.async_execute = AsyncMock()
        await entity.async_update()
        entity._device.async_execute.assert_not_called()


def _flag_param():
    """A 2.x flag at bit 3 of byte 6 of block 0B."""
    return write_param(
        name="progFlag",
        command="0B",
        type="switch",
        write_mode="block",
        offset=6,
        length=1,
        bit=3,
        signed=False,
    )


class _ParamEntity(THZParameterEntity):
    def __init__(self, entry):
        super().__init__(
            name=entry.name, command=entry.command, device=MagicMock(), device_id="d"
        )
        self._entry = entry
        self.applied = []
        self.hass = MagicMock()
        self.async_write_ha_state = MagicMock()

    def _apply_value(self, value_bytes):
        self.applied.append(value_bytes)


class TestParameterEntity:
    """THZParameterEntity takes its value from its block or the poller."""

    def test_poll_key_and_bit(self):
        entity = _ParamEntity(_flag_param())
        assert entity._poll_key() == ("0B", 6, 1)
        assert entity._value_from_poll(b"\x08") == b"\x01"
        assert entity._block_coordinator() is None

    @pytest.mark.asyncio
    async def test_block_parameter_listens_to_its_block(self):
        entity = _ParamEntity(_flag_param())
        coordinator = MagicMock(last_update_success=True)
        coordinator.data = bytes(6) + b"\x08"
        coordinator.async_request_refresh = AsyncMock()
        entity._coordinators = {"pxx0B": coordinator}
        entity._poller = poller = _poller()

        await entity.async_added_to_hass()

        poller.async_subscribe.assert_not_called()
        coordinator.async_add_listener.assert_called_once_with(
            entity._handle_block_update
        )
        assert entity.applied == [b"\x01"]

        coordinator.data = bytes(7)
        entity._handle_block_update()
        assert entity.applied == [b"\x01", b"\x00"]
        entity.async_write_ha_state.assert_called_once()

        await entity._async_after_write()
        coordinator.async_request_refresh.assert_awaited_once()
        poller.async_invalidate.assert_not_called()

    def test_failed_block_read_makes_unavailable(self):
        entity = _ParamEntity(_flag_param())
        coordinator = MagicMock(last_update_success=False, data=None)
        entity._coordinators = {"pxx0B": coordinator}

        entity._handle_block_update()

        assert entity.available is False
        assert entity.applied == []

    @pytest.mark.parametrize("data", [None, b"", b"\x00\x00"])
    def test_missing_or_short_block_keeps_the_value(self, data):
        entity = _ParamEntity(_flag_param())
        coordinator = MagicMock(last_update_success=True, data=data)
        entity._coordinators = {"pxx0B": coordinator}

        entity._handle_block_update()

        assert entity.available is True
        assert entity.applied == []

    def test_block_listener_after_the_block_is_gone(self):
        entity = _ParamEntity(_flag_param())
        entity._handle_block_update()
        entity.async_write_ha_state.assert_called_once()
