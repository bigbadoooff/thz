"""HC2 climate entity when pxxF5 has no hcOpMode field (ported from m-l fork).

pxxF5 has never had a mapped hcOpMode on any firmware, so the HC2 climate
entity used to be skipped everywhere. It is now created from the target
temperature alone with a fixed HEAT hvac_mode, and (like every other HC2
entity) is disabled by default unless enable_hc2 is set.
"""

from unittest.mock import MagicMock

from homeassistant.components.climate import HVACMode
import pytest

from custom_components.thz.__init__ import _entity_should_be_hidden
from custom_components.thz.climate import THZClimate, async_setup_entry
from custom_components.thz.const import (
    ENTITY_VISIBILITY_ALL,
    ENTITY_VISIBILITY_DEFAULT,
)
from tests.helpers import FakeRegisterManager, make_runtime_data

_F5_REAL = [
    ("hc2SetpointTemp:", 16, 4, "hex2int", 10, {}),
    ("hc2MixerValve:", 20, 2, "hex", 1, {}),
]
_HC2_WRITE = {
    "p01RoomTempDayHC2": {"command": "0B0007", "step": 0.1, "decode_type": "5temp"},
}


def _setup(enable_hc2, f5_entries=_F5_REAL):
    register_manager = FakeRegisterManager({"pxxF5": f5_entries})
    config_entry = MagicMock()
    config_entry.data = {"enable_hc2": enable_hc2}
    config_entry.runtime_data = make_runtime_data(
        **{
            "coordinators": {"pxxF5": MagicMock()},
            "device": MagicMock(),
            "device_id": "dev",
            "write_manager": MagicMock(
                get_all_registers=MagicMock(return_value=_HC2_WRITE)
            ),
            "register_manager": register_manager,
        }
    )
    added = []
    add = MagicMock(side_effect=lambda ents, *a: added.extend(ents))
    return config_entry, add, added


class TestHc2CreatedWithoutOpMode:
    @pytest.mark.asyncio
    async def test_entity_is_created_without_hcopmode(self):
        config_entry, add, added = _setup(enable_hc2=True)
        await async_setup_entry(MagicMock(), config_entry, add)
        assert [e._attr_translation_key for e in added] == ["heating_circuit_2"]

    @pytest.mark.asyncio
    async def test_hvac_mode_is_fixed_heat(self):
        config_entry, add, added = _setup(enable_hc2=True)
        await async_setup_entry(MagicMock(), config_entry, add)
        entity = added[0]
        entity.coordinator.data = bytes(60)
        assert entity._op_mode_offset is None
        assert entity.hvac_mode == HVACMode.HEAT

    @pytest.mark.asyncio
    async def test_still_skipped_without_target_temperature_field(self):
        config_entry, add, added = _setup(enable_hc2=True, f5_entries=[])
        await async_setup_entry(MagicMock(), config_entry, add)
        assert added == []

    @pytest.mark.asyncio
    async def test_op_mode_field_still_used_when_a_map_provides_one(self):
        entries = [*_F5_REAL, ("hcOpMode:", 48, 2, "opmodehc", 1, {})]
        config_entry, add, added = _setup(enable_hc2=True, f5_entries=entries)
        await async_setup_entry(MagicMock(), config_entry, add)
        assert added[0]._op_mode_offset == 24


class TestHc2DisabledByDefault:
    @pytest.mark.asyncio
    async def test_disabled_in_registry_unless_enable_hc2(self):
        config_entry, add, added = _setup(enable_hc2=False)
        await async_setup_entry(MagicMock(), config_entry, add)
        assert added[0].entity_registry_enabled_default is False

    @pytest.mark.asyncio
    async def test_enabled_when_enable_hc2(self):
        config_entry, add, added = _setup(enable_hc2=True)
        await async_setup_entry(MagicMock(), config_entry, add)
        assert added[0].entity_registry_enabled_default is True

    def test_other_climate_entities_are_unaffected(self):
        entity = THZClimate(
            coordinator=MagicMock(),
            cooling_coordinator=None,
            device=MagicMock(),
            device_id="dev",
            translation_key="heating_circuit",
            current_temp_offset=0,
            current_temp_length=2,
            target_temp_offset=2,
            target_temp_length=2,
            op_mode_offset=4,
            op_mode_length=1,
            heat_setpoint_entry=None,
            cool_switch_entry=None,
            cool_setpoint_entry=None,
        )
        assert entity.entity_registry_enabled_default is True


class TestVisibilityReconcile:
    """Toggling enable_hc2 must reach the HC2 climate entity too."""

    UID = "thz_dev_climate_heating_circuit_2"

    @pytest.mark.parametrize(
        "visibility", [ENTITY_VISIBILITY_DEFAULT, ENTITY_VISIBILITY_ALL]
    )
    def test_hidden_without_enable_hc2(self, visibility):
        assert _entity_should_be_hidden(
            self.UID, "heating circuit 2", visibility, False
        )

    @pytest.mark.parametrize(
        "visibility", [ENTITY_VISIBILITY_DEFAULT, ENTITY_VISIBILITY_ALL]
    )
    def test_shown_with_enable_hc2_regardless_of_tier(self, visibility):
        assert not _entity_should_be_hidden(
            self.UID, "heating circuit 2", visibility, True
        )

    def test_hc1_climate_is_never_hidden(self):
        assert not _entity_should_be_hidden(
            "thz_dev_climate_heating_circuit",
            "heating circuit",
            ENTITY_VISIBILITY_DEFAULT,
            False,
        )
