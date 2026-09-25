"""Tests for the THZDevice client: handshakes, telegrams, retries, register access.

The client talks to a ScriptedTransport (tests/helpers.py) instead of a
serial port or socket; tests/protocol/test_transport.py covers the real
transports.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.thz import thz_device as device_mod
from custom_components.thz.exceptions import (
    THZConnectionError,
    THZNotSupportedError,
    THZProtocolError,
    THZWriteRejectedError,
)
from custom_components.thz.thz_device import THZDevice
from tests.helpers import ScriptedTransport, device_with_transport, heat_pump_responder

# Answer of the device to an accepted SET (header 01 80, see FHEM THZ_decode).
SET_ACK = b"\x01\x80\x81\x10\x03"


def _get_answer(payload: bytes) -> tuple[bytes, bytes]:
    """Return (frame, decoded) of the device's answer to a GET."""
    crc = THZDevice.thz_checksum(b"\x01\x00\x00" + payload)
    return b"\x01\x00" + crc + payload + b"\x10\x03", crc + payload


def _device(chunks=(), responder=None, **kwargs):
    transport = ScriptedTransport(chunks, responder)
    return device_with_transport(transport, **kwargs), transport


# ---------------------------------------------------------------------------
# Handshakes
# ---------------------------------------------------------------------------


class TestHandshake1:
    @pytest.mark.asyncio
    async def test_success(self):
        device, transport = _device([b"\x10"])
        await device._do_handshake_1()
        assert transport.written == [b"\x02"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("chunks", "received"), [([b"\x99"], "99"), ([], "no data")]
    )
    async def test_wrong_or_missing_byte_raises(self, chunks, received):
        device, _ = _device(chunks)
        with pytest.raises(THZProtocolError, match=f"Handshake 1 failed.*{received}"):
            await device._do_handshake_1()


class TestHandshake2:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "chunks",
        [
            [b"\x10\x02"],
            [b"\x10", b"\x02"],
            # Some devices send only 0x02 (FHEM line 1525).
            [b"\x02"],
        ],
    )
    async def test_success(self, chunks):
        device, _ = _device(chunks)
        await device._do_handshake_2()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("firmware", "waits"), [("206", True), ("439", False)])
    async def test_late_0x02_is_awaited_briefly_on_firmware_2x(self, firmware, waits):
        # 0x10 arrives alone within the read timeout, 0x02 only afterwards.
        device, _ = _device()
        device._firmware_version = firmware
        with (
            patch.object(device, "_read_exact", side_effect=[b"\x10", b"\x02"]),
            patch(
                "custom_components.thz.thz_device.asyncio.sleep", new=AsyncMock()
            ) as sleep,
        ):
            await device._do_handshake_2()
        assert (sleep.await_args_list == [((0.005,),)]) is waits

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reads", "match"),
        [
            ([b"\x10", b"\x99"], "0x10 then 99"),
            ([b"\x10", b""], "0x10 then no data"),
            ([b"\x99\x99"], "received: 9999"),
            ([b""], "received: no data"),
        ],
    )
    async def test_failure_raises(self, reads, match):
        device, _ = _device()
        with (
            patch.object(device, "_read_exact", side_effect=reads),
            pytest.raises(THZProtocolError, match=match),
        ):
            await device._do_handshake_2()


# ---------------------------------------------------------------------------
# Data telegram
# ---------------------------------------------------------------------------


