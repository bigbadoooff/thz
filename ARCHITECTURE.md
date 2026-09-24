# Architecture

How the THZ integration is put together: which layer owns what, and how a
value gets from the heat pump into Home Assistant and back. For how to work on
the code, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Layers

```
Home Assistant
  │  config entries, entity registry, services, diagnostics
  ▼
Integration setup           __init__.py, config_flow.py, platform_setup.py
  │  one config entry = one heat pump = one THZDevice
  ▼
Entities                    sensor, binary_sensor, cop_sensor, fault_sensor,
  │                         climate, number, select, switch, time, button
  │  read:  coordinator data (read map and 2.x blocks) or
  │         parameter_poller.py (write map)
  │  write: parameter_io only
  ▼
parameter_io.py             the single read/write path for write-map parameters
  ▼
value_codec.py              bytes <-> values (numbers, temperatures, selects, times)
  ▼
thz_device.py               client: lock, timeouts, retry policy,
  │                         handshakes, register access (asyncio)
  ├─ protocol.py            pure: telegrams, checksum, escaping, framing,
  │                         judging the device's answers (FHEM THZ_decode)
  ▼
transport.py                SerialTransport / TcpTransport: move bytes only
  │                         (asyncio; pyserial-asyncio-fast for the port)
  ▼
Serial port or ser2net TCP socket
```

`register_maps/` sits beside this stack. `RegisterMapManager` (read map) and
`RegisterMapManagerWrite` (write map) pick and merge the map modules for the
detected firmware (`FIRMWARE_MAPS` in `register_map_manager.py`). Every layer
above gets its offsets, lengths, decode types and metadata from them. No other
module hard-codes register layouts.

## Two kinds of registers

**Read map (blocks).** The device answers a block request (`pxxFB`, `pxxF4`,
...) with a fixed layout of many values. The read map lists them as
`(name, offset, length, decode_type, factor[, meta])` per block, with offset
and length in nibbles as in FHEM. `RegisterMapManager` turns each entry into
a `ReadField` (`register_maps/model.py`) once: byte offset and length, the
nibble half of a one-nibble value, and a flag's bit within its byte (a flag
in the high nibble is four bits up). Sensors, binary sensors, COP sensors,
the climate entities and the 2.x write layouts all use these positions
(`fields()`, `find_field()`); no other module converts nibbles.
`tests/register_maps/test_map_schema.py` checks the maps of every firmware
profile: known decode types, fields after the block header, one-nibble
flags, unique names, existing translations and sane write bounds.

**Write map (parameters).** Settings that can be changed: setpoints, modes,
schedules, the clock. Each entry names a `command`, a `type` (number, select,
switch, time, button) and a decode type. `RegisterMapManagerWrite` turns each
entry into a `WriteParam` (`register_maps/model.py`, via `params()` /
`param(name)`); entities, climate, clock sync and backup/restore use these
typed parameters, not the map dicts. There are two access modes:

- *direct* (4.x/5.x firmware): each parameter is its own register, read and
  written with a single GET or SET.
- *block* (2.x firmware, `WriteParam.block`): the parameter lives at the
  layout's offset/length (and possibly bit) inside a block. Writing it is a
  read-modify-write of the whole block. `RegisterMapManagerWrite` derives
  the layout from the firmware's read map (`_enrich_2xx_write_entries`).

`parameter_io.py` hides the difference. Anything that reads or writes a
write-map entry calls `async_read_parameter` / `async_write_parameter`. That
includes entities, climate, clock sync and backup/restore.

## Polling: poll → coordinator → entity

1. `async_setup_entry` creates the `THZDevice`, connects, reads the firmware
   version and loads the register maps (`THZDevice.async_initialize`).
2. It creates one `DataUpdateCoordinator` per configured block, keyed by
   block name (`"pxxFB"`), each with its own interval plus jitter. Its update
   method, `_async_update_block`, reads the block through the device.
   - A block the firmware does not have yields `data=None`, and no entities
     are created for it.
   - A block that fails transiently keeps its coordinator, and its entities
     start unavailable.
   - If every block fails, setup raises `ConfigEntryNotReady`.
