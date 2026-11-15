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

> **Version 0.7.1** — See [CHANGELOG.md](CHANGELOG.md) for the full list of new
> features and breaking changes in this release.

> **New: controller advisor** (firmware 5.39 / 7.x). The integration can now
> tell you whether other controller settings would save electricity —
> simulated from your own history, without writing anything to the heat
> pump. See [Controller advisor](#controller-advisor).

## Introduction

A custom Home Assistant integration for Stiebel Eltron LWZ and Tecalor THZ
heat pumps. It talks to the heat pump over its serial protocol, by USB or
over the network (ser2net), and is set up entirely in the UI.

It is based on the FHEM module by Immi, adapted for Home Assistant with an
async architecture and UI configuration. Parts of it have been developed
with the help of AI.

## Features

| Topic | In short | Details |
|---|---|---|
| Sensors and settings | Temperatures, pressures, states, runtime hours, energy; settings as number, select, switch and time entities | [Entities](docs/entities.md) |
| Heating, hot water, ventilation | Climate entities for HC1/HC2, a water heater and a fan entity for unscheduled ventilation | [Entities](docs/entities.md#heating-hot-water-and-ventilation) |
| Energy and COP | Current, daily and lifetime COP (4.39 and newer) | [COP sensors](docs/entities.md#cop-sensors) |
| Fault memory | Sensors and an event for new faults; acknowledge or clear (4.x/5.x) | [Fault memory](docs/fault-memory.md) |
| Events and automations | Events for a new fault and a filter change, with examples | [Automations](docs/automations.md) |
| Services | Block refresh, raw register access, parameter backup/restore, diverter valve | [Services](docs/services.md) |
| Heating control | How the controller decides start and stop: formulas, settings, background | [Heating control](docs/heating-control.md) |
| **Controller advisor** (new) | Simulates controller settings from the history and suggests savings — advice only (5.39/7.x) | [Below](#controller-advisor), [Advisor](docs/advisor.md) |
| Configuration | Entity visibility tiers, sub-devices, per-block poll intervals, clock sync | [Configuration](docs/configuration.md) |
| Diagnostics and repairs | Diagnostics download; a drifted clock raises a fixable repair issue | [Troubleshooting](docs/troubleshooting.md) |

## Controller advisor

*New, firmware 5.39 / 7.x.* The advisor checks whether other settings of
the heating control would save electricity on **your** heat pump.

- **What it does:** it learns how your house and heat pump behave from the
  last 10 days in the recorder, simulates variants of KP, room influence
  and low end, and compares them with your current settings at the **same
  room temperature**. A setting that only makes the house cooler does not
  count as a saving.
- **What you see:** *Advisor: Possible Saving* in EUR/day with the
  recommendation (or "keep the current settings"), plus sensors for the
  predicted relative power, the margins to compressor start and stop and
  the model error. *Advisor: Run Now* recalculates at once; otherwise it
  runs daily.
- **When it advises:** only if its model predicts your measured relative
  power well enough (median error below 4 percentage points). Otherwise it
  says why it gives no advice.
- **What it never does:** write a setting or change the operating mode.
  Every result is a **simulation, not a measurement**, and no data leaves
  Home Assistant.
- **Setup:** keep the recorder running and the heat pump's sensors enabled;
  enter KP, design power and design temperature under **Configure** or let
  the advisor estimate them. External power meters can replace the heat
  pump's own power values; without a heating power value it is computed
  from the flow rate × ΔT, and without an electric power value the COP is
  estimated with Carnot, giving a minimum saving.

How the heat pump's controller works, with the formulas and background:
[docs/heating-control.md](docs/heating-control.md). Entities, options,
validation and limits of the advisor: [docs/advisor.md](docs/advisor.md).

## Installation

**Prerequisites:** a current Home Assistant release (tested with 2026.2;
releases before 2024.11 are not supported), a USB-to-serial adapter or a
ser2net server, and access to the heat pump's serial interface.

**HACS (recommended)**

1. Open HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/bigbadoooff/thz` with category **Integration**
3. Search for "Stiebel Eltron LWZ / Tecalor THZ", click **Download** and
   restart Home Assistant

**Manual:** copy the `thz` folder of the
[latest release](https://github.com/bigbadoooff/thz/releases) to
`<config_dir>/custom_components/thz/` and restart Home Assistant.

**Setup:** **Settings → Devices & Services → + Add integration →
"Stiebel Eltron LWZ / Tecalor THZ"**, choose USB or network and follow the
wizard. Settings can be changed later under **Reconfigure**; see
[Configuration](docs/configuration.md).

## How it works

- **Polling.** The heat pump never pushes data. Each register block is read
  on its own interval (600 s by default); settings are read once per write
  interval (1 hour by default) and right after a change from Home
  Assistant. See [How data is updated](docs/configuration.md#how-data-is-updated).
- **Fewer entities by default.** Schedules, advanced parameters and HC2
  are hidden until you enable them. See
  [Entity visibility](docs/configuration.md#entity-visibility).
- **Sub-devices.** Entities are grouped into heating circuits, hot water,
  ventilation, compressor, solar and cooling. See
  [Sub-devices](docs/configuration.md#sub-devices).

## Compatibility

| Firmware | Support |
|---|---|
| 2.06, 2.14, 2.14j | Sensors; settings via block read-modify-write |
| 4.19 | 4.39-like profile for the THZ 303 SOL |
| 4.39 | Full, incl. energy, COP, runtime hours, passive cooling |
| 5.09, 7.09 | 4.39-based with the 5.09 extras |
| 5.39, 7.59 | Full, incl. passive cooling energy and the controller advisor |
| Other | Falls back to the 4.39 maps — may work partially |

Confirmed working: LWZ5 with firmware 7.59. Other LWZ/THZ models may work;
please report yours. Details, firmware override and how the register maps
are loaded: [Firmware](docs/firmware.md).

## Known Limitations

- **One client per serial line.** FHEM or another tool on the same USB port
  or ser2net connection disturbs the communication.
- **No discovery.** USB and ser2net connections are set up by hand.
- **Settings update slowly.** A change at the control panel shows up after
  the next write interval, unless you refresh the entity.
- **Firmware-dependent features.** Fault memory needs 4.x/5.x, energy and
  COP 4.39 or newer, active cooling 5.x with cooling hardware; 2.x can show
  the ventilation but not start it. See [Firmware](docs/firmware.md).
- **Hot water mode** follows the heat pump's time program and operating
  mode; the water heater sets the temperature, not the mode.
- **Controller advisor:** modelled on the LWZ 5 CS Premium in mild weather;
  advice for frost is extrapolation. See [Advisor](docs/advisor.md#limits).

## Troubleshooting

- **"Handshake 1 failed" after a reboot:** another program (e.g. FHEM) holds
  the serial port.
- **No entities:** check the log for `thz`; the firmware may not be
  detected or a block not supported.
- **Debug logging:** **Enable debug logging** on the integration's page.

More, including logging and diagnostics:
[Troubleshooting](docs/troubleshooting.md).

## Removal

1. **Settings → Devices & Services → THZ** → three-dot menu → **Delete**.
   This stops polling and removes the device and its entities. The `thz.*`
   services stay registered until Home Assistant restarts.
2. Remove the files: in HACS → **Integrations** → "Stiebel Eltron LWZ /
   Tecalor THZ" → **Remove**, or delete `<config_dir>/custom_components/thz/`.
3. Restart Home Assistant.

No credentials or external accounts are created, so there is nothing else
to revoke.

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
