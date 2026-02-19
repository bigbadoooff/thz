# Stiebel Eltron LWZ / Tecalor THZ Integration (unofficial)

[![Validate](https://github.com/bigbadoooff/thz/actions/workflows/validate.yml/badge.svg)](https://github.com/bigbadoooff/thz/actions/workflows/validate.yml)
[![GitHub Release](https://img.shields.io/github/v/release/bigbadoooff/thz)](https://github.com/bigbadoooff/thz/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Introduction

This is a custom Home Assistant integration for connecting Stiebel Eltron LWZ or Tecalor THZ heat pumps to Home Assistant. The integration enables comprehensive monitoring and control of your heat pump system directly from your Home Assistant instance.

The integration communicates with the heat pump using the serial protocol, supporting both direct USB connections and network-based serial connections (via ser2net). This allows flexible deployment options depending on your home automation setup.

**Origin**: This integration is based on the FHEM-Module developed by Immi, adapted for Home Assistant with modern async architecture and full UI configuration support.

**V0.2 is a big release that fixes most of the known errors. A few tranlation strings are still missing and some sensor values are off either in unit or in size. I will fix that one by one.**

## Features

### Currently Implemented

- ✅ **Full UI Configuration**: Easy setup through Home Assistant's integration interface - no YAML configuration required
- ✅ **Connection Options**: Support for both USB serial and network (ser2net) connections
- ✅ **Sensor Platform**: Monitor various heat pump parameters (temperatures, pressures, operating states, etc.)
- ✅ **Switch Platform**: Control heat pump functions on/off
- ✅ **Number Platform**: Adjust numeric settings and parameters
- ✅ **Select Platform**: Choose between predefined options for various settings
- ✅ **Time Platform**: Set time-based parameters, schedules and programs
- ✅ **Device Registry Integration**: Proper device identification in Home Assistant
- ✅ **Automatic Polling**: Regular updates of sensor values
- ✅ **Smart Entity Management**: Non-essential entities are hidden by default to reduce clutter

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

### Planned Features

- 🔄 make sure all Sensor values are interpreted correctly
- 🔄 Improve Settings for Polling Frequency from the Device
- 🔄 create climate entities for smoother interaction

## Compatibility

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






