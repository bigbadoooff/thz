"""Coverage tests for async_setup_entry, async_unload_entry, and related helpers.

DataUpdateCoordinator is mocked in conftest.py as the bare `MagicMock` class,
which cannot be spec'd against another Mock (our `hass` fixture) — so these
tests patch `custom_components.thz.DataUpdateCoordinator` with a factory that
returns a fully-controllable fake coordinator instance.
"""
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.thz as thz_module
from custom_components.thz.const import DOMAIN


def _fake_coordinator(data=b"\x00" * 20):
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _fake_device(firmware="539", blocks=None):
    device = MagicMock()
    device.async_initialize = AsyncMock()
    device.firmware_version = firmware
    device.available_reading_blocks = blocks if blocks is not None else ["pxxFB"]
    device.write_register_map_manager = MagicMock()
    device.register_map_manager = MagicMock()
    device.register_map_manager.get_paired_blocks.return_value = {}
    device.unique_id = "thz-unique-1"
    device.close = MagicMock()
    return device


def _default_dev_reg():
    return MagicMock(
        async_get_or_create=MagicMock(return_value=MagicMock(id="dev1"))
    )


@contextmanager
def _patched_setup(device=None, coordinator_factory=None, dev_reg=None):
    """Patch the collaborators async_setup_entry needs, DRYing up the tests below.

    Always patches device_registry.async_get, entity_registry.async_get, and
    entity_registry.async_entries_for_config_entry with sensible defaults.
    THZDevice and DataUpdateCoordinator are only patched when a device /
    coordinator_factory is supplied. Yields the THZDevice patch object (so
    callers can assert on its call args) or None if device wasn't given.
    """
    with ExitStack() as stack:
        thz_device_mock = None
        if device is not None:
            thz_device_mock = stack.enter_context(
                patch.object(thz_module, "THZDevice", return_value=device)
            )
        if coordinator_factory is not None:
            stack.enter_context(
                patch.object(
                    thz_module, "DataUpdateCoordinator",
                    side_effect=coordinator_factory,
                )
            )
        stack.enter_context(
            patch.object(
                thz_module.dr, "async_get", return_value=dev_reg or _default_dev_reg()
            )
        )
        stack.enter_context(
            patch.object(
                thz_module.er, "async_get", return_value=MagicMock(entities={})
            )
        )
        stack.enter_context(
            patch.object(
                thz_module.er, "async_entries_for_config_entry", return_value=[]
            )
        )
        yield thz_device_mock


def _mock_hass():
    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries = MagicMock(return_value=[])
    hass.async_add_executor_job = AsyncMock()
    return hass