class TestReceiveDataTelegram:
    @pytest.mark.asyncio
    async def test_success_requests_the_data_with_0x10(self):
        frame, _ = _get_answer(b"\xfb\x01\x02")
        device, transport = _device([frame])
        assert await device._receive_data_telegram() == frame
        assert transport.written == [b"\x10"]

    @pytest.mark.asyncio
    async def test_chunks_are_accumulated(self):
        frame, _ = _get_answer(b"\xfb\x01\x02\x03")
        device, _ = _device([frame[:3], frame[3:6], frame[6:]])
        assert await device._receive_data_telegram() == frame

    @pytest.mark.asyncio
    async def test_escaped_0x10_split_across_chunks_is_read_to_the_end(self):
        frame = bytes.fromhex("0100aa1122331010031003")
        # The first chunk ends right after "10 10 03", which is an escaped
        # data byte 0x10 followed by a data byte 0x03, not the terminator.
        device, _ = _device([frame[:9], frame[9:]])
        assert await device._receive_data_telegram() == frame

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chunks", [[], [b"\x01\x00\xaa\x11"]])
    async def test_timeout_or_incomplete_frame_raises(self, chunks):
        device, _ = _device(chunks)
        with pytest.raises(THZProtocolError, match="No valid response"):
            await device._receive_data_telegram()

    @pytest.mark.asyncio
    async def test_nak_ends_the_read(self):
        device, _ = _device([b"\x15"], read_timeout=5.0)
        async with asyncio.timeout(1):
            assert await device._receive_data_telegram() == b"\x15"


# ---------------------------------------------------------------------------
# One exchange
# ---------------------------------------------------------------------------


class TestExchangeOnce:
    @pytest.mark.asyncio
    async def test_get_runs_the_whole_exchange(self):
        frame, _ = _get_answer(b"\xfb\x01\x02")
        device, transport = _device(responder=heat_pump_responder(frame))
        assert await device._exchange_once(b"TELEGRAM", "get", 0, 1) == frame
        assert transport.written == [b"\x02", b"TELEGRAM", b"\x10", b"\x02"]
        # Stale input is dropped before each handshake step.
        assert transport.resets == 2

    @pytest.mark.asyncio
    async def test_dead_connection_is_reopened_once_initialized(self):
        frame, _ = _get_answer(b"\xfb\x01\x02")
        device, transport = _device(responder=heat_pump_responder(frame))
        device._initialized = True
        transport.alive = False
        await device._exchange_once(b"TELEGRAM", "get", 0, 1)
        assert transport.connects == 1

    @pytest.mark.asyncio
    async def test_liveness_is_not_checked_before_initialization(self):
        frame, _ = _get_answer(b"\xfb\x01\x02")
        device, transport = _device(responder=heat_pump_responder(frame))
        transport.alive = False
        await device._exchange_once(b"TELEGRAM", "get", 0, 1)
        assert transport.connects == 0

    @pytest.mark.asyncio
    async def test_set_requires_the_acknowledgement(self):
        device, transport = _device(responder=heat_pump_responder(SET_ACK))
        assert await device._exchange_once(b"TELEGRAM", "set", 0, 1) == b""
        assert transport.written[-1] == b"\x02"

    @pytest.mark.asyncio
    async def test_set_accepts_the_shortest_acknowledgement(self):
        """FHEM reads a SET answer until it ends in 10 03, whatever its length."""
        device, _ = _device(responder=heat_pump_responder(b"\x01\x80\x10\x03"))
        assert await device._exchange_once(b"TELEGRAM", "set", 0, 1) == b""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("answer", "reason"),
        [
            (b"\x15", "NAK"),
            (b"\x01\x01\x02\x10\x03", "timing issue"),
            (b"\x01\x02\x03\x10\x03", "CRC error in request"),
            (b"\x01\x03\x04\x10\x03", "command not known"),
            (b"\x01\x04\x05\x10\x03", "unknown register"),
            (b"\x01\x99\x01\x10\x03", "unknown answer"),
            (b"\x01\x00\x00\x0a\x10\x03", "CRC error in answer"),
        ],
    )
    async def test_set_rejected(self, answer, reason):
        """Only an acknowledging answer accepts a SET, as in FHEM's THZ_decode."""
        device, _ = _device(responder=heat_pump_responder(answer))
        with pytest.raises(THZWriteRejectedError, match=reason):
            await device._exchange_once(b"TELEGRAM", "set", 0, 1)

    @pytest.mark.asyncio
    async def test_get_nak_is_a_protocol_error(self):
        device, _ = _device(responder=heat_pump_responder(b"\x15"))
        with pytest.raises(THZProtocolError, match="NAK"):
            await device._exchange_once(b"TELEGRAM", "get", 0, 1)


# ---------------------------------------------------------------------------
# send_request: retry policy
# ---------------------------------------------------------------------------


