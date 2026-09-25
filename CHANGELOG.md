# Changelog

All notable changes to the THZ integration are documented here.

---

## [Unreleased]

### Added

- **Strict typing:** mypy checks the whole integration in strict mode.
- **Documentation:** use cases and example automations
  (`docs/automations.md`: fault notification, filter reminder, hot water
  from PV surplus, ventilation boost, weekly backup), and README sections on
  how data is updated and on known limitations.
- **Event entities for a new fault and a filter change.** "Fault" fires
  `fault` for every record that appears in the fault memory, with its code,
  name, time and date; "Filter change" fires `filter_both`, `filter_up` or
  `filter_down` when the heat pump starts asking for that filter change.
  Both read data that is polled anyway.
- **Repair issue for a drifted device clock.** Without automatic clock
  sync, a heat pump clock that is off by more than a minute raises a repair
  issue instead of a daily persistent notification. Its fix sets the clock
  to Home Assistant's time and can turn on automatic sync; the issue goes
  away by itself once the clock is right again.

### Breaking changes

- **Hot water is a `water_heater` entity** instead of a climate entity.
  The old `climate` hot water entity is removed from the entity registry on
  update; automations and dashboards that used it need the new
  `water_heater` entity. Its state is `performance` (day setpoint),
  `eco` (setback, night setpoint) or `off` (standby); setting a temperature
  writes the setpoint of the current state (`p04` or `p05`), or the
  manual setpoint (`p11`) when that is the one in effect.
- **Ventilation is a `fan` entity** and the heating
  circuit climate entity no longer has a fan mode, which wrote the day
  stage of the program (`p07FanStageDay`). The fan starts *unscheduled
  ventilation* (`p99startUnschedVent`): a speed starts it at stage 1-3,
  off at stage 0, for the time set in `p43`-`p46`. It shows the stage the
  ventilation runs at, from the supply airflow (`pxxE8`) or else from the
  fan time program. On 2.x firmware the fan only shows the stage (set at
  the device, or of the fan program state).

### Changed

- **A garbled answer is asked for once more.** A read whose answer fails
  its checksum or reports a timing issue is repeated once before it counts
  as failed; the single bad answer is logged at debug level instead of as
  an error.
- **Errors that are not device errors are no longer swallowed** by the raw
  register services, the backup and the clock check; they show up in the
  log with a traceback instead of being hidden (the clock check logged them
  only at debug level).
- **Much quieter log.** A normal start logs one line instead of about 40.
  A lost connection is logged once as a warning and once as info when it
  is back, instead of per request and per block. Problems that recur on
  every poll (short or undecodable sensor data, unknown select values, a
  drifted clock) are logged once. Details moved to the debug level; see
  "Logging" in the README.
- **A setting that reads again is logged.** When a single setting failed to
  read while the heat pump answered (logged as a warning), its next
  successful read is logged at info.
- **The old `log_level` setting is removed.** Entries from old versions
  fixed the integration's log level with it, overriding Home Assistant's
  `logger:` configuration; they are migrated to version 1.3 without it.

- **Error messages are translated.** Errors from the services, the button
  and the setup ("will retry") come from the integration's translations
  (English and German) instead of fixed English text.

