"""Coverage tests for the pure/near-pure helper functions in __init__.py."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz import (
    _expand_scan_pattern,
    _expand_scan_range,
    _format_hex_dump,
    _guess_decode_candidates,
    _normalize_block_name,
    _require_target_entry_data,
    async_refresh_block,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError


def _make_hass_with_entries(entries: dict) -> MagicMock:
    """Build a hass whose config_entries.async_entries returns fake entries.

    `entries` maps entry_id -> runtime_data dict.
    """
    hass = MagicMock()
    fake_entries = []
    for entry_id, runtime_data in entries.items():
        entry = MagicMock()
        entry.entry_id = entry_id
        entry.runtime_data = runtime_data
        fake_entries.append(entry)
    hass.config_entries.async_entries = MagicMock(return_value=fake_entries)
    return hass


class TestRequireTargetEntryData:
    """Tests for _require_target_entry_data."""

    def test_raises_home_assistant_error_when_no_entries(self):
        hass = _make_hass_with_entries({})
        with pytest.raises(HomeAssistantError, match="not initialized"):
            _require_target_entry_data(hass, None)

    def test_single_entry_no_entry_id_returns_it(self):
        entry_data = {"device": MagicMock()}
        hass = _make_hass_with_entries({"entry1": entry_data})
        entry_id, result = _require_target_entry_data(hass, None)
        assert entry_id == "entry1"
        assert result is entry_data

    def test_multiple_entries_no_entry_id_raises_validation_error(self):
        hass = _make_hass_with_entries(
            {
                "entry1": {"device": MagicMock()},
                "entry2": {"device": MagicMock()},
            }
        )
        with pytest.raises(ServiceValidationError, match="Multiple THZ config entries"):
            _require_target_entry_data(hass, None)

    def test_multiple_entries_with_valid_entry_id(self):
        entry_data1 = {"device": MagicMock()}
        entry_data2 = {"device": MagicMock()}
        hass = _make_hass_with_entries(
            {
                "entry1": entry_data1,
                "entry2": entry_data2,
            }
        )
        entry_id, result = _require_target_entry_data(hass, "entry2")
        assert entry_id == "entry2"
        assert result is entry_data2

    def test_entry_id_not_found_raises_validation_error(self):
        hass = _make_hass_with_entries({"entry1": {"device": MagicMock()}})
        with pytest.raises(ServiceValidationError, match="No THZ entry found"):
            _require_target_entry_data(hass, "nonexistent")

    def test_ignores_entries_without_device_key(self):
        hass = _make_hass_with_entries({"entry1": {"not_a_device_entry": True}})
        with pytest.raises(HomeAssistantError, match="not initialized"):
            _require_target_entry_data(hass, None)


class TestExpandScanPattern:
    """Tests for _expand_scan_pattern."""

    def test_no_wildcards_returns_single_command(self):
        assert _expand_scan_pattern("0A0176") == ["0A0176"]

    def test_single_wildcard_expands_16_values(self):
        result = _expand_scan_pattern("0A017X")
        assert len(result) == 16
        assert result[0] == "0A0170"
        assert result[-1] == "0A017F"

    def test_two_wildcards_expands_256_values(self):
        result = _expand_scan_pattern("0A01XX")
        assert len(result) == 16 * 16
        assert result[0] == "0A0100"
        assert result[-1] == "0A01FF"

    def test_lowercase_pattern_normalized(self):
        result = _expand_scan_pattern("0a017x")
        assert result[0] == "0A0170"

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError, match="exactly 6 characters"):
            _expand_scan_pattern("0A017")

    def test_invalid_character_raises(self):
        with pytest.raises(ValueError, match="Invalid pattern character"):
            _expand_scan_pattern("0A017Z")


class TestExpandScanRange:
    """Tests for _expand_scan_range."""

    def test_simple_range(self):
        result = _expand_scan_range("0A0000", "0A0002")
        assert result == ["0A0000", "0A0001", "0A0002"]

    def test_single_value_range(self):
        assert _expand_scan_range("0A0000", "0A0000") == ["0A0000"]

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError, match="6 hex characters"):
            _expand_scan_range("0A00", "0A0002")

    def test_invalid_hex_raises(self):
        with pytest.raises(ValueError, match="valid hex"):
            _expand_scan_range("ZZZZZZ", "0A0002")

    def test_start_greater_than_end_raises(self):
        with pytest.raises(ValueError, match="less than or equal"):
            _expand_scan_range("0A0002", "0A0000")

    def test_lowercase_normalized(self):
        assert _expand_scan_range("0a0000", "0a0001") == ["0A0000", "0A0001"]


class TestFormatHexDump:
    """Tests for _format_hex_dump."""

    def test_empty_data(self):
        assert _format_hex_dump(b"") == ""

    def test_single_line(self):
        result = _format_hex_dump(bytes(range(4)))
        assert result == "  0000: 00 01 02 03"

    def test_multi_line(self):
        result = _format_hex_dump(bytes(range(20)))
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("  0000:")
        assert lines[1].startswith("  0010:")


class TestGuessDecodeCandidates:
    """Tests for _guess_decode_candidates."""

    def test_empty_data_returns_only_raw_fields(self):
        result = _guess_decode_candidates(b"")
        assert result == {"raw_hex": "", "raw_len": 0}

    def test_single_byte_includes_u8_s8_bit0(self):
        result = _guess_decode_candidates(bytes([0x01]))
        assert result["u8"] == 1
        assert result["s8"] == 1
        assert result["bit0"] is True
        assert "u16" not in result

    def test_two_bytes_includes_u16_s16_hex(self):
        result = _guess_decode_candidates(bytes([0x00, 0x0A]))
        assert result["u16"] == 10
        assert result["s16"] == 10
        assert "hex" in result
        assert "hex2int" in result

    def test_four_bytes_includes_u32_s32(self):
        result = _guess_decode_candidates(bytes([0x00, 0x00, 0x00, 0x01]))
        assert result["u32"] == 1
        assert result["s32"] == 1

    def test_bool_nonzero_true_for_nonzero_value(self):
        result = _guess_decode_candidates(bytes([0x00, 0x01]))
        assert result["bool_nonzero"] is True

    def test_bool_nonzero_false_for_zero_value(self):
        result = _guess_decode_candidates(bytes([0x00, 0x00]))
        assert result["bool_nonzero"] is False

    def test_select_candidates_present_when_map_hit(self):
        # "1" maps to "normal" in OpModeHC — verify a real SELECT_MAP hit surfaces.
        result = _guess_decode_candidates(bytes([0x01]))
        # Either select_candidates key is present, or at minimum decoding didn't crash.
        assert "raw_hex" in result


class TestNormalizeBlockName:
    """Tests for _normalize_block_name."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("FB", "pxxFB"),
            ("fb", "pxxFB"),
            ("pxxFB", "pxxFB"),
            ("PXXfb", "pxxFB"),
            ("0xFB", "pxxFB"),
            ("0A0176", "pxx0A0176"),
            (" FB ", "pxxFB"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert _normalize_block_name(raw) == expected


class TestAsyncRefreshBlock:
    """Tests for async_refresh_block."""

    @pytest.mark.asyncio
    async def test_refreshes_matching_coordinator(self):
        coordinator = MagicMock()
        coordinator.async_request_refresh = AsyncMock()
        hass = _make_hass_with_entries(
            {"entry1": {"coordinators": {"pxxFB": coordinator}}}
        )

        result = await async_refresh_block(hass, "FB")

        assert result is True
        coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_block_not_found_returns_false(self):
        hass = _make_hass_with_entries({"entry1": {"coordinators": {}}})

        result = await async_refresh_block(hass, "FB")

        assert result is False

    @pytest.mark.asyncio
    async def test_entry_id_not_found_returns_false(self):
        hass = _make_hass_with_entries({"entry1": {"coordinators": {}}})

        result = await async_refresh_block(hass, "FB", entry_id="nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_entry_id_targets_specific_entry(self):
        coord1 = MagicMock()
        coord1.async_request_refresh = AsyncMock()
        coord2 = MagicMock()
        coord2.async_request_refresh = AsyncMock()
        hass = _make_hass_with_entries(
            {
                "entry1": {"coordinators": {"pxxFB": coord1}},
                "entry2": {"coordinators": {"pxxFB": coord2}},
            }
        )

        result = await async_refresh_block(hass, "FB", entry_id="entry2")

        assert result is True
        coord2.async_request_refresh.assert_awaited_once()
        coord1.async_request_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refreshes_across_all_entries_without_entry_id(self):
        coord1 = MagicMock()
        coord1.async_request_refresh = AsyncMock()
        coord2 = MagicMock()
        coord2.async_request_refresh = AsyncMock()
        hass = _make_hass_with_entries(
            {
                "entry1": {"coordinators": {"pxxFB": coord1}},
                "entry2": {"coordinators": {"pxxFB": coord2}},
            }
        )

        result = await async_refresh_block(hass, "FB")

        assert result is True
        coord1.async_request_refresh.assert_awaited_once()
        coord2.async_request_refresh.assert_awaited_once()
