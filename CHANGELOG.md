# Changelog

All notable changes to the THZ integration are documented here.

---

## [Unreleased]

## [0.4.3] – 2026-08-04

### New Features

- **`thz.backup_settings` / `thz.restore_settings` services**: Snapshot all
  writable parameter values to a JSON file and restore them in one call.
  `backup_settings` reads every number, select, switch, time, and schedule
  entity from the device and saves the raw bytes to `thz_backup.json` in the
  HA config directory (path is configurable). Unsupported registers are silently
  skipped. `restore_settings` reads the file and writes each value back using
  the same direct or block read-modify-write path as the entity itself.
  Parameters absent from the current firmware's write map (e.g. after a
  firmware downgrade) are skipped without error. Both services return a
  `{success, count/restored/skipped, errors}` response and accept an optional
  `entry_id` for multi-device setups.

- **Write support for 2xx firmware (206, 214, 214j) via block read-modify-write**:
  2xx devices cannot write individual parameters directly. Instead, the full
  register block must be read, the target bytes modified, and the block written
  back. A new `write_block_value` method on `THZDevice` implements this
  read-modify-write cycle. The register map manager now cross-references the read
  maps at startup to derive the byte offset, length, and scaling factor for each
  writable parameter and stores them in the write-map entry alongside a
  `write_mode="block"` flag. Number entities use this flag to dispatch to the
  correct write path. The `PARENT_BLOCK_MAP` in `write_map_206.py` maps each
  parent group to its block address (e.g. `"p01-p12"` → `"17"`).

  Note: Offsets in the register maps follow the FHEM nibble-position convention.
  They are divided by two when stored in the enriched write entries so that all
  device I/O uses byte addressing consistently.

### Bug Fixes

