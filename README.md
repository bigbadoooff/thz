# Stiebel Eltron LWZ / Tecalor THZ Integration (unofficial)

[![Validate](https://github.com/bigbadoooff/thz/actions/workflows/ci.yml/badge.svg)](https://github.com/bigbadoooff/thz/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/bigbadoooff/thz)](https://github.com/bigbadoooff/thz/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

[![GitHub last commit](https://img.shields.io/github/last-commit/bigbadoooff/thz)](https://github.com/bigbadoooff/thz/commits)
[![GitHub issues](https://img.shields.io/github/issues/bigbadoooff/thz)](https://github.com/bigbadoooff/thz/issues)
[![GitHub contributors](https://img.shields.io/github/contributors/bigbadoooff/thz)](https://github.com/bigbadoooff/thz/graphs/contributors)
[![GitHub Repo stars](https://img.shields.io/github/stars/bigbadoooff/thz?style=social)](https://github.com/bigbadoooff/thz/stargazers)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bigbadoooff&repository=thz&category=integration)
[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=thz)

> **Version 0.6.0** — See [CHANGELOG.md](CHANGELOG.md) for the full list of new
> features and breaking changes in this release.

## Introduction

This is a custom Home Assistant integration for connecting Stiebel Eltron LWZ or Tecalor THZ heat pumps to Home Assistant. The integration enables comprehensive monitoring and control of your heat pump system directly from your Home Assistant instance.

The integration communicates with the heat pump using the serial protocol, supporting both direct USB connections and network-based serial connections (via ser2net). This allows flexible deployment options depending on your home automation setup.

Parts of this software have been developed by the help of AI.

**Origin**: This integration is based on the FHEM-Module developed by Immi, adapted for Home Assistant with modern async architecture and full UI configuration support.

**v0.4** adds climate entities (HC1, HC2, DHW), diverter valve motor control, compressor/booster runtime sensors, a block-refresh service, and a range of reliability and correctness improvements. See [CHANGELOG.md](CHANGELOG.md) for details.

## Features

### Currently Implemented

- ✅ **Full UI Configuration**: Easy setup through Home Assistant's integration interface — no YAML configuration required
- ✅ **Connection Options**: Support for both USB serial and network (ser2net) connections
- ✅ **Sensor Platform**: Monitor temperatures, pressures, operating states, runtime hours, and more
- ✅ **Switch Platform**: Control heat pump functions on/off
- ✅ **Number Platform**: Adjust numeric settings and parameters
- ✅ **Select Platform**: Choose between predefined options — including **passive cooling mode** (firmware 4.39/5.39)
- ✅ **Time Platform**: Set time-based parameters, schedules and programmes
- ✅ **Climate Platform**: Climate entities for Heating Circuit 1 and Heating Circuit 2 — with temperature control, HVAC mode and preset support
- ✅ **Water Heater Platform**: Hot water as a water heater entity — temperature, setpoint and eco (setback) / performance / off state
- ✅ **Fan Platform**: Ventilation as a fan entity — shows the current stage and starts unscheduled ventilation at stage 0–3
- ✅ **Diagnostics**: Download a diagnostics report for troubleshooting (via Settings → Devices & Services)
- ✅ **Device Registry Integration**: Proper device identification in Home Assistant
- ✅ **Per-Block Polling Intervals**: Each register block has its own configurable poll interval
- ✅ **Smart Entity Management**: Non-essential entities are hidden by default to reduce clutter
- ✅ **Services**: `thz.read_raw_register`, `thz.refresh_block`, `thz.set_diverter_valve`, parameter backup/restore, and fault memory (`thz.probe_fault_memory`, `thz.acknowledge_faults`, `thz.clear_fault_memory`)

### Climate Entities

These entities are created when the required data blocks and parameters are available:

| Entity | Source | Supports |
|--------|-------------|---------|
| Heating Circuit 1 (climate) | `pxxF4` | Temperature setpoint, HVAC mode, preset (operating mode) |
| Heating Circuit 2 (climate) | `pxxF5` | Temperature setpoint, HVAC mode, preset — created only when HC2 is configured |
| Hot Water (water heater) | `pxxF3` | Temperature and setpoint in effect; state `performance` (day), `eco` (setback, night setpoint) or `off` (standby). Setting a temperature writes the day setpoint (`p04`), or the night setpoint (`p05`) while in eco. |
| Ventilation (fan) | `p99startUnschedVent` (firmware 4.x/5.x) | The time programs set the ventilation stage; the fan controls *unscheduled ventilation*. A speed of 33/66/100 % starts it at stage 1/2/3, off starts it at stage 0, each for the time set in `p43`–`p46`; then the program takes over again. The program's stage settings (`p07` etc.) are not changed. Shown is the stage the ventilation runs at: from the supply airflow of the current stage (`pxxE8`, when polled) compared with `p37`–`p39`, otherwise from today's fan time program (day stage `p07` inside a window, night stage `p08` outside). |

HC1 also exposes **HVAC action** (heating / cooling / idle) and optional **cooling mode** when the device supports active cooling.

### Services

#### `thz.read_raw_register`
Read any raw register block directly from the heat pump and return the hex dump. Useful for firmware research and debugging. See [docs/read-raw-register-service.md](docs/read-raw-register-service.md) for full documentation.

#### `thz.refresh_block`
Force an immediate re-read of a specific coordinator block without waiting for the next poll interval. Accepts any block name form (`"FB"`, `"pxxFB"`, `"0xFB"`). Returns `{success, block}`.

```yaml
service: thz.refresh_block
data:
  block: "FB"
```

#### `thz.set_diverter_valve`
Manual control of the 3-way diverter valve motor. Both `heating` and `dhw` directions are guarded by the `diverterValve` status bit in `pxxF2`, read from the heat pump right before the move — the command is refused if the heat pump is currently pressurising the opposite circuit, or if `pxxF2` cannot be read. After 3 seconds the motor is automatically stopped and the stop is verified by reading back both motor registers.

```yaml
service: thz.set_diverter_valve
data:
  position: "dhw"   # heating | dhw | off
```

⚠️ Only use this service if you have a manually-controlled 3-way valve and understand the risk of incorrect actuation.

### Fault Memory (firmware 4.x / 5.x)

The heat pump keeps its last ten faults but has no "acknowledged" concept. When the **Fault Log** (`pxxD1`) block is polled, four sensors are created from it (no extra serial traffic):

| Sensor | Meaning |
|--------|---------|
| Fault status | `No fault` / `Fault` — `Fault` while there are records you have not acknowledged |
| Fault memory | Number of stored records; all records (newest first) are in the `entries` attribute |
| Latest fault | The newest stored fault, translated (`none` if there is none) with code, date and time as attributes |
| New faults | Number of records not yet acknowledged; the records are in the `entries` attribute |

Faults already stored when the integration first sees the block are treated as acknowledged, so an existing history does not trigger an alarm. The heat pump stores day and month only, no year.

#### `thz.probe_fault_memory`
Read-only. Returns the raw D1 bytes and the decoded records.

#### `thz.acknowledge_faults`
Marks all records currently stored as seen. Only affects Home Assistant (the *Fault status* and *New faults* sensors); nothing is written to the heat pump.

#### `thz.clear_fault_memory`
Physically clears the heat pump's fault memory. It reads and validates D1 first, sends **one** clear command (`0000` to D1, never retried) and verifies the result by reading D1 again. The history on the device is lost. You must pass `confirmation: "CLEAR D1"`. It works on every firmware that provides D1, but the write has only been verified on real hardware on firmware **4.19**; if the readback still shows faults the service reports an error.

```yaml
service: thz.clear_fault_memory
data:
  confirmation: "CLEAR D1"
```

### Hidden Entities by Default

To provide a cleaner initial setup experience, the following entity types are hidden by default:

- **Time plan/programme entities**: Advanced schedule configuration entities (`programDHW_*`, `programHC1_*`)
- **Advanced technical parameters**: Parameters like gradient, hysteresis, integral components (typically p13 and higher)
- **HC2 (Heating Circuit 2) entities**: Only needed if you have a second heating circuit installed, including HC2's own schedule entities (`programHC2_*`). Gated separately from the two categories above (see below).

Two independent settings control this, both asked during setup and changeable later via **Settings → Devices & Services → THZ → Configure**. Changing either retroactively bulk enables/disables the matching entities already in the registry, not just newly-created ones — any entity you've individually re-enabled or disabled by hand is left alone.

- **Entity visibility** — a three-way tier covering schedules and advanced parameters:
  - *Default*: hide both.
  - *Extended*: enable advanced parameters, keep schedules hidden.
  - *All*: enable both.
- **Enable HC2 entities** — a separate checkbox, off by default. Independent of the tier above — even the "All" tier leaves HC2 hidden until this is checked, since most installs only have one heating circuit.

Entities can also always be re-enabled individually via **Settings → Devices & Services → THZ → device → Show disabled entities**.

### Sub-devices

The entities can be grouped into sub-devices linked to the heat pump:

- Heating circuit 1
- Heating circuit 2
- Hot water
- Ventilation
- Compressor (compressor, refrigerant circuit, defrost, COP)
- Solar
- Cooling

General entities, such as the clock, fault memory, versions, outside temperature and operating mode, stay on the heat pump device. Each sub-device has its own device page and can be put in its own area.

The **Split into sub-devices** setting is asked during setup, on by default. It can be changed later via **Settings → Devices & Services → THZ → Configure**. Installations set up before this option existed keep the single device until you switch it on.

Switching the split on or off keeps the entity IDs, but the displayed names change. With the split on, a name is made of the sub-device name and the entity name, for example "lwz Hot water DHW temperature". Automations that refer to entity IDs keep working. Automations that pick a *device* (device triggers, conditions or actions) must be pointed to the new device. When the split is switched off, the entities move back to the heat pump with their names, areas and enabled state intact, and the sub-devices are removed.

### COP (Coefficient of Performance) Sensors

For firmware versions that support energy monitoring (e.g., 4.39), the integration automatically provides COP sensors:

- **Current COP**: Real-time COP based on instantaneous power measurements
- **Daily COP DHW / Heating / Total**
- **Lifetime COP DHW / Heating / Total**

COP = Heat Output ÷ Electrical Input. A COP of 3.0 means 3 kW of heat for every 1 kW of electricity consumed.

### Runtime Hours (firmware 4.39 / 5.39)

The `sHistory` block (command `09`) provides cumulative operating hours for the compressor and booster heaters:

- `compressor_runtime_heating` — compressor hours in heating mode
- `compressor_runtime_cooling` — compressor hours in cooling mode
- `compressor_runtime_dhw` — compressor hours in DHW mode
- `booster_runtime_dhw` — booster heater hours for DHW
- `booster_runtime_heating` — booster heater hours for heating

### Passive Cooling (firmware 4.39 / 5.39)

A **Passive Cooling** select entity controls the passive cooling mode:

| Mode | Description |
|------|-------------|
| `off` | Passive cooling disabled |
| `exhaust_air` | Cool via exhaust air only |
| `supply_air` | Cool via supply air only |
| `bypass` | Bypass mode |
| `sommerkassette` | Summer cassette mode |

A corresponding energy sensor `sCoolHCTotal` tracks total passive cooling energy on firmware 5.39.

### Diagnostics

The integration supports Home Assistant's built-in diagnostics download:

1. Go to **Settings** → **Devices & Services** → **THZ**
2. Click on your heat pump device
3. Click **Download Diagnostics**

The report includes firmware version, connection status, coordinator last-update times, and redacted hex dumps of all currently-polled register blocks.

## Compatibility

### Supported Firmware Versions

| Firmware | Notes |
|----------|-------|
| 2.06     | Sensor read support; write support via block read-modify-write |
| 2.14 / 2.14j | Sensor read support; write support via block read-modify-write |
| 4.19     | 4.39-like profile for the THZ 303 SOL; a few `pxxFB` sensors the shorter payload cannot supply are disabled. Fault memory clear verified on this firmware |
| 4.39     | Full support including energy sensors, COP, runtime hours, and passive cooling |
| 5.39     | Full support including passive cooling energy sensor (`sCoolHCTotal`) |
| Other    | Falls back to a 4.39-like configuration (like the reference FHEM module) — may work partially |

### How Firmware Versions Are Loaded

The `firmware` option you pick during setup selects which register map modules
the integration merges together. This determines both which sensors/entities
get created and how their raw bytes are decoded — picking the wrong firmware
typically produces missing entities or garbled values, not errors.

Everything is driven by `RegisterMapManager` / `RegisterMapManagerWrite`
(`custom_components/thz/register_maps/register_map_manager.py`), which build
a merged map for a given `firmware` string in three layers, applied in order
(a later layer's entries win, matched by sensor name within the same
register block):

1. **Base map** — `register_map_all.py` (reads) is always loaded first. It
   defines the registers common to essentially every firmware (climate
   blocks `F2`–`F5`, `sGlobal`/`FB`, `sTimedate`/`FC`, firmware/hardware
   version `FD`/`FE`, etc.), using the 4.39/5.39 byte layout. There is no
   `write_map_all.py` — the base write map is effectively empty.
2. **Write maps** — one or more `write_map_*.py` modules for the firmware,
   merged in listed order.
3. **Read maps** — one or more `readings_map_*.py` / `register_map_*.py`
   modules for the firmware, merged in listed order over the base map.

| `firmware` value | Write maps | Read maps (over the base) |
|---|---|---|
| `206` | `write_map_206` | `readings_map_2xx`, `readings_map_206`, `register_map_206` |
| `214` | `write_map_206`, `write_map_214` | `readings_map_2xx`, `readings_map_214`, `register_map_214` |
| `214j` | `write_map_206`, `write_map_214` | `readings_map_2xx`, `readings_map_214j`, `register_map_214j` |
| `419` | `write_map_439_539`, `write_map_439` | `readings_map_439`, `register_map_419` |
| `439` | `write_map_439_539`, `write_map_439` | `readings_map_439`, `register_map_439` |
| `439technician` | `write_map_439_539`, `write_map_439`, `write_map_X39tech` | `readings_map_439`, `register_map_439` |
| `509` / `709` | `write_map_439_539`, `write_map_539` | `readings_map_439`, `readings_map_509` |
| `539` | `write_map_439_539`, `write_map_539` | `readings_map_439`, `readings_map_539` |
| `539technician` | `write_map_439_539`, `write_map_539`, `write_map_X39tech` | `readings_map_439`, `readings_map_539` |
| anything else | `write_map_439_539`, `write_map_439` | `readings_map_439` (`default`, treated as 4.39-like) |

`709` is intentionally identical to `509` — the 7.09 firmware has no register
differences from 5.09 that this integration is aware of. An unrecognized
`firmware` string falls back to `default`, which mirrors the reference FHEM
module's own behaviour of assuming 4.39 rather than guessing at 5.39-like
registers that may not exist on the device (e.g. cooling-only blocks).

#### The 2xx family (206 / 214 / 214j)

- `readings_map_2xx.py` holds the sensor blocks the legacy FHEM module
  requests identically for **all three** 2.xx variants (defrost/heating/DHW/
  solar parameters, operating hours, schedules, fan calibration, solar
  circuit, system status, time/date). `readings_map_206.py`,
  `readings_map_214.py`, and `readings_map_214j.py` then only need to add
  what genuinely differs per variant:
  - `pFan` (cmd `01`): 206 uses a longer byte layout than 214/214j, which
    share a shorter one.
  - `sHC1` (cmd `F4`) and `sGlobal` (cmd `FB`): each variant has its own bit
    layout, since the underlying hardware/firmware differ.
  - The fault log `sLast10errors` (cmd `D1`) only exists on 206 — 214/214j
    firmware doesn't expose it, so no entity is created for those variants.
- Writing a parameter on 2xx firmware works differently from 4.39/5.39: the
  protocol has no per-register write command, so `RegisterMapManagerWrite`
  cross-references the read register maps to look up each writable
  parameter's containing block, byte offset, and length, then performs a
  read-modify-write of the whole block (`write_mode="block"`, see
  `_enrich_2xx_write_entries`). 4.39/5.39 write registers directly.
- No energy/COP metering, runtime-hours-by-mode, or passive cooling exists
  on 2xx firmware — those registers were only added starting with 4.39 (see
  below).

#### The 4.39 / 5.39 family (439 / 509 / 709 / 539)

- `readings_map_439.py` is the common base for this family (energy/COP
  sensors, compressor & booster runtime hours, fault log, solar circuit,
  fan speeds); `readings_map_509.py` / `readings_map_539.py` layer
  firmware-specific extras on top (e.g. flow rate, humidity thresholds,
  compressor power/rotation limits, dew point sensors, and — 5.39 only —
  the passive-cooling energy sensor `sCoolHCTotal`).
- Devices without active cooling hardware get cooling-only registers
  stripped from the merged 5.39 maps (`_COOLING_READ_BLOCKS` /
  `_COOLING_WRITE_KEYS`, applied via the `has_cooling` flag from your
  config), so the passive cooling select entity and its related sensors
  only appear when relevant.
- The `439technician` / `539technician` variants add `write_map_X39tech` on
  top of the normal 439/539 write maps, exposing extra technician-only
  parameters that are otherwise not writable.

### Confirmed Working Devices

| Model | Firmware Version | Status |
|-------|------------------|--------|
| LWZ5  | 7.59 | ✅ Working |

**Note**: While this integration has been confirmed to work with the devices listed above, it may work with other Stiebel Eltron LWZ and Tecalor THZ models. Users are encouraged to test and report compatibility.

## Installation

### Prerequisites

- Home Assistant (version 2021.12 or newer recommended)
- USB-to-serial adapter or ser2net server for network connection
- Physical access to your heat pump's serial interface

### Option 1: HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance
2. Open HACS → **Integrations** → three-dot menu → **Custom repositories**
3. Add `https://github.com/bigbadoooff/thz` as a custom repository with category **Integration**
4. Search for "Stiebel Eltron LWZ / Tecalor THZ" and click **Download**
5. Restart Home Assistant

### Option 2: Manual Installation

1. Download the latest release from the [releases page](https://github.com/bigbadoooff/thz/releases)
2. Copy the `thz` folder to `<config_dir>/custom_components/thz/`
3. Restart Home Assistant

### Configuration

1. Go to **Settings** → **Devices & Services** → **+ ADD INTEGRATION**
2. Search for **"Stiebel Eltron LWZ / Tecalor THZ Integration"**
3. Choose your connection type (USB or Network/ser2net) and follow the wizard

## Removal

1. Go to **Settings** → **Devices & Services** → **THZ**
2. Click the three-dot menu on the integration entry and choose **Delete**
3. Confirm the removal — this stops all polling and removes the device and
   its entities from Home Assistant. The `thz.*` services stay registered
   until Home Assistant restarts without the integration.

After deleting the integration in the UI, also remove the files depending on
how it was installed:

- **HACS**: open HACS → **Integrations**, find "Stiebel Eltron LWZ / Tecalor
  THZ", and click **Remove**
- **Manual installation**: delete the `<config_dir>/custom_components/thz/`
  folder

Then restart Home Assistant. No credentials or external accounts are created
by this integration, so there is nothing else to revoke — only the local
serial/network connection to the heat pump is released.

## Troubleshooting

### USB connection stops working after host reboot

If you are using USB and another application (e.g., FHEM) also accesses the serial port, it may grab the device before Home Assistant on startup, causing "Handshake 1 failed" errors. Disable the THZ device in FHEM (or whichever application is competing) and restart the Home Assistant container.

If HA is running in Docker and the device was not enumerated when the container started, restart the container after the USB adapter appears: `docker restart homeassistant`.

### Integration does not create entities

Check HA logs for `thz` entries. Common causes:
- Firmware version not detected (empty firmware string) — the integration falls back to a default map but some blocks may be empty
- Block not supported on the device — blocks returning no data are skipped silently

Use `thz.read_raw_register` to verify that a specific block returns data on your device.

## Disclaimer

**IMPORTANT**: This is an unofficial, community-developed integration and is not affiliated with, endorsed by, or supported by Stiebel Eltron or Tecalor.

⚠️ **Use at Your Own Risk**: While this integration has been tested and used in production, no warranty is provided. Improper use could affect your heat pump's operation. Always monitor your heat pump after installing this integration.

## How to Contribute

Contributions are welcome!

- **Bugs**: Open an issue with HA version, heat pump model, firmware version, and relevant log entries
- **Compatibility reports**: Let us know which devices work (or don't)
- **Code**: see [CONTRIBUTING.md](CONTRIBUTING.md) and [ARCHITECTURE.md](ARCHITECTURE.md)

## Contributors

Thanks to everyone who has helped build and improve this integration:

<table>
<tr>
<td align="center">
<a href="https://github.com/bigbadoooff">
<img src="https://github.com/bigbadoooff.png?size=80" width="80" height="80" alt="bigbadoooff"><br>
<sub><b>bigbadoooff</b></sub>
</a>
</td>
<td align="center">
<a href="https://github.com/Largelos">
<img src="https://github.com/Largelos.png?size=80" width="80" height="80" alt="Largelos"><br>
<sub><b>Largelos</b></sub>
</a>
</td>
<td align="center">
<a href="https://github.com/MartinDomig">
<img src="https://github.com/MartinDomig.png?size=80" width="80" height="80" alt="MartinDomig"><br>
<sub><b>MartinDomig</b></sub>
</a>
</td>
</tr>
</table>

See the full [contributor graph](https://github.com/bigbadoooff/thz/graphs/contributors)
for everyone who has opened issues, filed compatibility reports, or submitted
PRs. Parts of this software have also been developed with the help of AI
(GitHub Copilot, Claude).

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

---

**Credits**: Based on the FHEM-Module by Immi. Thanks to the FHEM and Home Assistant community for their support and contributions.