class TestSendRequest:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        device, _ = _device()
        with patch.object(device, "_exchange_once", return_value=b"ok") as exchange:
            assert await device.send_request(b"telegram", "get") == b"ok"
        assert exchange.await_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error", [THZConnectionError("dropped"), THZProtocolError("proto")]
    )
    async def test_error_then_success_reconnects_once(self, error):
        device, transport = _device()
        with patch.object(device, "_exchange_once", side_effect=[error, b"ok"]):
            assert await device.send_request(b"telegram", "get") == b"ok"
        assert transport.connects == 1

    @pytest.mark.asyncio
    async def test_connection_errors_exhaust_the_retry(self):
        device, _ = _device()
        errors = [THZConnectionError("a"), THZConnectionError("b")]
        with (
            patch.object(device, "_exchange_once", side_effect=errors),
            pytest.raises(THZConnectionError, match="Connection failed after 2"),
        ):
            await device.send_request(b"telegram", "get")

    @pytest.mark.asyncio
    async def test_protocol_errors_exhaust_the_retry(self):
        device, _ = _device()
        errors = [THZProtocolError("first"), THZProtocolError("second")]
        with (
            patch.object(device, "_exchange_once", side_effect=errors),
            pytest.raises(THZProtocolError, match="second"),
        ):
            await device.send_request(b"telegram", "get")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "raised", "match"),
        [
            (THZConnectionError("a"), THZConnectionError, "Connection failed after 1"),
            (THZProtocolError("proto"), THZProtocolError, "proto"),
        ],
    )
    async def test_failed_reconnect_ends_the_request(self, error, raised, match):
        device, _ = _device()
        with (
            patch.object(device, "_exchange_once", side_effect=[error]),
            patch.object(
                device, "_reconnect", side_effect=THZConnectionError("no port")
            ),
            pytest.raises(raised, match=match),
        ):
            await device.send_request(b"telegram", "get")

    @pytest.mark.asyncio
    async def test_not_supported_is_neither_retried_nor_reconnected(self):
        device, transport = _device()
        with (
            patch.object(
                device, "_exchange_once", side_effect=THZNotSupportedError("no")
            ) as exchange,
            pytest.raises(THZNotSupportedError),
        ):
            await device.send_request(b"telegram", "get")
        assert exchange.await_count == 1
        assert transport.connects == 0


class TestSetIsNotRepeatedOnceSent:
    """A SET that already went out is never sent a second time (#180)."""

    @staticmethod
    def _telegram_writes(transport):
        return [data for data in transport.written if data == b"TELEGRAM"]

    @pytest.mark.asyncio
    async def test_set_failing_after_telegram_is_not_repeated(self):
        # Handshake 1 succeeds, then the device never answers the telegram.
        device, transport = _device([b"\x10"])
        with pytest.raises(THZProtocolError, match="Handshake 2"):
            await device.send_request(b"TELEGRAM", "set")
        assert len(self._telegram_writes(transport)) == 1
        assert transport.connects == 0

    @pytest.mark.asyncio
    async def test_rejected_set_is_not_repeated(self, caplog):
        device, transport = _device(responder=heat_pump_responder(b"\x15"))
        with pytest.raises(THZWriteRejectedError):
            await device.send_request(b"TELEGRAM", "set")
        assert len(self._telegram_writes(transport)) == 1
        assert transport.connects == 0
        # A rejection is a clear answer, not a SET of unknown outcome.
        assert "may or may not have applied" not in caplog.text

    @pytest.mark.asyncio
    async def test_set_failing_before_telegram_is_retried(self):
        device, transport = _device(responder=heat_pump_responder(SET_ACK))
        handshake = AsyncMock(side_effect=[THZConnectionError("down"), None])
        with patch.object(device, "_do_handshake_1", handshake):
            assert await device.send_request(b"TELEGRAM", "set") == b""
        assert len(self._telegram_writes(transport)) == 1

    @pytest.mark.asyncio
    async def test_get_is_still_retried_after_telegram(self):
        frame, _ = _get_answer(b"\xfb\x01\x02")
        device, transport = _device(responder=heat_pump_responder(frame))
        original = device._do_handshake_2
        handshake = AsyncMock(side_effect=[THZProtocolError("no ack"), None])

        async def second_attempt_real():
            await handshake()
            await original()

        with patch.object(device, "_do_handshake_2", second_attempt_real):
            assert await device.send_request(b"TELEGRAM", "get") == frame
        assert len(self._telegram_writes(transport)) == 2


