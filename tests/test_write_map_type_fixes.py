"""Regression coverage for WRITE_MAP entries typed with a decode_type, not a platform.

Each write-platform module (number.py, switch.py, select.py, button.py, ...)
builds its entities by filtering WRITE_MAP entries on ``entry["type"] ==
platform_type`` (see ``platform_setup.async_setup_write_platform``). A "type"
value that isn't one of the real platform names ("number", "switch",
"select", "button", "time", ...) never matches any platform's filter, so the
entry is silently dropped -- no entity is ever created for it, with no error
or warning to say why.

Three write maps had entries where "type" had accidentally been set to a
*decode_type* token ("pclean" / "0clean") instead of a platform name:

- write_map_206.py: ~101 entries typed "pclean" (should be "number").
- write_map_214.py: "ResetErrors" typed "0clean" (should be "button").
- write_map_X39tech.py: "zPumpHC"/"zPumpDHW" typed "select" with decode_type
  "0clean", which has no registered select options (should be "number").

These tests pin the corrected types and add a standing invariant so a
decode_type token can't silently regress back into a "type" field again.
"""

from custom_components.thz.register_maps.write_map_206 import (
    WRITE_MAP as WRITE_MAP_206,
)
from custom_components.thz.register_maps.write_map_214 import (
    WRITE_MAP as WRITE_MAP_214,
)
from custom_components.thz.register_maps.write_map_X39tech import (
    WRITE_MAP as WRITE_MAP_X39TECH,
)

# decode_type tokens that must never appear as a "type" (platform) value.
_DECODE_TYPE_TOKENS_MISUSED_AS_PLATFORM = {"pclean", "0clean", "1clean"}

# The map's own non-entry metadata keys, skipped when iterating entries.
_METADATA_KEYS = {"Firmware", "firmware"}


class TestWriteMap206PcleanFix:
    """write_map_206.py: 'pclean' was never a valid platform type."""

    def test_no_entries_still_typed_pclean(self):
        """No entry should be left with the old bogus 'pclean' type."""
        offenders = [
            name
            for name, entry in WRITE_MAP_206.items()
            if name not in _METADATA_KEYS and entry.get("type") == "pclean"
        ]
        assert offenders == [], f"still typed 'pclean': {offenders}"

    def test_p01RoomTempDay_is_number_type(self):
        """Spot-check a representative entry: p01RoomTempDay."""
        entry = WRITE_MAP_206["p01RoomTempDay"]
        assert entry["type"] == "number"
        # decode_type is untouched -- the bug was only in "type".
        assert entry["decode_type"] == "pClean"

    def test_previously_pclean_entries_are_now_number_or_ptime(self):
        """Every entry that used to say 'pclean' is now 'number' or 'ptime'.

        The exceptions are the handful whose decode_type is time-flavored
        and which were already correctly typed 'ptime' (untouched by this
        fix).
        """
        for name, entry in WRITE_MAP_206.items():
            if name in _METADATA_KEYS:
                continue
            if entry.get("decode_type") == "pClean":
                assert entry["type"] in ("number", "ptime"), (
                    f"{name}: unexpected type {entry['type']!r}"
                )


class TestWriteMap214ResetErrorsFix:
    """write_map_214.py: 'ResetErrors' was typed '0clean' instead of 'button'."""

    def test_reset_errors_is_button_type(self):
        entry = WRITE_MAP_214["ResetErrors"]
        assert entry["type"] == "button", (
            f"ResetErrors should be type 'button', got {entry['type']!r}"
        )
        assert entry["decode_type"] == "0clean"
        assert entry["icon"] == "mdi:trash-can-outline"


class TestWriteMapX39techPumpFix:
    """write_map_X39tech.py: zPumpHC/zPumpDHW typed 'select' with a bad decode_type.

    The unregistered decode_type guaranteed empty options and a ValueError
    on any read/write.
    """

    def test_zPumpHC_is_number_type(self):
        entry = WRITE_MAP_X39TECH["zPumpHC"]
        assert entry["type"] == "number"
        assert entry["decode_type"] == "0clean"

    def test_zPumpDHW_is_number_type(self):
        entry = WRITE_MAP_X39TECH["zPumpDHW"]
        assert entry["type"] == "number"
        assert entry["decode_type"] == "0clean"

    def test_zControlValveDHW_untouched(self):
        """ZControlValveDHW was not part of this fix -- confirm it's unaffected."""
        entry = WRITE_MAP_X39TECH["zControlValveDHW"]
        assert entry["type"] == "select"
        assert entry["decode_type"] == "1clean"


class TestNoDecodeTypeTokenMisusedAsPlatform:
    """Standing invariant: a WRITE_MAP entry's "type" must never be a bare decode_type.

    This is what let all three bugs above go unnoticed -- the entries were
    simply skipped at platform setup instead of raising.
    """

    def _assert_map_clean(self, write_map, map_name):
        offenders = [
            f"{map_name}.{name} (type={entry.get('type')!r})"
            for name, entry in write_map.items()
            if name not in _METADATA_KEYS
            and entry.get("type") in _DECODE_TYPE_TOKENS_MISUSED_AS_PLATFORM
        ]
        assert offenders == [], f"decode_type token used as platform type: {offenders}"

    def test_write_map_206_clean(self):
        self._assert_map_clean(WRITE_MAP_206, "write_map_206")

    def test_write_map_214_clean(self):
        self._assert_map_clean(WRITE_MAP_214, "write_map_214")

    def test_write_map_X39tech_clean(self):
        self._assert_map_clean(WRITE_MAP_X39TECH, "write_map_X39tech")
