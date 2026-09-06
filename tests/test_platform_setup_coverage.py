"""Coverage tests for custom_components/thz/platform_setup.py.

Exercises async_setup_write_platform():
- Filtering write registers by platform_type.
- Entity construction path (entity_type(...)).
- write_interval sourced from config_entry.data, with DEFAULT_UPDATE_INTERVAL
  fallback when absent.
- Empty register map -> async_add_entities called with an empty list.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.thz.platform_setup import async_setup_write_platform
from custom_components.thz.const import DEFAULT_UPDATE_INTERVAL


class FakeEntity:
    """Stand-in entity class capturing the kwargs it was built with."""

    def __init__(
        self,
        name,
        entry,
        device,
        device_id,
        scan_interval,
        entity_id_style="default",
        entity_visibility="default",
        entity_id_prefix=None,
    ):
        self.name = name
        self.entry = entry
        self.device = device
        self.device_id = device_id
        self.scan_interval = scan_interval
        self.entity_id_style = entity_id_style
        self.entity_visibility = entity_visibility
        self.entity_id_prefix = entity_id_prefix


def _make_hass_and_entry(registers, write_interval_data=None):
    device = MagicMock()
    write_manager = MagicMock()
    write_manager.get_all_registers.return_value = registers

    hass = MagicMock()

    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    config_entry.data = write_interval_data or {}
    config_entry.runtime_data = {
        "write_manager": write_manager,
        "device": device,
        "device_id": "dev1",
    }

    return hass, config_entry, device, write_manager


class TestAsyncSetupWritePlatformDefaultFactory:
    @pytest.mark.asyncio
    async def test_only_matching_platform_type_entities_created(self):
        registers = {
            "reg_number_1": {"type": "number", "command": "cmd1"},
            "reg_switch_1": {"type": "switch", "command": "cmd2"},
            "reg_number_2": {"type": "number", "command": "cmd3"},
        }
        hass, config_entry, device, _ = _make_hass_and_entry(registers)
        async_add_entities = MagicMock()

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, FakeEntity, "number"
        )

        assert async_add_entities.call_count == 1
        entities, update_before_add = async_add_entities.call_args.args
        assert update_before_add is True
        assert len(entities) == 2
        names = {e.name for e in entities}
        assert names == {"reg_number_1", "reg_number_2"}
        for e in entities:
            assert e.device is device
            assert e.device_id == "dev1"

    @pytest.mark.asyncio
    async def test_no_matching_entries_yields_empty_list(self):
        registers = {"reg_switch_1": {"type": "switch", "command": "cmd"}}
        hass, config_entry, _, _ = _make_hass_and_entry(registers)
        async_add_entities = MagicMock()

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, FakeEntity, "number"
        )

        entities, _ = async_add_entities.call_args.args
        assert entities == []

    @pytest.mark.asyncio
    async def test_empty_register_map(self):
        hass, config_entry, _, write_manager = _make_hass_and_entry({})
        async_add_entities = MagicMock()

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, FakeEntity, "select"
        )

        write_manager.get_all_registers.assert_called_once()
        entities, flag = async_add_entities.call_args.args
        assert entities == []
        assert flag is True

    @pytest.mark.asyncio
    async def test_write_interval_defaults_when_missing(self):
        registers = {"reg1": {"type": "time", "command": "cmd"}}
        hass, config_entry, _, _ = _make_hass_and_entry(
            registers, write_interval_data={}
        )
        async_add_entities = MagicMock()

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, FakeEntity, "time"
        )

        entities, _ = async_add_entities.call_args.args
        assert len(entities) == 1
        assert entities[0].scan_interval == DEFAULT_UPDATE_INTERVAL

    @pytest.mark.asyncio
    async def test_write_interval_taken_from_config_entry(self):
        registers = {"reg1": {"type": "time", "command": "cmd"}}
        hass, config_entry, _, _ = _make_hass_and_entry(
            registers, write_interval_data={"write_interval": 4242}
        )
        async_add_entities = MagicMock()

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, FakeEntity, "time"
        )

        entities, _ = async_add_entities.call_args.args
        assert entities[0].scan_interval == 4242