3. It creates the `ParameterPoller` (`parameter_poller.py`), which polls the
   write-map registers every `write_interval`.
4. Runtime state (`device`, `coordinators`, `poller`, both map managers,
   visibility and naming settings) is stored as the entry's runtime data, a
   `THZRuntimeData` dataclass (`runtime_data.py`); the platforms take a
   typed `THZConfigEntry`.
5. The platforms create their entities (`platform_setup.py` for the write-map
   platforms):
   - Read-map entities are `CoordinatorEntity`s and decode from
     `coordinator.data`.
   - Write-map entities (number, select, switch, time) do not poll
     themselves. A 2.x parameter whose block is polled by a coordinator
     listens to it and cuts its value out of the block
     (`parameter_from_block`). Every other one subscribes its read key
     `(command, offset, length)` at the poller while it is added to Home
     Assistant (`THZBaseEntity.async_added_to_hass`).
   - The poller reads each subscribed key once per round, one after the
     other, and hands the bytes to the key's entities. Entities sharing a
     key (a schedule's start and end) cost one read; disabled entities
     none. New keys are read in one batch shortly after they are
     subscribed, so entities are added without a read of their own.
     Several connection errors in a row end a round and mark the rest
     unavailable.
   - `homeassistant.update_entity` still reads an entity's register
     directly (`async_update`).
6. After a write, an entity requests a refresh of the block coordinator
   that shows the value, or drops the poller's last result for its key.

All device I/O runs on the event loop and goes through
`THZDevice.async_execute`. It serialises access with the device lock and
bounds each call with a hard timeout. A call that overruns is cancelled and
the connection closed, so a hung line cannot block the lock forever. A SET is
never retried once its telegram has been sent.

## The protocol

A request is `01 00` (GET) or `01 80` (SET), then a checksum byte, then the
command and data, then `10 03`.

- The checksum is the sum of all bytes except the checksum position, mod 256.
- `0x10` is escaped as `10 10` and `0x2B` as `2B 18`.
- A frame ends at a `03` preceded by an odd number of `10` bytes.
- The device answers a SET too: `01 80` acknowledges it; NAK (`15`) and the
  error headers `01 01`..`01 04` reject it (`THZWriteRejectedError`), as in
  FHEM's `THZ_decode`. A SET is never repeated once it was sent.

Errors of the device layer are `THZError` subclasses (`exceptions.py`):
`THZConnectionError`, `THZProtocolError` (with `THZNotSupportedError` and
`THZWriteRejectedError`) and `THZNotInitializedError`. Callers catch
`DEVICE_ERRORS` and translate once: into `UpdateFailed` in the block
coordinators, into `HomeAssistantError` in services and entity actions.

The format is the one used by FHEM's `00_THZ.pm`, which is known to work on
real devices. `tests/protocol/test_fhem_reference.py` runs that module
unmodified against our encoder. The register maps here are more current than
FHEM's tables, so FHEM is used only as a protocol reference, never for map
contents.

## Other parts

| Module | Role |
|---|---|
| `config_flow.py` | Setup (IP or USB, block and write-group selection) and reconfigure |
| `services/` | `thz.*` services, registered once in `async_setup`: `raw` (register access, block refresh), `diverter`, `backup` (backup/restore), `faults` |
| `fault_memory.py`, `fault_state.py`, `fault_sensor.py` | D1 fault memory: decoding, acknowledgement, sensors |
| `clock_sync.py` | Periodic clock-drift check and optional correction |
| `cop_sensor.py` | COP computed from energy and power registers |
| `entity_translations.py`, `entity_id_style.py`, `const.py` | Translation keys, FHEM-style entity_ids, visibility tiers |
| `devices.py` | Device info for all entities; optional split into functional sub-devices (by unique_id patterns) and cleanup of sub-devices |
| `diagnostics.py` | Redacted diagnostics dump |
| `notify.py` | Persistent notifications |

## Tests

- `tests/` runs against stubbed Home Assistant modules and covers the code
  branch by branch.
- `tests_ha/` runs the integration inside a real Home Assistant with only the
  line simulated. It includes a per-firmware snapshot of the created entities.

Both are described in [tests/README.md](tests/README.md).
