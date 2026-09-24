"""Tests for repairs.py (the clock drift fix flow)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.thz import repairs
from custom_components.thz.repairs import ClockDriftRepairFlow, async_create_fix_flow
from tests.helpers import make_runtime_data


def _flow(entry):
    flow = ClockDriftRepairFlow("entry1")
    flow.issue_id = "clock_drift_entry1"
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_entry.return_value = entry
    return flow


def _entry(loaded=True):
    entry = MagicMock()
    entry.data = {"host": "192.0.2.1"}
    entry.runtime_data = make_runtime_data() if loaded else None
    return entry


@pytest.mark.asyncio
async def test_create_fix_flow():
    flow = await async_create_fix_flow(
        MagicMock(), "clock_drift_entry1", {"entry_id": "entry1"}
    )
    assert isinstance(flow, ClockDriftRepairFlow)
    assert flow._entry_id == "entry1"


@pytest.mark.asyncio
async def test_init_shows_the_confirmation():
    result = await _flow(_entry()).async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert result["errors"] == {}


@pytest.mark.asyncio
async def test_confirm_sets_the_clock():
    entry = _entry()
    flow = _flow(entry)
    with patch.object(repairs, "async_write_device_clock", AsyncMock()) as write:
        result = await flow.async_step_confirm({"auto_sync_clock": False})
    assert result["type"] == "create_entry"
    write.assert_awaited_once()
    assert write.await_args.args[1] is entry.runtime_data.device
    flow.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_can_turn_on_automatic_sync():
    entry = _entry()
    flow = _flow(entry)
    with patch.object(repairs, "async_write_device_clock", AsyncMock()):
        await flow.async_step_confirm({"auto_sync_clock": True})
    flow.hass.config_entries.async_update_entry.assert_called_once_with(
        entry, data={"host": "192.0.2.1", "auto_sync_clock": True}
    )


@pytest.mark.asyncio
async def test_device_error_shows_the_form_again():
    flow = _flow(_entry())
    write = AsyncMock(side_effect=OSError("no answer"))
    with patch.object(repairs, "async_write_device_clock", write):
        result = await flow.async_step_confirm({"auto_sync_clock": True})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    flow.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize("entry", [None, _entry(loaded=False)])
@pytest.mark.asyncio
async def test_aborts_without_a_loaded_entry(entry):
    result = await _flow(entry).async_step_confirm()
    assert result == {"type": "abort", "reason": "not_loaded"}
