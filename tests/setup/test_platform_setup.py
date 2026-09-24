"""Tests for custom_components/thz/platform_setup.py.

Exercises async_setup_write_platform():
- Filtering write registers by platform_type.
- Entity construction path (entity_type(...)).
- The entities get the block coordinators and the poller, and are added
  without a read before adding (the poller reads them).
- Empty register map -> async_add_entities called with an empty list.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.thz.platform_setup import async_setup_write_platform
from tests.helpers import FakeWriteManager, make_runtime_data


class FakeEntity:
    """Stand-in entity class capturing the kwargs it was built with."""

    def __init__(
        self,
        name,
        entry,
        device,
        device_id,
        entity_id_style="default",
        entity_visibility="default",
        entity_id_prefix=None,
    ):
        self.name = name
        self.entry = entry
        self.device = device
        self.device_id = device_id
        self.entity_id_style = entity_id_style
        self.entity_visibility = entity_visibility
        self.entity_id_prefix = entity_id_prefix


def _make_hass_and_entry(registers, write_interval_data=None):
    device = MagicMock()
    write_manager = FakeWriteManager(registers)
    hass = MagicMock()

    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    config_entry.data = write_interval_data or {}
    config_entry.runtime_data = make_runtime_data(
        **{
            "write_manager": write_manager,
            "device": device,
            "device_id": "dev1",
        }
    )

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
        (entities,) = async_add_entities.call_args.args
        assert len(entities) == 2
        names = {e.name for e in entities}
        assert names == {"reg_number_1", "reg_number_2"}
        for e in entities:
            assert e.device is device
            assert e.device_id == "dev1"
            assert e._poller is config_entry.runtime_data.poller
            assert e._coordinators is config_entry.runtime_data.coordinators

    @pytest.mark.asyncio
    async def test_no_matching_entries_yields_empty_list(self):
        registers = {"reg_switch_1": {"type": "switch", "command": "cmd"}}
        hass, config_entry, _, _ = _make_hass_and_entry(registers)
        async_add_entities = MagicMock()

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, FakeEntity, "number"
        )

        (entities,) = async_add_entities.call_args.args
        assert entities == []

    @pytest.mark.asyncio
    async def test_empty_register_map(self):
        hass, config_entry, _, _ = _make_hass_and_entry({})
        async_add_entities = MagicMock()

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, FakeEntity, "select"
        )

        (entities,) = async_add_entities.call_args.args
        assert entities == []
