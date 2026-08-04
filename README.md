# Stiebel Eltron LWZ / Tecalor THZ Integration (unofficial)

[![Validate](https://github.com/bigbadoooff/thz/actions/workflows/validate.yml/badge.svg)](https://github.com/bigbadoooff/thz/actions/workflows/validate.yml)
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

> **Version 0.4.3** — See [CHANGELOG.md](CHANGELOG.md) for the full list of new
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
- ✅ **Climate Platform**: Full climate entities for Heating Circuit 1, Heating Circuit 2, and Domestic Hot Water — with temperature control, HVAC mode, preset and fan mode support
- ✅ **Diagnostics**: Download a diagnostics report for troubleshooting (via Settings → Devices & Services)
- ✅ **Device Registry Integration**: Proper device identification in Home Assistant
- ✅ **Per-Block Polling Intervals**: Each register block has its own configurable poll interval
- ✅ **Smart Entity Management**: Non-essential entities are hidden by default to reduce clutter
- ✅ **Services**: `thz.read_raw_register`, `thz.refresh_block`, and `thz.set_diverter_valve`

### Climate Entities

Three climate entities are automatically created when the required data blocks are available:

| Entity | Source block | Supports |
|--------|-------------|---------|
| Heating Circuit 1 | `pxxF4` | Temperature setpoint, HVAC mode, preset (comfort/sleep/away), fan mode |
| Heating Circuit 2 | `pxxF5` | Temperature setpoint, HVAC mode, preset — created only when HC2 is configured |
| Domestic Hot Water | `pxxF3` | Temperature setpoint, HVAC mode |

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
Manual control of the 3-way diverter valve motor. Both `heating` and `dhw` directions are guarded by the `diverterValve` status bit in `pxxF2` — the command is refused if the heat pump is currently pressurising the opposite circuit. After 3 seconds the motor is automatically stopped and the stop is verified by reading back both motor registers.

```yaml
service: thz.set_diverter_valve
data:
  position: "dhw"   # heating | dhw | off
```

⚠️ Only use this service if you have a manually-controlled 3-way valve and understand the risk of incorrect actuation.

### Hidden Entities by Default

To provide a cleaner initial setup experience, the following entity types are hidden by default:

- **HC2 (Heating Circuit 2) entities**: Only needed if you have a second heating circuit installed
- **Time plan/programme entities**: Advanced schedule configuration entities (`programDHW_*`, `programHC1_*`, `programHC2_*`)
- **Advanced technical parameters**: Parameters like gradient, hysteresis, integral components (typically p13 and higher)

Hidden entities can be re-enabled via **Settings → Devices & Services → THZ → device → Show disabled entities**.

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
| 4.39     | Full support including energy sensors, COP, runtime hours, and passive cooling |
| 5.39     | Full support including passive cooling energy sensor (`sCoolHCTotal`) |
| Other    | Falls back to 5.39-like configuration — may work partially |

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
3. Confirm the removal — this stops all polling, unregisters the `thz.*`
   services, and removes the device and its entities from Home Assistant

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
- **Code**: Fork → feature branch → PR with a clear description

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
