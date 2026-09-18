"""Firmware 4.19 (Tecalor THZ 303 SOL) profile, ported from Darian6969's fork."""

import json
import pathlib

import pytest

from custom_components.thz.const import (
    FIRMWARE_OVERRIDE_AUTO,
    FIRMWARE_PROFILE_LABELS,
)
from custom_components.thz.register_maps import register_map_all
from custom_components.thz.register_maps.register_map_manager import (
    FIRMWARE_MAPS,
    RegisterMapManager,
    RegisterMapManagerWrite,
)

_COMPONENT = (
    pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "thz"
)
_SHORT_PAYLOAD_SENSORS = {"flowRate", "p_HCw", "humidityAirOut", "insideTemp"}


def _norm(name):
    return name.strip().rstrip(":").strip()


class TestProfile:
    def test_419_is_a_known_firmware(self):
        assert FIRMWARE_MAPS["419"] == {
            "write": ["write_map_439_539", "write_map_439"],
            "read": ["readings_map_439", "register_map_419"],
        }

    def test_write_entities_match_the_439_profile(self):
        assert (
            RegisterMapManagerWrite("419").get_all_registers()
            == RegisterMapManagerWrite("439").get_all_registers()
        )

    def test_energy_and_runtime_blocks_are_loaded(self):
        blocks = RegisterMapManager("419").get_all_registers()
        assert {"pxx09", "pxx0A091A", "pxx0A0920"} <= set(blocks)


class TestShortPxxFbPayload:
    def test_the_four_out_of_payload_sensors_are_disabled(self):
        entries = {
            _norm(e[0]): e
            for e in RegisterMapManager("419").get_all_registers()["pxxFB"]
        }
        disabled = {n for n, e in entries.items() if e[3] == "disabled"}
        assert disabled == _SHORT_PAYLOAD_SENSORS

    def test_every_other_sensor_keeps_its_base_meta(self):
        base = {_norm(e[0]): e for e in register_map_all.REGISTER_MAP["pxxFB"]}
        merged = {
            _norm(e[0]): e
            for e in RegisterMapManager("419").get_all_registers()["pxxFB"]
        }
        for name, entry in merged.items():
            if name in _SHORT_PAYLOAD_SENSORS or name not in base:
                continue
            assert len(entry) > 5 or len(base[name]) <= 5, name

    def test_no_power_rescaling_without_evidence(self):
        entries = {
            _norm(e[0]): e
            for e in RegisterMapManager("419").get_all_registers()["pxxFB"]
        }
        assert entries["actualPower_Pel"][4] == 1


class TestFirmwareOverrideChoices:
    """Every selectable profile must exist and be translated."""

    def test_419_is_selectable(self):
        assert FIRMWARE_PROFILE_LABELS["419"] == "4.19"

    def test_every_profile_is_a_firmware_map(self):
        for key in FIRMWARE_PROFILE_LABELS:
            if key != FIRMWARE_OVERRIDE_AUTO:
                assert key in FIRMWARE_MAPS, key

    @pytest.mark.parametrize(
        "path", ["strings.json", "translations/en.json", "translations/de.json"]
    )
    def test_selector_options_match_the_profile_list(self, path):
        with open(_COMPONENT / path, encoding="utf-8") as fh:
            options = json.load(fh)["selector"]["firmware_override"]["options"]
        assert set(options) == set(FIRMWARE_PROFILE_LABELS)
