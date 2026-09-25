"""A write that fails is reported to the caller of the action."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.thz.exceptions import THZConnectionError

from .common import entity_id, setup_entry


async def _line_down(*_args, **_kwargs) -> bytes:
    raise THZConnectionError("line down")


@pytest.mark.parametrize(
    ("domain", "suffix", "service", "data"),
    [
        ("number", "p01roomtempdayhc1", "set_value", {"value": 21.0}),
        (
            "climate",
            "climate_heating_circuit",
            "set_preset_mode",
            {"preset_mode": "standby"},
        ),
        ("fan", "fan_ventilation", "turn_off", {}),
    ],
)
async def test_failed_write_raises(
    hass: HomeAssistant, fake_device, domain, suffix, service, data
) -> None:
    entry = await setup_entry(hass)
    target = entity_id(hass, entry, domain, suffix)
    before = hass.states.get(target).state
    device = fake_device.instances[-1]

    with (
        patch.object(device, "send_request", _line_down),
        pytest.raises(HomeAssistantError, match="line down"),
    ):
        await hass.services.async_call(
            domain, service, {"entity_id": target, **data}, blocking=True
        )

    assert hass.states.get(target).state == before
