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
  │  read:  coordinator data (read map) or parameter_io (write map)
  │  write: parameter_io only
  ▼
parameter_io.py             the single read/write path for write-map parameters
  ▼
value_codec.py              bytes <-> values (numbers, temperatures, selects, times)
  ▼
thz_device.py               telegrams, escaping, checksum, framing, locking,
  │                         timeouts, reconnects (blocking, runs in the executor)
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
`(name, offset, length, decode_type, factor[, meta])` per block. Sensors,
binary sensors, COP sensors and the climate entities decode their values out
of the block data.

**Write map (parameters).** Settings that can be changed: setpoints, modes,
schedules, the clock. Each entry names a `command`, a `type` (number, select,
switch, time, button) and a decode type. There are two access modes:

- *direct* (4.x/5.x firmware): each parameter is its own register, read and
  written with a single GET or SET.
- *block* (2.x firmware, `write_mode="block"`): the parameter lives at
  `offset`/`length` (and possibly `bit`) inside a block. Writing it is a
  read-modify-write of the whole block. `RegisterMapManagerWrite` derives
  these fields from the firmware's read map
  (`_enrich_2xx_write_entries`).

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
3. Runtime state (`device`, `coordinators`, both map managers, visibility and
   naming settings) is stored as the entry's runtime data, a
   `THZRuntimeData` dataclass (`runtime_data.py`); the platforms take a
   typed `THZConfigEntry`.
4. The platforms create their entities (`platform_setup.py` for the write-map
   platforms):
   - Read-map entities are `CoordinatorEntity`s and decode from
     `coordinator.data`.
   - Write-map entities poll themselves every `write_interval` via
     `THZBaseEntity`. On 2.x, a number whose block is already polled by a
     coordinator takes its value from the coordinator data
     (`parameter_from_block`) instead of reading the device again.
5. After a write, an entity requests a refresh of the coordinator that shows
   the value.

All device I/O goes through `THZDevice.async_execute`. It serialises access
with the device lock, runs the blocking call in the executor with a hard
timeout, and abandons (and disconnects) a call that overruns. That way a hung
line cannot block the lock forever. A SET is never retried once its telegram
has been sent.

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