# ---------------------------------------------------------------------------
# Register access
# ---------------------------------------------------------------------------


class TestRegisterAccess:
    @pytest.mark.asyncio
    async def test_get_round_trip(self):
        frame, decoded = _get_answer(b"\xfb\x00\xc8\x05")
        device, transport = _device(responder=heat_pump_responder(frame))
        assert await device.read_write_register(b"\xfb", "get") == decoded
        assert transport.written[1].startswith(b"\x01\x00")

    @pytest.mark.asyncio
    async def test_undecodable_answer_raises(self):
        device, _ = _device()
        with (
            patch.object(device, "send_request", return_value=b"raw"),
            patch.object(device, "decode_response", return_value=None),
            pytest.raises(THZProtocolError, match="Failed to decode"),
        ):
            await device.read_write_register(b"\xfb", "get")

    @pytest.mark.asyncio
    async def test_set_round_trip(self):
        device, transport = _device(responder=heat_pump_responder(SET_ACK))
        assert await device.write_value(b"\xfb", b"\x01\x02") is None
        assert transport.written[1].startswith(b"\x01\x80")

    @pytest.mark.asyncio
    async def test_set_nak_is_reported_without_waiting_for_the_timeout(self):
        device, _ = _device(responder=heat_pump_responder(b"\x15"), read_timeout=5.0)
        async with asyncio.timeout(1):
            with pytest.raises(THZWriteRejectedError, match="NAK"):
                await device.write_value(b"\xfb", b"\x01\x02")

    @pytest.mark.asyncio
    async def test_read_value_slices_the_response(self):
        device, _ = _device()
        with patch.object(
            device, "read_write_register", return_value=b"\x00\x01\x02\x03\x04"
        ) as rw:
            assert await device.read_value(b"\xfb", "get", 2, 2) == b"\x02\x03"
        rw.assert_awaited_once_with(b"\xfb", "get")

    @pytest.mark.asyncio
    async def test_read_block_delegates(self):
        device, _ = _device()
        with patch.object(device, "read_write_register", return_value=b"block") as rw:
            assert await device.read_block(b"\x0a\x06\x48", "get") == b"block"
        rw.assert_awaited_once_with(b"\x0a\x06\x48", "get")


class TestReadFirmwareVersion:
    @pytest.mark.asyncio
    async def test_success(self):
        device, _ = _device()
        with patch.object(device, "read_value", return_value=b"\x00\xce"):
            assert await device.read_firmware_version() == "206"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "outcome",
        [
            {"return_value": None},
            {"side_effect": OSError("io")},
            {"side_effect": THZProtocolError("proto")},
            {"side_effect": THZConnectionError("gone")},
        ],
    )
    async def test_failure_returns_empty(self, outcome):
        device, _ = _device()
        with patch.object(device, "read_value", **outcome):
            assert await device.read_firmware_version() == ""


class TestAvailableReadingBlocks:
    def test_empty_without_register_map(self):
        device, _ = _device()
        assert device.available_reading_blocks == []

    def test_lists_the_register_map_blocks(self):
        device, _ = _device()
        device.register_map_manager = MagicMock()
        device.register_map_manager.get_all_registers.return_value = {"a": 1, "b": 2}
        assert sorted(device.available_reading_blocks) == ["a", "b"]


# ---------------------------------------------------------------------------
# async_initialize
# ---------------------------------------------------------------------------