- **Settings are polled by one poller per heat pump** (#185): number,
  select, switch and time entities no longer run a timer each. The poller
  reads every register once per `write_interval`, one after the other; a
  register shown by several entities (a schedule's start and end) is read
  once, and disabled entities are not read at all. At startup the entities
  are added first and read in one batch right after, instead of each one
  reading the device before it is added. When the heat pump stops
  answering, a round ends after a few failed reads and the entities become
  unavailable, instead of every entity waiting for its own timeout. 2.x
  switches, selects and times inside a polled block now take their value
  from the block, like 2.x numbers already did.

- **The connection runs on asyncio** (#185): serial port and ser2net TCP
  no longer use a worker thread per request. The serial port is opened with
  `pyserial-asyncio-fast`, a new requirement that Home Assistant installs
  automatically. A request that exceeds its timeout is cancelled cleanly
  instead of being left running in the background.

- **A write the heat pump rejects is reported as an error.** The answer to a
  SET is now read and checked like FHEM does: only an acknowledgement
  (`01 80`) counts as success; NAK and the device's error answers (timing,
  CRC error, unknown command, unknown register) fail the write with a
  message instead of passing silently.

- **Services are registered when Home Assistant starts** instead of with
  the first config entry, and they stay registered after the last entry is
  removed. A call without a loaded THZ entry now fails with a validation
  error ("No THZ device is loaded").
- **Reconfigure keeps the entry's unique id current** (#179): changing the
  host or serial device updates it, and a host or device that another THZ
  entry already uses is refused.

### Added

- **Party end time** (4.x/5.x, #185): the party register holds the start
  and the end of the party; besides the start (now named *Party Start*) a
  new *Party End* time entity shows and sets the end. Setting 00:00 as the
  end means 24:00, as for the schedules. Writes match FHEM's
  `set party-time HH:MM--HH:MM` byte for byte.

- **Optional sub-devices** (#186): a new setting, *Split into sub-devices*,
  groups the entities into sub-devices linked to the heat pump:
  - heating circuit 1,
  - heating circuit 2,
  - hot water,
  - ventilation,
  - compressor,
  - solar,
  - cooling.

  New setups have it on. Existing setups keep the single device until it is
  switched on via Configure. Entity IDs stay the same, but displayed names
  change, and automations that pick a device must be updated.

### Bug Fixes

- **2.x settings could stay unavailable for good** when their block failed
  to read at startup and later turned out to be one the firmware does not
  have. They now fall back to being read on their own.
- **A setup that failed late kept the connection open.** When setting up
  the platforms failed after the heat pump was connected, the serial port
  or ser2net connection and the clock check stayed active; ser2net often
  allows one client only, so the retry could not connect. Both now stop
  however setup ends.
- **A backup from another firmware was restored without a question.**
  Parameters are matched by name, and the same name can have another range
  or meaning on another firmware. `thz.restore_parameters` now refuses such
  a backup unless `allow_other_firmware` is set; a dry run shows it
  (`firmware_matches`, `backup_firmware`).
- **Writing a time could overwrite the time next to it.** Schedule start
  and end times and the party start and end share a register; a write read
  it and wrote it back in two separate steps, and an empty answer made it
  write zeros into the other time. The read and the write now happen in one
  step, a short answer writes nothing, and schedules are written as start
  and end, like FHEM does. Restoring a backup keeps the other time of the
  party register, too.
- **A heating circuit in standby reported the mode `off`,** which it does
  not offer (only heat and cool). It now stays `heat` and shows the
  standby as the action `off`.
- **Connecting at startup had no time limit.** Reading the firmware and
  probing for cooling now run under the device lock with a 30 second
  limit, like every other device call, so a line that hangs cannot stall
  setup.
- **Adding a heat pump that is already set up opened its port first.**
  The flow connected and read the firmware before it noticed the
  duplicate; on a serial port that talked next to the running
  integration. It now refuses the duplicate before connecting.
- **The climate preset and cooling setpoint went stale.** They were read
  once at startup, so a mode changed at the heat pump, through the
  operating-mode select or through the other heating circuit did not show
  until Home Assistant restarted. Both are now polled with the other
  settings and read again right after any entity writes them.
- **A failed write looked like a success.** Setting a number, select,
  switch, time, climate, hot water or fan entity while the heat pump did not
  answer only logged an error; the action succeeded and the frontend showed
  the new value. The action now fails with an error message, and the entity
  keeps its value.
- **A second heat pump got almost no entities.** Sensors, binary sensors,
  numbers, selects, switches, buttons and schedule times had unique IDs made
  of the register alone, so Home Assistant dropped the second heat pump's
  entities as duplicates. Every unique ID now contains the heat pump's
  identifier; existing entities are migrated on update and keep their
  entity IDs and history.
- **The party-time sensor showed a meaningless number of minutes** (4.x/5.x,
  #185): the register holds the party start and end as quarter hours, and
  the sensor now shows them as FHEM does, e.g. `07:00--22:30`. It is no
  longer a duration in minutes, so its unit and long-term statistics go
  away. (The block is off by default; the *Party Start* and *Party End*
  time entities show and set the same values.)

- **Heating curve gradients are read unsigned, as FHEM does** (#185): the
  `6gradient` parameters (p13/p16 gradient HC1/HC2) were decoded as signed
  values, so a raw value from 0x8000 up showed as negative. Real gradients
  stay far below that; the change makes the reading match FHEM's.

- **Leftover placeholder sensors on 2.06/2.14 are removed** (#176, #185):
  sensors such as *Dew Point*, *P_Nd*/*P_Hd* and *actualPower_\** that
  earlier versions created for fields the firmware does not have stayed in
  the entity registry as "no longer provided". They are now removed when
  the integration starts.

- **The diverter valve check used polled data** (#185): `thz.set_diverter_valve`
  decided from the `diverterValve` bit of the last `pxxF2` poll, which can be
  one poll interval old. The block is now read right before the check, and
  the move is refused if that read fails.

- **Changing the host or serial device kept the entities but not the
  device** (#185): the heat pump's device registry identifier was derived
  from the connection on every start, so after a Reconfigure to a new host
  a second device appeared, and the climate, COP and fault entities (whose
  unique ids contain it) were created anew without their history. The
  identifier is now stored in the entry when it is created; existing
  entries keep the one they are registered under (entry migration to 1.2).

- **Three entities had no name of their own**: the pump settings of the
  technician maps (`zPumpHC`, `zPumpDHW`, numbers) and the 2.14 error reset
  (`ResetErrors`, a button) had their translations only under `select`, so
  Home Assistant showed them as "Heating Circuit 1 Number", "Hot Water
  Number" or just the device name. Existing entity IDs stay as they are.

- **Sensors and selects showed English protocol names instead of translated
  values** (e.g. *Wochentag* reading `Monday`): the weekday, season mode,
  heating/DHW operating mode, program state and fault code sensors (plus the
  new *Latest fault* sensor) are now enum sensors with translated states in
  English and German, and the *Operating mode* and *Control valve DHW*
  selects have translated options. The 2.xx *Last errors* list is translated
  into the configured language when the value is built (restart or reload
  after changing the language). State and option values change to lowercase
  keys (`monday`, `setback`, `daymode`, `f05_outletfanfault`, `none` for "no
  fault"); update automations or templates that compared against the old
  text or call `select.select_option` with the old option names. A value that
  is not in the table reads `unknown`, with the raw bytes in the
  `register_raw` attribute.

## [0.6.0] – 2026-09-19

### Added

- **Write entities for firmware 4.39/5.39** (ported from the m-l fork, found
  with `read_raw_register` on an LWZ 403 SOL): `p20FlowProportionHC2`
  (`0C059D`, mirror of `p19` for heating circuit 2, hidden unless
  `enable_hc2`), `pSolarHysteresis` (`0A058F`) and `pDHWVaporizationDelay`
  (`0A058E`, solar loop delay after a collector stagnation event). The two
  solar parameters count as advanced and are hidden by default.

- **Implausible temperature readings are discarded** (ported from the m-l
  fork): the serial protocol has only a 1-byte checksum, so a corrupted
  frame can decode to e.g. -3276.8 degC and end up in long-term statistics.
  Temperature sensors now report unknown instead when the value is outside
  -50..100 degC (solar collector -50..300, hot gas -50..200, both can
  legitimately exceed 100). The warning is logged once per episode.

- **Heating Circuit 2 climate entity is now created** (ported from the m-l
  fork): `pxxF5` has no `hcOpMode` field on any firmware, and the setup code
  required one, so the HC2 climate entity was never created. It now only
  needs the HC2 target temperature; `hvac_mode` is a fixed HEAT (COOL while
  cooling). Like every other HC2 entity it is disabled by default and
  follows the `enable_hc2` option, including when that option is toggled
  later in Reconfigure.

- **Firmware 4.19 profile (Tecalor THZ 303 SOL)** (ported from the
  Darian6969 fork): `419` is now a known firmware and is selectable in the
  `firmware_override` dropdown. It uses the 4.39 maps, but `pxxFB` is shorter
  on 4.19, so `flowRate`, `p_HCw`, `humidityAirOut` and `insideTemp` are
  disabled instead of logging "payload too short" on every poll. Not verified
  on 4.19 hardware: whether `actualPower_Qc`/`actualPower_Pel` are in kW like
  4.39 (left unscaled), and COP sensors are not offered below firmware 4.39.

- **Fault memory sensors and services for firmware 4.x/5.x** (ported from the
  Darian6969 fork): four sensors (*Fault status*, *Fault memory*, *Latest
  fault*, *New faults*) decode up to ten stored faults from the `pxxD1` block
  and remember, in Home Assistant only, which records you have seen (existing
  history is not an alarm on first run). Built on the existing `pxxD1`
  coordinator, so there is no extra serial traffic. New services
  `thz.probe_fault_memory` (read-only), `thz.acknowledge_faults` (HA side only)
  and `thz.clear_fault_memory`, which clears the device's fault memory with a
  confirmation phrase, one non-retried write and verification by readback.
  The clear service is available on every firmware; the write was verified
  on real hardware on firmware 4.19 only, elsewhere success is decided by the
  readback.

- **More robust device clock sync** (ported from the Darian6969 fork): each
  clock register read is retried up to three times, a correction only writes
  the components that differ, and the result is verified by reading the clock
  back (a mismatch is logged). `auto_sync_clock` stays opt-in.

### Bug Fixes

- **Firmware 4.39: 45 `pxxFB` sensors lost unit, device class, state class,
  icon and name** (issue #164, introduced in 0.5.0): `register_map_439.py`
  re-declared the whole `pxxFB` block without meta dicts, and the merge in
  `RegisterMapManager` replaces base entries by name, so every re-listed
  entry silently lost its metadata (no more long-term statistics, no unit,
  raw register name as friendly name). `_merge_maps` now carries the base
  entry's meta dict over when an override omits it, and
  `register_map_439.py` is reduced to what really differs on 4.39 (the
  three disabled sensors, `dewPoint`, and the power scaling below). A
  regression test asserts no firmware's merged map drops base metadata.

- **Firmware 4.39: `actualPower_Qc` / `actualPower_Pel` off by a factor of
  1000** (issue #165): 4.39 hardware reports these in kW while the map
  declares W (5.39 reports W, so the base map is unchanged). The `esp_mant`
  decoder ignored its `factor` argument; it now divides by it like the other
  decoders, and the 4.39 map uses `0.001` (kW → W). The unit stays W, so
  history recorded before the fix keeps its old (kW-sized) values and will
  show a step to the correct values at the update.

## [0.5.1] – 2026-09-14

### Added

- **Sensors for firmware 2.06/2.14/2.14j ported from the legacy FHEM
  module**: `readings_map_2xx.py`, `readings_map_214.py`, and
  `readings_map_214j.py` were empty stubs, so most sensors for the 200
  firmware series were entirely missing. Added the sensor blocks common to
  all three 2.xx variants (defrost/heating/DHW/solar parameters, operating
  hours, schedules, fan calibration, solar circuit readings, system status,
  time/date), the previously entirely-missing solar-circuit sensor block
  (`sSol`, cmd `16`) for all 2xx firmware, and the firmware-specific `pFan`
  (cmd `01`) block for 214/214j.

### Bug Fixes

- **Firmware 214j read the wrong `sGlobal` register layout**: without a
  firmware-specific override, `pxxFB` (`sGlobal`, cmd `FB`) silently fell
  back to `register_map_all.py`'s generic 4.39-style block, decoding the
  wrong bit positions/offsets for mixer, pump, compressor, and ventilator
  status on real 214j hardware. Added the correct `FBglob214` layout.

### Documentation

- **README**: added a "How Firmware Versions Are Loaded" section
  documenting `RegisterMapManager`'s base/write/read map layering, the
  firmware → module table, and the functional differences between the 2xx
  and 4.39/5.39 firmware families.

## [0.5.0] – 2026-09-10

### Added

- **`enable_hc2` config option**: A separate checkbox for showing Heating Circuit 2
  entities, independent of the `entity_visibility` tier. Previously HC2 entities were
  lumped into the same "advanced" category as technical parameters, so there was no
  way to show advanced parameters without also showing HC2 (or vice versa). HC2 now
  defaults to hidden regardless of tier -- even "All" -- until explicitly enabled.

### Bug Fixes

- **Config flow / Reconfigure dialog mixed German and English**: the
  `entity_id_style`, `entity_visibility`, and `firmware_override` dropdowns
  used a plain `vol.In(dict)` with hardcoded English option text, which
  has no translation hook at all -- their option values (and, for
  `entity_id_style`/`entity_visibility`/`firmware_override`/
  `auto_sync_clock`, their field labels too) always showed in English
  regardless of Home Assistant's language, mixed in with the correctly
  German-translated fields around them. Converted those three fields to
  `SelectSelector` with `translation_key`, and added the missing field
  labels and option translations to `strings.json` and both
  `translations/*.json` files.

- **Firmware 709 used a separate, byte-for-byte duplicate readings map**:
  `readings_map_709.py` excluded the exact same four compressor/power
  blocks as `readings_map_509.py`, just under a different module name.
  Consolidated firmware 709 onto `readings_map_509` and removed the
  duplicate file.

- **Wrong scaling for `p54MinPumpCycles`/`p55MaxPumpCycles`** (issue #155,
  firmware 439/509/539): both had `step: 0.1` despite being whole-number
  cycle counts, so a device value of 48 displayed as 4.8 and a value of 1
  as 0.1. Fixed to `step: 1`.

- **`enable_hc2` not applied on upgrade**: entries that predate the hc2/advanced
  category split (where HC2 was previously enabled under the "Extended"/"All" tiers)
  had no recorded HC2 reconciliation state, so the change-detection defaulted the
  "previous" HC2 state to `False` -- coincidentally matching the checkbox's own
  default. Explicitly setting "Enable HC2 entities" to off via Reconfigure, with the
  tier left unchanged, was then wrongly treated as a no-op, leaving already-enabled
  HC2 entities visible. Now infers the effective prior HC2 state from the
  previously-applied tier when no HC2 reconciliation has run yet, so this case is
  correctly detected and reconciled.

- **HC2 schedule entities ignored `enable_hc2`**: entity names matching both the
  "program" (schedule) and "hc2" keywords -- i.e. HC2's own time-plan entities like
  `programHC2_Mo_0` -- were classified purely as "schedule", so they were governed
  only by the `entity_visibility` tier and became visible under "All" regardless of
  the "Enable HC2 entities" checkbox. HC2 is now matched before "schedule", so any
  HC2-related entity, program/schedule ones included, is gated purely by
  `enable_hc2`, independent of the tier.

- **`p99CoolingHC1AreaFan` was a plain on/off switch showing "1"/"0"**:
  this parameter actually selects which distribution system HC1 cooling is
  delivered through -- "area" (a surface/underfloor loop run in reverse) or
  "air" (a fan coil unit) -- not a literal fan. The name was also
  misleading and the German translation ("Flächenlüfter", i.e. "area fan")
  was simply wrong. Converted to a select entity (`Cooling HC1
  Distribution`) showing "Area (floor)"/"Air (fan coil)" instead of raw
  1/0, confirmed against real hardware: 0 = area, 1 = air.

- **Time entities never actually wrote to the device**: `THZTime` and
  `THZScheduleTime` (schedule Start/End) defined `async_set_native_value`,
  which is the `NumberEntity`/`SelectEntity` override convention -- not
  `TimeEntity`'s. `TimeEntity` calls `async_set_value` instead, so every
  `time.set_value` service call (including from the schedule Lovelace card)
  silently fell through to the base class's own unimplemented `set_value()`
  and raised `NotImplementedError` before ever reaching the device, shown
  to the user as "Failed to perform the action time/set_value. unknown
  error" on every single write attempt. Renamed both methods to
  `async_set_value(self, value: time) -> None` and dropped the now-dead
  manual string-to-time parsing, since HA's own `time.set_value` schema
  already validates and hands the method a real `datetime.time`.
- **Test suite could not catch this class of bug**: `tests/conftest.py`'s
  `MockTimeEntity` stand-in didn't simulate `TimeEntity`'s real
  "unimplemented base method raises `NotImplementedError`" fallback at all,
  so a subclass overriding the wrong method name would still "pass" under
  test. `MockTimeEntity` now mirrors that fallback chain.

### New Features

- **`thz.clear_value` service**: clears a time or schedule Start/End entity
  back to the device's own "unset" state (the 0x80 sentinel), equivalent to
  clearing that slot from the heat pump's own on-device menu. Home
  Assistant's built-in `time.set_value` service has no way to express "no
  time set" -- its schema requires a real time value -- so this is exposed
  as a dedicated entity service on the `time` platform instead, targetable
  at any `time.*` entity from this integration.

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