- **Binary sensor renames** (fixes #117): Three binary sensors have been renamed
  for clarity and consistency with the German HVAC terminology used in the THZ
  device:
  - `dhw_pump` → "Circulation Hot Water" / "Zirkulation Warmwasser"
  - `heating_circuit_pump` → "Circulation Heating" / "Zirkulation Heizung"
  - `pump_hc` → "Circulation Pump" / "Zirkulationspumpe"

  Only translation display names are changed; translation keys and entity IDs
  remain the same.

- **Firmware 509 and 709 (LWZ 304 / LWZ 304 Trend) — dedicated register maps**
  (fixes #113, #115): Both firmware variants run on 5.39-class hardware but do
  not expose four compressor/power blocks (`pxx0A069A` Heating Relative Power,
  `pxx0A069B` Compressor Relative Power, `pxx0A069C` Compressor Speed Unlimited,
  `pxx0A069D` Compressor Speed Limited). Without a dedicated map these variants
  fell through to the 5.39 default, where the first unsupported block aborted the
  coordinator setup loop before energy/COP blocks (`pxx0A09D2`, `pxx0A09D3`) ever
  got coordinators — causing "No coordinator found for block …" warnings and the
  COP sensor failing with "No COP sensors could be created — missing required data".

  Added `readings_map_509` and `readings_map_709`, each filtering the four
  unsupported blocks out of the 5.39 base map. Firmware 509 and 709 now resolve
  to these maps directly; the `PAIRED_BLOCKS` mapping (needed for combined energy
  sensor reads) is re-exported unchanged so COP sensors work correctly.

- **Firmware 709 (LWZ 304 Trend) fails to start due to unsupported registers
  `pxx0A069A`–`pxx0A069D`**: These four blocks (Heating/Compressor Relative Power,
  Compressor Speed Unlimited/Limited) return a `\x01\x04` "not supported" response
  on firmware 709. Previously this propagated as `RuntimeError("Failed to decode
  device response")` → `UpdateFailed` → `ConfigEntryNotReady`, aborting the entire
  integration setup. Fixed by two layers of defence:

  1. `_async_update_block` now catches `THZRegisterNotSupportedError` and returns
     `None` instead of raising `UpdateFailed`. The coordinator treats `None` data as
     a successful (but empty) fetch, so `async_config_entry_first_refresh` completes
     without raising. The block is detected by the existing
     `if coordinator.data is None` check and added to `unsupported_blocks`.

  2. `async_config_entry_first_refresh` is now wrapped in `try/except
     ConfigEntryNotReady` inside the coordinator setup loop. Any block that still
     raises (e.g., a transient decode error that slips through) is marked as
     unsupported and skipped rather than aborting setup. The block is not added to
     `coordinators`, so it is never polled again.

- **Unsupported registers trigger a reconnect on every poll**: When the device
  responds with `\x01\x04` (register not supported by firmware),
  `decode_response` raised `THZRegisterNotSupportedError` inside its `try` block,
  where it was caught by the broad `except Exception` handler, logged as
  "Error decoding response: Register not supported by device firmware", and
  returned `None`. The caller then raised `RuntimeError("Failed to decode device
  response")`, which `send_request`'s `except RuntimeError` handler treated as a
  protocol error and triggered `_reconnect()`. `async_execute`'s
  `except BaseException` path additionally called `_force_close()`.

  Fixed by adding `except THZRegisterNotSupportedError: raise` guards in
  `decode_response`, `send_request`, and `async_execute`. The exception now
  propagates cleanly through the call chain without reconnecting or closing the
  connection. The coordinator wraps it in `UpdateFailed` and skips that poll cycle,
  which is the correct behaviour for a permanent "not supported" condition.

- **`ValueError: argument must be an int, or have a fileno() method` in executor
  thread**: A `call_later` deadline fires `_force_close()` from the event loop
  while an executor thread is blocked inside pyserial's `read()`. pyserial's
  `close()` sets the internal file descriptor to `None`; the pending `select.select`
  call inside `read()` then receives `None` where it expects an `int`, raising
  `ValueError`. The same race can raise `AttributeError` via `fileno()`.

  Fixed by catching `(ValueError, AttributeError)` alongside `OSError` and
  `serial.SerialException` in `_write_bytes` and `_read_available`, and re-raising
  them as `ConnectionError`. This collapses the race-condition exception into the
  normal connection-lost path without any special-case handling.

- **Periodic "Update is taking over 10 seconds" hang (HA 2026.05+)**: All ~60 write
  entities would stall simultaneously because every entity update and service call
  acquired `device.lock` and then blocked indefinitely on an
  `async_add_executor_job` call with no timeout. If the serial port or TCP socket
  stopped responding, the lock was never released, causing every subsequent entity
  update to queue up behind it and all cross the 10-second warning threshold at the
  same time. Reloading the integration was the only recovery.

  Fixed by introducing `async_execute` on `THZDevice`, which acquires the lock and
  wraps every executor call in `asyncio.wait_for` with an 8-second deadline. On
  timeout it calls `_force_close()` **while still holding the lock** (so no other
  coroutine picks up a broken connection) then raises `ConnectionError`. The stuck
  executor thread receives an `OSError` when the port is closed and exits on its
  own. All lock+executor blocks across `__init__.py`, `button.py`, `climate.py`,
  `number.py`, `select.py`, `switch.py`, and `time.py` now use `async_execute`.

- **Integration does not reconnect after connection loss**: Previously,
  `async_execute` only called `_force_close()` (setting `self.ser = None`) on an
  8-second timeout. Protocol-level failures that resolved in under 8 seconds
  (handshake error, read timeout) propagated out of `async_execute` without
  cleanup, leaving `self.ser` pointing at a closed or half-connected socket/serial
  object. On subsequent polls, `_is_connection_alive()` could return inconsistent
  results for this broken state, causing `_reconnect()` to be skipped and the
  connection to never recover without a manual integration reload. Fixed by
  catching all exceptions in `async_execute`, calling `_force_close()` in every
  error path, and re-raising. `self.ser` is now guaranteed to be `None` after any
  failure, so the next poll always starts with a clean `_reconnect()` attempt.

- **CPU spin in `_read_exact` can aggravate USB-CDC adapters**: The 5 ms
  `time.sleep` that was previously removed from `_read_exact` (incorrectly
  flagged as blocking in an async context) has been restored. `_read_exact` runs
  exclusively in executor threads, so sleeping is correct; without it the function
  busy-loops for up to 1 second per call, which can trip USB-CDC adapter firmware
  rate limits and contribute to serial hangs.

- **Coordinators queue indefinitely when all poll simultaneously (thundering herd)**:
  All coordinators share a single `device.lock`. After the first poll period, every
  coordinator fires at approximately the same wall-clock second (because they all
  completed their initial refresh within seconds of each other during setup). With
  15–20 coordinators each requiring 3–8 s of serial I/O, the last ones in the queue
  waited 16–20 s before the lock was available. The 8-second read timeout inside
  `async_execute` did not help because it only applies *after* the lock is acquired.

  Fixed by two changes:

  1. **Lock-acquisition timeout**: `async_execute` now times out after 20 s if the
     lock cannot be acquired. A coordinator that loses the race raises `UpdateFailed`
     and retries at its next scheduled interval rather than blocking for an
     unbounded time.

  2. **Per-coordinator poll jitter**: Each `DataUpdateCoordinator` is created with a
     random jitter of up to 10 % added to its `update_interval` (e.g. 600–660 s for
     a 600 s interval). After the first period the coordinators are naturally spread
     across the jitter window and no longer fire simultaneously.

- **`asyncio.wait_for` does not raise `TimeoutError` for a running executor thread
  (Python ≥ 3.12)**: When `asyncio.wait_for` times out on a future that is already
  running in the thread pool, `Future.cancel()` returns `False` (threads cannot be
  cancelled). In Python ≥ 3.12 `wait_for` then waits for the thread to finish and
  returns its result rather than raising `TimeoutError`, so the 8-second deadline
  was silently bypassed for threads that reconnected and retried successfully (seen
  as "Finished fetching … in 20 s, success: True" in the coordinator logs).

  Fixed by adding a `call_later` deadline alongside `asyncio.wait_for`. The
  `call_later` callback fires unconditionally from the event loop at exactly the
  timeout and calls `_force_close()`, interrupting the thread's blocking I/O
  regardless of Python version. If the thread nevertheless reconnects and succeeds
  past the deadline, the valid data is returned (not discarded) but the reconnected
  connection is immediately force-closed so the next call starts from a clean state.

### Translation Fixes

- **"Schnellentlüftung" → "Schnelllüftung" (binary sensor, German)**: The German
  name for `quick_air_vent` in the binary sensor section incorrectly used
  "Schnellentlüftung" (deaeration / bleeding). The FHEM source calls this signal
  "SchnellLüftung" (ventilation), matching the English "Quick Air Vent". Corrected
  to "Schnelllüftung".

### Improvements

Several Home Assistant Integration Quality Scale gaps have been closed:

- **Action exceptions**: Service handlers now raise `ServiceValidationError` /
  `HomeAssistantError` on failure instead of returning `{success: false}`,
  matching HA's expected service-call contract.
- **Entity unavailable**: Write entities (`number`, `switch`, `select`, `time`)
  now report `available = False` when a register read fails, instead of
  silently keeping a stale value.
- **`ConfigEntry.runtime_data`**: Per-entry state moved off `hass.data` and
  onto the config entry's `runtime_data`, the current HA-recommended pattern.
- **`PARALLEL_UPDATES`**: Declared per platform so HA correctly serializes
  concurrent polls/service calls against each device.
- **Icon translations**: Icons now come from `icons.json` instead of being
  hardcoded per entity.
- **Strict typing**: The integration ships a `py.typed` marker and passes a
  dedicated mypy CI gate (`warn_return_any`, `strict_equality`,
  `check_untyped_defs`, and friends).
- **EntityCategory**: Advanced/technician-mode parameters are now tagged
  `EntityCategory.CONFIG` so they group correctly in the HA UI.
- Removal/uninstallation instructions added to the README.

### Code Quality

- Simplified several duplicated code paths found during an internal read-path
  audit:
  - A shared `_resolve_scan_commands` helper now backs both
    `scan_raw_registers` and `watch_raw_registers_changes`, replacing two
    copies of the same pattern/range validation and expansion logic.
  - A shared `_async_read_register` helper on `THZBaseEntity` replaces
    near-identical `async_update` boilerplate across `number`, `switch`,
    `select`, and `time`.
  - 120 hand-maintained `program*` entries in the entity-translation table
    were replaced with a two-line computed rule (verified by AST analysis
    that every removed entry followed the same `lower()` + `-` → `_` pattern).
  - `THZDevice`'s socket-vs-serial dispatch (`_is_connection_alive`,
    `_write_bytes`, `_read_available`) now branches on the already-set
    `self.connection` field instead of probing `self.ser` with `hasattr()`.
  - Removed an unused `entity_factory` override parameter from
    `async_setup_write_platform`.
- **Extracted `custom_components/thz/services.py`**: The 725-line
  `_async_setup_services` function — all seven `thz.*` service handlers plus
  their shared helpers (scan/range expansion, decode-candidate guessing,
  hex-dump formatting, entry resolution, block-name normalization, and
  `async_refresh_block`) — moved out of `__init__.py` into a dedicated
  module. `__init__.py` shrinks from ~1470 lines to ~420 and now only
  contains config-entry setup/teardown and coordinator wiring; behavior and
  the public `async_refresh_block` re-export are unchanged.
- **Traceback-preserving logging**: 17 `_LOGGER.error()` calls inside
  `except` blocks (mostly in `thz_device.py`) discarded the exception
  traceback because they didn't pass `exc_info`. Switched to
  `_LOGGER.exception()`, which logs at the same level plus the traceback.
- **Line-ending normalization**: Added `.gitattributes` (`* text=auto
  eol=lf`) and normalized all tracked text files to LF; the repo previously
  had an undocumented mix of CRLF and LF depending on when a file was last
  touched.

---

## [0.4.1] – 2026-06-29

### Bug Fixes

- **`NameError: unsupported_blocks` in sensor platform**: The `unsupported_blocks` set
  was stored in `entry_data` by the integration setup but never retrieved in `sensor.py`,
  causing the sensor platform to fail on startup. Fixed by reading it from `entry_data`
  with an empty-set fallback.

- **UTF-8 BOM in `__init__.py`**: A byte-order mark (`EF BB BF`) at the start of the
  file caused `hassfest` to fail with `SyntaxError` on Python 3.14. Windows git with
  `core.autocrlf=true` silently stripped it on checkout so it was invisible locally.
  File committed as plain UTF-8 with LF line endings.

- **Climate platform `KeyError: write_manager`**: `async_setup_entry` in `climate.py`
  was reading `write_manager`, `register_manager`, and `device_id` from the domain-level
  dict instead of from the per-entry dict (`hass.data[DOMAIN][entry_id]`).

---

## [0.4.0] – 2026-06-28

### New Features

- **Compressor/booster runtime hours** (firmware 4.39 / 5.39): Added `sHistory`
  (command `09`) sensors reporting cumulative operating hours in `h` —
  `compressor_runtime_heating`, `compressor_runtime_cooling`, `compressor_runtime_dhw`,
  `booster_runtime_dhw`, and `booster_runtime_heating`.
  ⚠️ **Breaking change for users who already have these sensors**: entity names and
  unique IDs have changed from `*_starts_*` to `*_runtime_*`. Existing history,
  automations, or dashboards referencing the old names will need to be updated.

- **Climate entity — Heating Circuit 2 (HC2)**: A second `climate` entity is now created
  for HC2 when `p01RoomTempDayHC2` is present in the write-register map. It reads the
  setpoint and operating mode from the `pxxF5` coordinator.

- **`thz.refresh_block` service**: Force an immediate re-read of any coordinator block
  from the device without waiting for the next poll interval. Accepts the block name in
  any form (`"FB"`, `"pxxFB"`, `"0xFB"`). Returns `{success, block}`. Also available as
  `async_refresh_block(hass, block, entry_id)` for use by other platforms.

- **`thz.set_diverter_valve` service**: Manual control of the 3-way diverter valve motor.
  Accepts `position: heating | dhw | off`.
  - Both `heating` and `dhw` are guarded by the `diverterValve` bit in `pxxF2` — the
    command is refused if the heat pump is currently pressurising the opposite circuit,
    preventing valve movement against live flow.
  - After activating the motor the service waits 3 seconds then automatically stops it
    (sends `00 00` to both motor commands).
  - The stop is verified by reading back both registers; if either is non-zero the stop
    is retried once and a warning is logged.
  - `off` stops the motor immediately with the same read-back verification.
  - Returns `{success, position, confirmed_off}`.

### Improvements

- **Climate field layouts derived from the register map**: Byte offsets and lengths for
  all climate readings (`roomSetTemp`, `insideTempRC`, `hcOpMode`, `dhwTemp`, etc.) are
  now looked up from the active firmware's merged register map at startup instead of
  being hardcoded. This automatically picks up firmware-specific offsets. If a required
  field is absent the entity is skipped with an error log rather than using a stale
  hardcoded value.

- **Climate writes trigger an immediate coordinator refresh**: Setting temperature, HVAC
  mode, preset, or fan mode now requests a coordinator refresh immediately after the
  write so HA reflects the actual device value without waiting for the next poll.

### Bug Fixes

- **Relative Humidity HC2 mapped as Dew Point** (PR #127): The sensor at nibble 82 in
  the `pxxFB` block was incorrectly labelled `dewPoint` with temperature metadata. It
  carries relative humidity for HC2 (room controller). Renamed to `relHumidityHC2` with
  humidity metadata and `rel_humidity_hc2` translation key (EN + DE).

- **Switches and selects revert in the UI after a few seconds**: Toggling a switch or
  changing a select option updated the internal state but never pushed it to Home
  Assistant (`async_write_ha_state()` was missing), so the UI fell back to the stale
  value until the next poll. The same issue affected number and time entities. All of
  these now write the new state immediately for instant UI feedback.

- **Passive cooling select value always reads as "Unknown"** (#122): Fixed a byte-order
  encoding bug where the `passive_cooling` select type was decoded as big-endian
  (returning value 256 instead of 1). Now uses the same single-byte encoding as
  `2opmode`, matching the actual device protocol.

- **HA 2026.05 hang / serial reconnect on protocol error** (#118): A `RuntimeError`
  from a stale TCP socket (e.g. ser2net) previously raised immediately without
  attempting to reconnect. The integration now tries to reconnect and retry on
  `RuntimeError` the same way it does for `ConnectionError`.

- **Ventilator speed sensors show Hz instead of %** (#106): All ventilator speed sensors
  (`outputVentilatorSpeed`, `inputVentilatorSpeed`, `mainVentilatorSpeed`) now correctly
  report their unit as `%` to match the FHEM source. The `device_class: frequency` has
  been removed. ⚠️ **Breaking change for users with long-term statistics on these
  sensors** — HA may require manually migrating or clearing the old statistics.

### Bug Fixes

- **Switches and selects revert in the UI after a few seconds**: Toggling a switch or
  changing a select option updated the internal state but never pushed it to Home
  Assistant (`async_write_ha_state()` was missing), so the UI fell back to the stale
  value until the next poll. The same issue affected number and time entities. All of
  these now write the new state immediately for instant UI feedback.

- **Passive cooling select value always reads as "Unknown"** (#122): Fixed a byte-order
  encoding bug where the `passive_cooling` select type was decoded as big-endian
  (returning value 256 instead of 1). Now uses the same single-byte encoding as
  `2opmode`, matching the actual device protocol.

- **HA 2026.05 hang / serial reconnect on protocol error** (#118): A `RuntimeError`
  from a stale TCP socket (e.g. ser2net) previously raised immediately without
  attempting to reconnect. The integration now tries to reconnect and retry on
  `RuntimeError` the same way it does for `ConnectionError`.

- **Ventilator speed sensors show Hz instead of %** (#106): All ventilator speed sensors
  (`outputVentilatorSpeed`, `inputVentilatorSpeed`, `mainVentilatorSpeed`) now correctly
  report their unit as `%` to match the FHEM source. The `device_class: frequency` has
  been removed. ⚠️ **Breaking change for users with long-term statistics on these
  sensors** — HA may require manually migrating or clearing the old statistics.

---

## [0.3.0-alpha] – 2026-03-02

> **Alpha release** — tested on firmware 4.39 and 5.39. Please report any regressions
> or unexpected behaviour in the [issue tracker](https://github.com/bigbadoooff/thz/issues).

### New Features

#### Passive Cooling Support (firmware 4.39 / 5.39)
- New **select entity** `p75passiveCooling` for devices running firmware 4.39 or 5.39.
- Supports modes: `off`, `exhaust_air`, `supply_air`, `bypass`, and `sommerkassette`.
- Fully translated in English and German.
- Cooling energy sensor `sCoolHCTotal` (paired-block read) added for firmware 5.39.

#### Diagnostics Support
- The integration now exposes a **Download Diagnostics** option in the Home Assistant UI.
- The diagnostics file includes firmware version, connection type, coordinator status,
  last update timestamps, and redacted hex dumps of all currently-polled register
  blocks.
- Sensitive data (host, device path, serial number) is automatically redacted.

#### COP (Coefficient of Performance) Sensors
- Automatically created for devices with energy-monitoring support (firmware ≥ 4.39).
- Sensors cover **daily**, **monthly**, **yearly**, and **lifetime** COP for DHW,
  heating circuit, and combined total.
- Monthly and yearly sensors reset at the start of each new period and persist
  across Home Assistant restarts.

#### Energy Sensors via Paired-Block Reads (firmware 4.39 / 5.39)
- Heat-output and electricity-consumption sensors are now read using a two-command
  ("paired block") protocol that combines a high-word and a low-word to produce
  accurate 32-bit energy values in Wh.
- Sensors: `sHeatDHWDay`, `sHeatDHWTotal`, `sHeatHCDay`, `sHeatHCTotal`,
  `sElectrDHWDay`, `sElectrDHWTotal`, `sElectrHCDay`, `sElectrHCTotal`,
  `sCoolHCTotal` (5.39 only).

#### `thz.read_raw_register` Service
- New developer/debug service to read any raw register block directly from the
  heat pump.
- Returns results as a service response (usable in automations), a persistent
  notification, and an INFO-level log entry.
- See [docs/read-raw-register-service.md](docs/read-raw-register-service.md) for
  full documentation.

#### Per-Block Configurable Polling Intervals
- Each register block now has its own poll interval, configurable in the
  **Reconfigure** dialog.
- Fast-changing blocks (e.g., temperatures) can be polled frequently while
  slow-changing settings blocks can be polled less often.
- Default interval: 600 seconds.

#### Sensor Metadata in Register Maps
- Register map tuples now support an optional 6th element (a metadata dict)
  providing `unit`, `device_class`, `state_class`, `icon`, and `translation_key`
  inline.
- Module-level helpers (`_TEMP`, `_POWER`, `_ENERGY_TOTAL`, etc.) reduce
  repetition across firmware maps.

#### Smart Entity Visibility
- Advanced, rarely-needed entities are hidden by default to reduce initial clutter:
  - HC2 (heating circuit 2) entities
  - Time programme entities (`programDHW_*`, `programHC1_*`, `programHC2_*`)
  - Technical parameters p13 and above (gradient, hysteresis, integral, etc.)
- Hidden entities remain visible in the entity registry and can be re-enabled
  individually via **Settings → Devices & Services**.
- A one-time migration automatically hides these entities for users upgrading
  from older versions.

### Changes

- **Manifest version bumped to `0.3.0`.**
- `sensor_meta.py` is now a backward-compatibility stub. All sensor metadata lives
  inline in the register-map tuples. Do **not** add new entries to `sensor_meta.py`.
- `decode_value()` in `sensor.py` is now a thin wrapper around the canonical
  `decode_raw_value()` from `value_codec.py`. The `cop_sensor.py` module imports
  `decode_raw_value` directly.
- Write entities no longer use Home Assistant's class-level `SCAN_INTERVAL`
  polling. Instead they register a `async_track_time_interval` timer in
  `async_added_to_hass` (default 600 s) and cancel it in
  `async_will_remove_from_hass`.
- Updated firmware detection: `214j` variant is now recognised separately from
  `214`.
- Register map manager uses a data-driven `FIRMWARE_MAPS` dict; unknown firmware
  versions fall back gracefully to the `default` (5.39-like) configuration.

### Breaking Changes

> If you are upgrading from 0.2.x, read these carefully.

1. **Entity unique_id format has changed.**  
   Sensor unique IDs now follow the pattern `thz_{block}_{offset}_{name}`.  
   Write-entity unique IDs follow `thz_set_{command}_{name}`.  
   Upgrading will re-create any sensor or write entity whose name was previously
   stored under a different unique ID. You may need to update any automations or
   dashboards that reference those entities.

2. **`sensor_meta.py` is a stub.**  
   Any third-party extension that imported `SENSOR_META` from `sensor_meta` to
   add custom metadata must be updated to use the 6th-element dict in the
   register-map tuple instead.

3. **Calendar platform has been removed.**  
   Any existing `calendar.thz_*` entities from previous versions will no
   longer be available. Update or remove any automations, scripts, or
   dashboards that reference these calendar entities.

### Bug Fixes

- Fixed nibble-offset decoding for `length=1` registers at even offsets (FHEM
  compatibility): bit numbers are now shifted by +4 for the HIGH nibble.
- Fixed paired-block energy reads where the high word was incorrectly combined
  as `low*1000 + high` instead of `high*1000 + low`.
- Improved connection-timeout handling: TCP socket is now closed and re-opened
  on timeout rather than accumulating stale data.

---

## [0.2.2] – prior release

See the [0.2.x README note](README.md) for a summary of changes introduced in
the 0.2 series.