class TestAsyncInitialize:
    @pytest.mark.asyncio
    async def test_unknown_connection_raises(self):
        device, _ = _device(connection="bogus")
        with pytest.raises(ValueError, match="Unknown connection type"):
            await device.async_initialize()

    @pytest.mark.asyncio
    async def test_low_firmware_skips_the_cooling_probe(self):
        device, transport = _device()
        with (
            patch.object(device, "read_firmware_version", return_value="206"),
            patch.object(device, "_probe_cooling_support") as probe,
        ):
            await device.async_initialize()

        assert transport.connects == 1
        probe.assert_not_awaited()
        assert device._initialized is True
        assert device.firmware_version == "206"
        assert device.register_map_manager is not None
        assert device.write_register_map_manager is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("has_cooling", [True, False])
    async def test_high_firmware_probes_cooling(self, has_cooling):
        device, _ = _device()
        with (
            patch.object(device, "read_firmware_version", return_value="539"),
            patch.object(
                device, "_probe_cooling_support", return_value=has_cooling
            ) as probe,
        ):
            await device.async_initialize()
        probe.assert_awaited_once()
        assert device.has_cooling is has_cooling

    @pytest.mark.asyncio
    async def test_override_selects_the_maps_but_keeps_the_reported_version(self):
        device, _ = _device(firmware_override="539")
        with (
            patch.object(device, "read_firmware_version", return_value="439"),
            patch.object(device, "_probe_cooling_support", return_value=True) as probe,
        ):
            await device.async_initialize()
        probe.assert_awaited_once()
        assert device.firmware_version == "439"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("firmware", [None, ""])
    async def test_unread_firmware_raises_and_closes(self, firmware):
        # read_firmware_version() returns "" on failure; that must not fall
        # through to the 4.39 default profile.
        device, transport = _device()
        with (
            patch.object(device, "read_firmware_version", return_value=firmware),
            pytest.raises(THZConnectionError, match="could not be read"),
        ):
            await device.async_initialize()

        assert transport.closes == 1
        assert device.register_map_manager is None

    @pytest.mark.asyncio
    async def test_failed_connect_propagates(self):
        device, transport = _device()
        with (
            patch.object(
                transport, "connect", side_effect=THZConnectionError("refused")
            ),
            pytest.raises(THZConnectionError, match="refused"),
        ):
            await device.async_initialize()
        assert transport.closes == 1
        # Setup reports it; no "heat pump does not answer" before first contact.
        assert device.link_ok is True

    @pytest.mark.asyncio
    async def test_runs_under_the_device_lock(self):
        device, _ = _device()
        held = []

        async def firmware():
            held.append(device.lock.locked())
            return "439"

        with patch.object(device, "read_firmware_version", side_effect=firmware):
            await device.async_initialize()
        assert held == [True]
        assert not device.lock.locked()

    @pytest.mark.asyncio
    async def test_hung_initialization_times_out_and_closes(self, monkeypatch):
        monkeypatch.setattr(device_mod, "_INITIALIZE_TIMEOUT", 0.01)
        device, transport = _device()

        async def hang():
            await asyncio.sleep(1)

        with (
            patch.object(device, "read_firmware_version", side_effect=hang),
            pytest.raises(THZConnectionError, match="timed out"),
        ):
            await device.async_initialize()
        assert transport.closes == 1
        assert device.link_ok is True


class TestClose:
    def test_close_closes_the_transport(self):
        device, transport = _device()
        device.close()
        device.close()
        assert transport.closes == 2

    @pytest.mark.asyncio
    async def test_running_call_does_not_reconnect_after_close(self):
        """A refresh in flight during unload must not reopen the connection."""
        device, transport = _device()
        device._initialized = True
        started = asyncio.Event()

        async def exchange(*args):
            started.set()
            await asyncio.sleep(0.01)
            raise THZConnectionError("closed under us")

        with patch.object(device, "_exchange_once", side_effect=exchange):
            task = asyncio.create_task(device.send_request(b"telegram", "get"))
            await started.wait()
            device.close()
            with pytest.raises(THZConnectionError):
                await task
        assert transport.connects == 0

    @pytest.mark.asyncio
    async def test_initialize_after_close_connects_again(self):
        device, transport = _device()
        device.close()
        with patch.object(device, "read_firmware_version", return_value="439"):
            await device.async_initialize()
        assert transport.connects == 1
