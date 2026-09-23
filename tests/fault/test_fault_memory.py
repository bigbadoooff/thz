"""D1 fault memory: decoding, acknowledgement tracking and the guarded clear.

Ported from the Darian6969 FW 4.19 fork, rebuilt on upstream conventions
(shared fault table, device.async_execute, no extra polling).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.thz.fault_memory import (
    CLEAR_CONFIRMATION,
    FAULT_CLEAR_PAYLOAD,
    FAULT_MEMORY_COMMAND,
    clear_fault_memory,
    decode_fault_date,
    decode_fault_memory,
    decode_fault_time,
    new_record_start,
    read_fault_memory,
    record_fingerprints,
)
from custom_components.thz.fault_state import (
    STATUS_FAULT,
    STATUS_OK,
    THZFaultTracker,
)


def _record(number, hhmm, ddmm):
    """Six-byte record: number, reserved, time and date each byte-swapped."""
    t = int(hhmm.replace(":", ""))
    d = int(ddmm.replace(".", ""))
    return bytes([number, 0]) + t.to_bytes(2, "little") + d.to_bytes(2, "little")


def _payload(*records, reported=None):
    count = len(records) if reported is None else reported
    return bytes([0x00, 0xD1, count, 0x00]) + b"".join(records)


R3 = _record(3, "08:15", "05.01")
R5 = _record(5, "23:59", "31.12")
R11 = _record(11, "00:00", "01.02")


class TestFieldDecoding:
    def test_time_is_byte_swapped_decimal(self):
        assert decode_fault_time((815).to_bytes(2, "little")) == "08:15"

    @pytest.mark.parametrize("value", [2400, 1260, 9999])
    def test_implausible_time_is_none(self, value):
        assert decode_fault_time(value.to_bytes(2, "little")) is None

    def test_date_is_byte_swapped_decimal(self):
        assert decode_fault_date((501).to_bytes(2, "little")) == "05.01"

    @pytest.mark.parametrize("value", [0, 132, 3113, 100])
    def test_implausible_date_is_none(self, value):
        assert decode_fault_date(value.to_bytes(2, "little")) is None

    def test_wrong_length_is_none(self):
        assert decode_fault_time(b"\x01") is None
        assert decode_fault_date(b"") is None


class TestDecodeFaultMemory:
    def test_empty_memory(self):
        decoded = decode_fault_memory(_payload())
        assert decoded["valid"] and decoded["entries"] == []

    def test_records_are_decoded_oldest_first(self):
        decoded = decode_fault_memory(_payload(R3, R5))
        first, second = decoded["entries"]
        assert (first["fault_number"], first["fault_code"]) == (3, "F03")
        assert first["description"] == "F03_HighPreasureGuardFault"
        assert (first["time"], first["date"]) == ("08:15", "05.01")
        assert second["fault_number"] == 5 and second["time"] == "23:59"

    def test_unknown_fault_number_gets_a_placeholder_name(self):
        decoded = decode_fault_memory(_payload(_record(99, "01:01", "01.01")))
        assert decoded["entries"][0]["description"] == "F99_Unknown"

    def test_decodes_up_to_ten_records(self):
        decoded = decode_fault_memory(_payload(*([R3] * 10)))
        assert len(decoded["entries"]) == 10

    def test_count_is_capped_and_warned_when_records_are_missing(self):
        decoded = decode_fault_memory(_payload(R3, reported=4))
        assert len(decoded["entries"]) == 1
        assert "warning" in decoded

    def test_more_than_ten_reported_is_capped(self):
        decoded = decode_fault_memory(_payload(*([R3] * 12), reported=12))
        assert len(decoded["entries"]) == 10

    def test_short_payload_is_invalid(self):
        assert not decode_fault_memory(b"\x00\xd1")["valid"]

    def test_wrong_command_echo_is_invalid(self):
        assert not decode_fault_memory(b"\x00\xd2\x00\x00")["valid"]

    def test_partial_trailing_record_is_ignored(self):
        decoded = decode_fault_memory(_payload(R3) + b"\x05\x00")
        assert len(decoded["entries"]) == 1


class TestNewRecordStart:
    def test_no_history_means_everything_is_new(self):
        assert new_record_start([], ["a", "b"]) == 0

    def test_identical_history_has_nothing_new(self):
        assert new_record_start(["a", "b"], ["a", "b"]) == 2

    def test_appended_record_is_new(self):
        assert new_record_start(["a", "b"], ["a", "b", "c"]) == 2

    def test_rolling_window_keeps_overlap(self):
        assert new_record_start(["a", "b", "c"], ["b", "c", "d"]) == 2

    def test_no_overlap_means_everything_is_new(self):
        assert new_record_start(["a"], ["x", "y"]) == 0

    def test_fingerprints_skip_incomplete_records(self):
        entries = [{"complete": True, "raw": "aa"}, {"complete": False, "raw": "b"}]
        assert record_fingerprints(entries) == ["AA"]


class FakeStore:
    def __init__(self, data=None):
        self.data = data
        self.saved = []

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.saved.append(data)
        self.data = data


class TestTracker:
    def _tracker(self, data=None):
        return THZFaultTracker(FakeStore(data))

    def test_first_run_baselines_existing_history_without_alarm(self):
        tracker = self._tracker()
        state = tracker.process(_payload(R3, R5))
        assert state["status"] == STATUS_OK and state["new_count"] == 0
        assert state["fault_count"] == 2 and tracker.dirty

    def test_state_lists_newest_first_and_latest_is_newest(self):
        state = self._tracker().process(_payload(R3, R5))
        assert [e["fault_number"] for e in state["entries"]] == [5, 3]
        assert state["latest"]["fault_number"] == 5

    def test_new_record_after_baseline_raises_fault_status(self):
        tracker = self._tracker()
        tracker.process(_payload(R3))
        state = tracker.process(_payload(R3, R11))
        assert state["status"] == STATUS_FAULT
        assert state["new_count"] == 1
        assert state["new_entries"][0]["fault_number"] == 11

    def test_acknowledge_clears_the_alarm_and_reports_pending(self):
        tracker = self._tracker()
        tracker.process(_payload(R3))
        tracker.process(_payload(R3, R11))
        assert tracker.acknowledge() == 1
        assert tracker.state["status"] == STATUS_OK
        # the same payload again stays acknowledged
        assert tracker.process(_payload(R3, R11))["new_count"] == 0

    def test_only_records_after_the_acknowledgement_are_new(self):
        tracker = self._tracker()
        tracker.process(_payload(R3))
        tracker.acknowledge()
        state = tracker.process(_payload(R3, R5, R11))
        assert state["new_count"] == 2

    def test_device_side_clear_resets_the_baseline(self):
        tracker = self._tracker()
        tracker.process(_payload(R3, R5))
        state = tracker.process(_payload())
        assert state["fault_count"] == 0 and state["status"] == STATUS_OK
        assert tracker.process(_payload(R3))["new_count"] == 1

    def test_unusable_payload_makes_state_unavailable_but_keeps_baseline(self):
        tracker = self._tracker()
        tracker.process(_payload(R3))
        assert tracker.process(b"\x00") is None
        assert tracker.process(None) is None
        assert tracker.process(_payload(R3))["new_count"] == 0

    def test_process_is_idempotent_for_an_unchanged_payload(self):
        tracker = self._tracker()
        first = tracker.process(_payload(R3))
        assert tracker.process(_payload(R3)) is first

    def test_acknowledge_without_data_raises(self):
        with pytest.raises(RuntimeError):
            self._tracker().acknowledge()

    @pytest.mark.asyncio
    async def test_baseline_survives_a_restart(self):
        store = FakeStore()
        first = THZFaultTracker(store)
        first.process(_payload(R3))
        await first.async_save()
        assert store.saved

        second = THZFaultTracker(store)
        await second.async_load()
        state = second.process(_payload(R3, R5))
        assert state["new_count"] == 1  # only R5 is new after the reload

    @pytest.mark.asyncio
    async def test_save_only_writes_when_dirty(self):
        store = FakeStore()
        tracker = THZFaultTracker(store)
        await tracker.async_save()
        assert store.saved == []

    @pytest.mark.asyncio
    async def test_corrupt_store_content_is_ignored(self):
        tracker = THZFaultTracker(FakeStore({"acknowledged_records": "nope"}))
        await tracker.async_load()
        assert tracker.process(_payload(R3))["new_count"] == 0  # fresh baseline


def _device(*payloads, write_error=None):
    """Device whose D1 reads return the given payloads in order."""
    device = MagicMock()
    device.read_block = MagicMock()
    device.write_value = MagicMock()
    reads = list(payloads)
    calls = []

    async def execute(hass, func, *args):
        calls.append((func, args))
        if func is device.write_value:
            if write_error:
                raise write_error
            return None
        return reads.pop(0) if len(reads) > 1 else reads[0]

    device.async_execute = AsyncMock(side_effect=execute)
    device.calls = calls
    return device


def _writes(device):
    return [c for c in device.calls if c[0] is device.write_value]


class TestReadFaultMemory:
    @pytest.mark.asyncio
    async def test_returns_raw_and_decoded(self):
        result = await read_fault_memory(MagicMock(), _device(_payload(R3)))
        assert result["raw"] == _payload(R3).hex().upper()
        assert result["decoded"]["fault_count_reported"] == 1

    @pytest.mark.asyncio
    async def test_no_data_raises(self):
        with pytest.raises(RuntimeError):
            await read_fault_memory(MagicMock(), _device(None))

    @pytest.mark.asyncio
    async def test_invalid_payload_raises(self):
        with pytest.raises(RuntimeError, match="command echo"):
            await read_fault_memory(MagicMock(), _device(b"\x00\xaa\x00\x00"))


class TestClearFaultMemory:
    @pytest.mark.asyncio
    async def test_empty_memory_is_left_alone(self):
        device = _device(_payload())
        result = await clear_fault_memory(MagicMock(), device)
        assert result == {"cleared": False, "before_count": 0, "after_count": 0}
        assert _writes(device) == []

    @pytest.mark.asyncio
    async def test_success_writes_exactly_once_and_verifies_by_readback(self):
        device = _device(_payload(R3, R5), _payload())
        result = await clear_fault_memory(MagicMock(), device)
        assert result == {"cleared": True, "before_count": 2, "after_count": 0}
        assert _writes(device) == [
            (device.write_value, (FAULT_MEMORY_COMMAND, FAULT_CLEAR_PAYLOAD))
        ]

    @pytest.mark.asyncio
    async def test_still_full_after_clear_is_an_error_without_retrying_the_write(self):
        device = _device(_payload(R3), _payload(R3))
        with pytest.raises(RuntimeError, match="still reports 1"):
            await clear_fault_memory(MagicMock(), device)
        assert len(_writes(device)) == 1

    @pytest.mark.asyncio
    async def test_write_failure_is_reported_and_not_retried(self):
        device = _device(_payload(R3), write_error=OSError("boom"))
        with pytest.raises(RuntimeError, match="may or may not"):
            await clear_fault_memory(MagicMock(), device)
        assert len(_writes(device)) == 1

    @pytest.mark.asyncio
    async def test_pre_read_failure_prevents_any_write(self):
        device = _device(None)
        with pytest.raises(RuntimeError, match="before clearing"):
            await clear_fault_memory(MagicMock(), device)
        assert _writes(device) == []

    @pytest.mark.asyncio
    async def test_unsupported_register_prevents_any_write(self):
        from custom_components.thz.exceptions import THZNotSupportedError

        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=THZNotSupportedError("x"))
        with pytest.raises(RuntimeError, match="not supported"):
            await clear_fault_memory(MagicMock(), device)

    @pytest.mark.asyncio
    async def test_readback_is_retried_but_the_write_is_not(self, monkeypatch):
        async def no_sleep(_):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        state = {"n": 0}
        device = MagicMock()
        writes = []

        async def execute(hass, func, *args):
            if func is device.write_value:
                writes.append(args)
                return None
            state["n"] += 1
            if state["n"] == 1:
                return _payload(R3)  # pre-read
            if state["n"] == 2:
                raise OSError("busy")  # first readback fails
            return _payload()  # second readback succeeds

        device.async_execute = AsyncMock(side_effect=execute)
        result = await clear_fault_memory(MagicMock(), device)
        assert result["cleared"] is True
        assert len(writes) == 1

    @pytest.mark.asyncio
    async def test_unreadable_readback_reports_unknown_result(self, monkeypatch):
        async def no_sleep(_):
            return None

        monkeypatch.setattr("asyncio.sleep", no_sleep)
        state = {"n": 0}
        device = MagicMock()

        async def execute(hass, func, *args):
            if func is device.write_value:
                return None
            state["n"] += 1
            if state["n"] == 1:
                return _payload(R3)
            raise OSError("gone")

        device.async_execute = AsyncMock(side_effect=execute)
        with pytest.raises(RuntimeError, match="result is unknown"):
            await clear_fault_memory(MagicMock(), device)


class TestConstants:
    def test_confirmation_phrase(self):
        assert CLEAR_CONFIRMATION == "CLEAR D1"
