# Stiebel Eltron LWZ / Tecalor THZ Integration (unofficial)

[![Validate](https://github.com/bigbadoooff/thz/actions/workflows/validate.yml/badge.svg)](https://github.com/bigbadoooff/thz/actions/workflows/validate.yml)
[![GitHub Release](https://img.shields.io/github/v/release/bigbadoooff/thz)](https://github.com/bigbadoooff/thz/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

> **Version 0.3.0-alpha** — See [CHANGELOG.md](CHANGELOG.md) for the full list of new
> features and breaking changes in this release.

## Introduction

This is a custom Home Assistant integration for connecting Stiebel Eltron LWZ or Tecalor THZ heat pumps to Home Assistant. The integration enables comprehensive monitoring and control of your heat pump system directly from your Home Assistant instance.

The integration communicates with the heat pump using the serial protocol, supporting both direct USB connections and network-based serial connections (via ser2net). This allows flexible deployment options depending on your home automation setup.

Parts of this software have been developed by the help of AI.

**Origin**: This integration is based on the FHEM-Module developed by Immi, adapted for Home Assistant with modern async architecture and full UI configuration support.

**V0.3 alpha** adds passive cooling control, full diagnostics support, COP sensors, energy sensors via paired-block reads, and many reliability improvements. See [CHANGELOG.md](CHANGELOG.md) for details.

## Features

### Currently Implemented

- ✅ **Full UI Configuration**: Easy setup through Home Assistant's integration interface - no YAML configuration required
- ✅ **Connection Options**: Support for both USB serial and network (ser2net) connections
- ✅ **Sensor Platform**: Monitor various heat pump parameters (temperatures, pressures, operating states, etc.)
- ✅ **Switch Platform**: Control heat pump functions on/off
- ✅ **Number Platform**: Adjust numeric settings and parameters
- ✅ **Select Platform**: Choose between predefined options for various settings — including **passive cooling mode** (firmware 4.39/5.39)
- ✅ **Time Platform**: Set time-based parameters, schedules and programs
- ✅ **Diagnostics**: Download a diagnostics report for troubleshooting (via Settings → Devices & Services)
- ✅ **Device Registry Integration**: Proper device identification in Home Assistant
- ✅ **Per-Block Polling Intervals**: Each register block has its own configurable poll interval
- ✅ **Smart Entity Management**: Non-essential entities are hidden by default to reduce clutter
- ✅ **Raw Register Service**: `thz.read_raw_register` service for debugging firmware-specific register layouts

### Hidden Entities by Default

To provide a cleaner initial setup experience, the following entity types are hidden by default:

- **HC2 (Heating Circuit 2) entities**: Only needed if you have a second heating circuit installed
- **Time plan/program entities**: Advanced schedule configuration entities (programDHW_*, programHC1_*, programHC2_*)
- **Advanced technical parameters**: Parameters like gradient, hysteresis, integral components (typically p13 and higher)

**Note**: Hidden entities can still be manually enabled through the Home Assistant UI:
1. Go to **Settings** → **Devices & Services**
2. Find the THZ integration and click on it
3. Click on the device
4. Click "Show disabled entities" at the bottom
5. Enable any entities you need

### COP (Coefficient of Performance) Sensors

For firmware versions that support energy monitoring (e.g., 4.39), the integration automatically provides COP sensors:

#### Automatically Created Sensors

- **Current COP**: Real-time COP based on instantaneous power measurements
- **Daily COP DHW**: Daily COP for domestic hot water
- **Daily COP Heating**: Daily COP for heating circuit
- **Daily COP Total**: Combined daily COP (DHW + Heating)
- **Lifetime COP DHW**: Overall COP for DHW since installation
- **Lifetime COP Heating**: Overall COP for heating since installation
- **Lifetime COP Total**: Combined lifetime COP (DHW + Heating)

**Note**: COP (Coefficient of Performance) is calculated as Heat Output ÷ Electrical Input. A COP of 3.0 means the heat pump produces 3 kW of heat for every 1 kW of electricity consumed. 

COP sensors require energy sensors to be available on your device, typically present in firmware 4.39 and higher.

### Passive Cooling (firmware 4.39 / 5.39)

For devices running firmware 4.39 or 5.39, a **Passive Cooling** select entity is available to control how the heat pump uses its passive cooling capability. Available modes:

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

The report includes firmware version, connection status, coordinator last-update times, and redacted hex dumps of all currently-polled register blocks. This information is useful when reporting bugs.

### Developer: Raw Register Service

Use the `thz.read_raw_register` service to read any raw register block from the heat pump for debugging or firmware research. See [docs/read-raw-register-service.md](docs/read-raw-register-service.md) for full documentation.

### Developer: Scan Raw Registers Service

Use the `thz.scan_raw_registers` service to scan multiple raw registers in one run and collect all successful responses.

- Input modes:
   - `pattern`: 6-char hex pattern with `X` wildcard (example: `0A0XXX` scans `0A0000`..`0A0FFF`)
   - `start` + `end`: explicit inclusive hex range
- Optional fields:
   - `entry_id`: required when multiple THZ devices are configured
   - `include_errors`: include failed commands in `results`
   - `decode_values`: include best-effort decoded values in `results.decoded`
   - `max_results`: limit amount of scanned commands

Service response contains:

- `summary`: mode, scanned count, success/error counters
- `results`: list of commands with `command`, `length`, `hex`, formatted hex dump (`formatted`)
- when `decode_values: true`, each successful result also contains `decoded` with best-effort candidates decoded from payload bytes (not from checksum/echo header bytes)

Example service call:

- `pattern: "0A0XXX"`
- `max_results: 4096`

This scans every command from `0A0000` to `0A0FFF`, preserving all successful responses in a structured output for easy review.

### Planned Features

- 🔄 Create climate entities for smoother interaction with Home Assistant's climate card

## Compatibility

### Supported Firmware Versions

The register maps and write maps in this release target the following firmware families:

| Firmware | Notes |
|----------|-------|
| 2.06     | sensors are supported, writing of entities to be implemented |
| 2.14 / 2.14j | sensors are supported, writing of entities to be implemented |
| 4.39     | Full support including energy sensors, COP, and passive cooling |
| 5.39     | Full support including passive cooling energy sensor (`sCoolHCTotal`) |
| Other    | Falls back to 5.39-like configuration — may work partially |

### Confirmed Working Devices

| Model | Firmware Version | Status |
|-------|------------------|--------|
| LWZ5  | 7.59            | ✅ Working |

**Note**: While this integration has been confirmed to work with the devices listed above, it may work with other Stiebel Eltron LWZ and Tecalor THZ models. Users are encouraged to test and report compatibility.

## Installation

### Prerequisites

- Home Assistant (version 2021.12 or newer recommended)
- USB-to-serial adapter or ser2net server for network connection
- Physical access to your heat pump's serial interface

### Installation Methods

#### Option 1: HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance
2. Open HACS in your Home Assistant interface
3. Navigate to "Integrations"
4. Click the three dots in the top right corner and select "Custom repositories"
5. Add `https://github.com/bigbadoooff/thz` as a custom repository with category "Integration"
6. Search for "Stiebel Eltron LWZ / Tecalor THZ" in HACS
7. Click "Download" to install the integration
8. Restart Home Assistant

#### Option 2: Manual Installation

1. Download the latest release from the [releases page](https://github.com/bigbadoooff/thz/releases)
2. Extract the `thz` folder from the archive
3. Copy the `thz` folder to your Home Assistant's `custom_components` directory
   - Path: `<config_dir>/custom_components/thz/`
   - If the `custom_components` directory doesn't exist, create it
4. Restart Home Assistant

### Configuration

1. Navigate to **Settings** → **Devices & Services** in Home Assistant
2. Click the **"+ ADD INTEGRATION"** button
3. Search for **"Stiebel Eltron LWZ / Tecalor THZ Integration"**
4. Follow the configuration wizard:
   - **Connection Type**: Choose between USB or Network (ser2net)
   - **USB Connection**: Provide the device path (e.g., `/dev/ttyUSB0`)
   - **Network Connection**: Provide the host IP address and port
5. Complete the setup and the integration will discover your heat pump

## Disclaimer

**IMPORTANT**: This is an unofficial, community-developed integration and is not affiliated with, endorsed by, or supported by Stiebel Eltron or Tecalor.

⚠️ **Use at Your Own Risk**: While this integration has been tested and used successfully, the author makes no guarantees regarding its functionality, safety, or suitability for any particular purpose. By using this integration, you acknowledge and accept the following:

- No warranty or guarantee of any kind is provided
- The integration may not work with all heat pump models or firmware versions
- Improper use or configuration could potentially affect your heat pump's operation
- You are responsible for ensuring compliance with any applicable warranties or regulations
- Always monitor your heat pump's operation after installing this integration

That said, the integration has been running successfully in production environments without issues. The author welcomes feedback and bug reports to improve the integration.

## How to Contribute

Contributions are welcome and appreciated! Here's how you can help:

### Reporting Issues

If you encounter bugs or unexpected behavior:

1. Check the [existing issues](https://github.com/bigbadoooff/thz/issues) to see if your problem has already been reported
2. If not, create a new issue with:
   - A clear, descriptive title
   - Detailed description of the problem
   - Steps to reproduce the issue
   - Your Home Assistant version
   - Your heat pump model and firmware version
   - Relevant log entries (if available)

### Providing Feedback

Your feedback helps improve the integration:

- Share your experience with different heat pump models and firmware versions
- Suggest new features or improvements
- Report which devices work (or don't work) with the integration

### Contributing Code

If you'd like to contribute code:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes following the existing code style
4. Test your changes thoroughly
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request with a clear description of your changes

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

This means you are free to use, modify, and distribute this software under the terms of the GPL v3 license. Any derivative works must also be licensed under GPL v3.

---

**Credits**: Based on the FHEM-Module by Immi. Thanks to the FHEM and Home Assistant community for their support and contributions.