def _mock_config_entry(entry_id="entry1", **data_overrides):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.as_dict = MagicMock(return_value={})
    data = {
        "connection_type": "usb",
        "device": "/dev/ttyUSB0",
    }
    data.update(data_overrides)
    entry.data = data
    return entry


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_usb_setup_success(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        device = _fake_device()

        with _patched_setup(
            device=device, coordinator_factory=lambda *a, **kw: _fake_coordinator()
        ) as mock_cls:
            result = await thz_module.async_setup_entry(hass, entry)

        assert result is True
        mock_cls.assert_called_once_with(connection="usb", port="/dev/ttyUSB0")
        assert entry.entry_id in hass.data[DOMAIN]
        stored = hass.data[DOMAIN][entry.entry_id]
        assert stored["device"] is device
        assert "pxxFB" in stored["coordinators"]
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ip_setup_success(self):
        hass = _mock_hass()
        entry = _mock_config_entry(
            connection_type="ip", host="10.0.0.5", port=2323, device=None
        )
        device = _fake_device()

        with _patched_setup(
            device=device, coordinator_factory=lambda *a, **kw: _fake_coordinator()
        ) as mock_cls:
            result = await thz_module.async_setup_entry(hass, entry)

        assert result is True
        mock_cls.assert_called_once_with(
            connection="ip", host="10.0.0.5", tcp_port=2323
        )

    @pytest.mark.asyncio
    async def test_invalid_connection_type_raises(self):
        hass = _mock_hass()
        entry = _mock_config_entry(connection_type="bluetooth")

        with _patched_setup():
            with pytest.raises(ValueError, match="Invalid connection type"):
                await thz_module.async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_device_init_oserror_raises_config_entry_not_ready(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        device = _fake_device()
        device.async_initialize = AsyncMock(side_effect=OSError("no port"))

        with _patched_setup(device=device):
            with pytest.raises(thz_module.ConfigEntryNotReady):
                await thz_module.async_setup_entry(hass, entry)

    @pytest.mark.asyncio
    async def test_no_refresh_intervals_uses_defaults_from_available_blocks(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        device = _fake_device(blocks=["pxxFB", "pxxF2"])

        with _patched_setup(
            device=device, coordinator_factory=lambda *a, **kw: _fake_coordinator()
        ):
            await thz_module.async_setup_entry(hass, entry)

        stored = hass.data[DOMAIN][entry.entry_id]
        assert set(stored["coordinators"]) == {"pxxFB", "pxxF2"}

    @pytest.mark.asyncio
    async def test_no_refresh_intervals_and_no_available_blocks_creates_none(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        device = _fake_device(blocks=[])

        with _patched_setup(device=device):
            await thz_module.async_setup_entry(hass, entry)

        stored = hass.data[DOMAIN][entry.entry_id]
        assert stored["coordinators"] == {}

    @pytest.mark.asyncio
    async def test_block_config_entry_not_ready_marks_unsupported(self):
        hass = _mock_hass()
        entry = _mock_config_entry(refresh_intervals={"pxxFB": 300})
        device = _fake_device()

        failing_coordinator = _fake_coordinator()
        failing_coordinator.async_config_entry_first_refresh = AsyncMock(
            side_effect=thz_module.ConfigEntryNotReady("block failed")
        )

        with _patched_setup(
            device=device, coordinator_factory=lambda *a, **kw: failing_coordinator
        ):
            await thz_module.async_setup_entry(hass, entry)

        stored = hass.data[DOMAIN][entry.entry_id]
        assert "pxxFB" in stored["unsupported_blocks"]
        assert "pxxFB" not in stored["coordinators"]

    @pytest.mark.asyncio
    async def test_block_with_none_data_marked_unsupported(self):
        hass = _mock_hass()
        entry = _mock_config_entry(refresh_intervals={"pxxFB": 300})
        device = _fake_device()
        coordinator = _fake_coordinator(data=None)

        with _patched_setup(
            device=device, coordinator_factory=lambda *a, **kw: coordinator
        ):
            await thz_module.async_setup_entry(hass, entry)

        stored = hass.data[DOMAIN][entry.entry_id]
        assert "pxxFB" in stored["unsupported_blocks"]
        assert "pxxFB" in stored["coordinators"]  # still stored, just unsupported

    @pytest.mark.asyncio
    async def test_area_and_alias_passed_to_device_registry(self):
        hass = _mock_hass()
        entry = _mock_config_entry(alias="Basement THZ", area="Basement")
        device = _fake_device()
        dev_reg = _default_dev_reg()

        with _patched_setup(
            device=device,
            coordinator_factory=lambda *a, **kw: _fake_coordinator(),
            dev_reg=dev_reg,
        ):
            await thz_module.async_setup_entry(hass, entry)

        _, kwargs = dev_reg.async_get_or_create.call_args
        assert kwargs["name"] == "Basement THZ"
        assert kwargs["suggested_area"] == "Basement"

    @pytest.mark.asyncio
    async def test_log_level_applied(self):
        import logging

        hass = _mock_hass()
        entry = _mock_config_entry(log_level="debug")
        device = _fake_device(blocks=[])

        with _patched_setup(device=device):
            await thz_module.async_setup_entry(hass, entry)

        assert thz_module._LOGGER.level == logging.DEBUG
        thz_module._LOGGER.setLevel(logging.NOTSET)  # reset for other tests


class TestAsyncUnloadEntry:
    @pytest.mark.asyncio
    async def test_unload_closes_device_and_removes_services_when_last_entry(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        device = _fake_device()
        hass.data[DOMAIN] = {entry.entry_id: {"device": device}}
        hass.config_entries.async_entries = MagicMock(return_value=[])

        result = await thz_module.async_unload_entry(hass, entry)

        assert result is True
        hass.async_add_executor_job.assert_awaited_once_with(device.close)
        assert entry.entry_id not in hass.data[DOMAIN]
        removed = {c.args[1] for c in hass.services.async_remove.call_args_list}
        assert "read_raw_register" in removed

    @pytest.mark.asyncio
    async def test_unload_keeps_services_with_remaining_entries(self):
        hass = _mock_hass()
        entry = _mock_config_entry("entry1")
        other_entry = MagicMock(entry_id="entry2")
        device = _fake_device()
        hass.data[DOMAIN] = {entry.entry_id: {"device": device}}
        hass.config_entries.async_entries = MagicMock(return_value=[other_entry])

        result = await thz_module.async_unload_entry(hass, entry)

        assert result is True
        hass.services.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_unload_platform_failure_leaves_data_untouched(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        device = _fake_device()
        hass.data[DOMAIN] = {entry.entry_id: {"device": device}}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

        result = await thz_module.async_unload_entry(hass, entry)

        assert result is False
        assert entry.entry_id in hass.data[DOMAIN]
        hass.async_add_executor_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unload_missing_entry_data_is_safe(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        hass.data[DOMAIN] = {}

        result = await thz_module.async_unload_entry(hass, entry)

        assert result is True
        hass.async_add_executor_job.assert_not_awaited()


class TestAsyncRemoveConfigEntryDevice:
    @pytest.mark.asyncio
    async def test_always_returns_true(self):
        hass = _mock_hass()
        result = await thz_module.async_remove_config_entry_device(
            hass, MagicMock(), MagicMock()
        )
        assert result is True


class TestAsyncRemoveEntry:
    @pytest.mark.asyncio
    async def test_removes_all_entities_for_entry(self):
        hass = _mock_hass()
        entry = _mock_config_entry()
        entity1 = MagicMock(entity_id="sensor.thz_a")
        entity2 = MagicMock(entity_id="sensor.thz_b")

        with patch.object(
            thz_module.er, "async_get", return_value=MagicMock()
        ) as mock_get, patch.object(
            thz_module.er, "async_entries_for_config_entry",
            return_value=[entity1, entity2],
        ):
            await thz_module.async_remove_entry(hass, entry)

        mock_get.return_value.async_remove.assert_any_call("sensor.thz_a")
        mock_get.return_value.async_remove.assert_any_call("sensor.thz_b")


class TestMigrateDisableHiddenEntities:
    @pytest.mark.asyncio
    async def test_skips_when_already_migrated(self):
        hass = _mock_hass()
        entry = _mock_config_entry(_hidden_entities_migrated=True)

        with patch.object(thz_module.er, "async_get") as mock_get:
            await thz_module._async_migrate_disable_hidden_entities(hass, entry)
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_disables_hidden_entities_and_sets_flag(self):
        hass = _mock_hass()
        entry = _mock_config_entry()

        hidden_entity = MagicMock(
            unique_id="programHC1_Mo_0", original_name=None, name=None,
            entity_id="time.thz_program", disabled_by=None,
        )
        visible_entity = MagicMock(
            unique_id="insideTempRC", original_name="Inside Temperature",
            name=None, entity_id="sensor.thz_inside_temp", disabled_by=None,
        )
        already_disabled = MagicMock(
            unique_id="programHC2_Mo_0", original_name=None, name=None,
            entity_id="time.thz_program2", disabled_by="user",
        )

        ent_reg = MagicMock()
        ent_reg.async_update_entity = MagicMock()

        with patch.object(thz_module.er, "async_get", return_value=ent_reg), \
             patch.object(
                 thz_module.er, "async_entries_for_config_entry",
                 return_value=[hidden_entity, visible_entity, already_disabled],
             ):
            await thz_module._async_migrate_disable_hidden_entities(hass, entry)

        ent_reg.async_update_entity.assert_called_once()
        call_args = ent_reg.async_update_entity.call_args
        assert call_args[0][0] == "time.thz_program"
        hass.config_entries.async_update_entry.assert_called_once()
        _, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs["data"]["_hidden_entities_migrated"] is True


class TestCleanupOrphanedEntities:
    @pytest.mark.asyncio
    async def test_removes_orphaned_thz_entities(self):
        hass = _mock_hass()
        orphaned = MagicMock(
            platform="thz", config_entry_id=None, entity_id="sensor.orphan"
        )
        owned = MagicMock(
            platform="thz", config_entry_id="entry1", entity_id="sensor.owned"
        )
        other_domain = MagicMock(
            platform="other", config_entry_id=None, entity_id="light.x"
        )

        ent_reg = MagicMock()
        ent_reg.entities = {
            "sensor.orphan": orphaned,
            "sensor.owned": owned,
            "light.x": other_domain,
        }
        ent_reg.async_remove = MagicMock()

        with patch.object(thz_module.er, "async_get", return_value=ent_reg):
            await thz_module._async_cleanup_orphaned_entities(hass)

        ent_reg.async_remove.assert_called_once_with("sensor.orphan")

    @pytest.mark.asyncio
    async def test_no_orphans_is_noop(self):
        hass = _mock_hass()
        ent_reg = MagicMock()
        ent_reg.entities = {}
        ent_reg.async_remove = MagicMock()

        with patch.object(thz_module.er, "async_get", return_value=ent_reg):
            await thz_module._async_cleanup_orphaned_entities(hass)

        ent_reg.async_remove.assert_not_called()


class TestAsyncUpdateBlock:
    @pytest.mark.asyncio
    async def test_reads_single_block(self):
        hass = _mock_hass()
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=b"\x01\x02\x03\x04")

        result = await thz_module._async_update_block(hass, device, "pxxFB")

        assert result == b"\x01\x02\x03\x04"

    @pytest.mark.asyncio
    async def test_paired_block_combines_values(self):
        hass = _mock_hass()
        device = MagicMock()
        # cmd2 (low) result: 8 bytes, low value at offset 4:6 = 100
        cmd2_result = bytearray(8)
        cmd2_result[4:6] = (100).to_bytes(2, "big", signed=True)
        # cmd3 (high) result: high value at offset 4:6 = 2
        cmd3_result = bytearray(8)
        cmd3_result[4:6] = (2).to_bytes(2, "big", signed=True)

        device.async_execute = AsyncMock(
            side_effect=[bytes(cmd2_result), bytes(cmd3_result)]
        )

        result = await thz_module._async_update_block(
            hass, device, "pxx0A091A", paired_blocks={"pxx0A091A": "pxx0A091C"}
        )

        combined = int.from_bytes(result[4:8], "big", signed=True)
        assert combined == 2 * 1000 + 100

    @pytest.mark.asyncio
    async def test_unsupported_register_returns_none(self):
        from custom_components.thz.thz_device import THZRegisterNotSupportedError

        hass = _mock_hass()
        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=THZRegisterNotSupportedError("no"))

        result = await thz_module._async_update_block(hass, device, "pxxFB")

        assert result is None

    @pytest.mark.asyncio
    async def test_other_error_raises_update_failed(self):
        hass = _mock_hass()
        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(thz_module.UpdateFailed):
            await thz_module._async_update_block(hass, device, "pxxFB")
